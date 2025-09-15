"""
Periodic cleanup utility for Syft Events server.

This module provides utilities for cleaning up old request and response files
that are older than a specified time threshold. It can be used both as a
standalone utility and integrated into the SyftEvents server.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional

from loguru import logger
from syft_core import Client
from syft_rpc.protocol import SyftRequest


def parse_time_interval(interval_str: str) -> int:
    """
    Parse a human-readable time interval string into seconds.

    Supports formats like:
    - "1d" (1 day)
    - "2h" (2 hours)
    - "30m" (30 minutes)
    - "45s" (45 seconds)
    - "1d2h30m" (1 day, 2 hours, 30 minutes)

    Args:
        interval_str: Time interval string (e.g., "1d", "2h", "30m")

    Returns:
        Time interval in seconds

    Raises:
        ValueError: If the interval string format is invalid
    """
    if not interval_str:
        raise ValueError("Time interval cannot be empty")

    # Pattern to match time units: number + unit (d/h/m/s)
    pattern = r"(\d+)([dhms])"
    matches = re.findall(pattern, interval_str.lower())

    if not matches:
        raise ValueError(
            f"Invalid time interval format: {interval_str}. "
            "Must be in the format of '1d', '2h', '30m', '1d2h30m', etc."
        )

    total_seconds = 0
    unit_multipliers = {
        "d": 24 * 60 * 60,  # days to seconds
        "h": 60 * 60,  # hours to seconds
        "m": 60,  # minutes to seconds
        "s": 1,  # seconds
    }

    for value, unit in matches:
        if unit not in unit_multipliers:
            raise ValueError(f"Unknown time unit: {unit}")

        total_seconds += int(value) * unit_multipliers[unit]

    if total_seconds <= 0:
        raise ValueError("Time interval must be positive")

    return total_seconds


class CleanupStats:
    """Statistics for cleanup operations."""

    def __init__(self):
        self.requests_deleted: int = 0
        self.responses_deleted: int = 0
        self.errors: int = 0
        self.last_cleanup: Optional[datetime] = None

    def reset(self):
        """Reset statistics."""
        self.requests_deleted = 0
        self.responses_deleted = 0
        self.errors = 0

    def __str__(self) -> str:
        return (
            f"CleanupStats(requests={self.requests_deleted}, "
            f"responses={self.responses_deleted}, "
            f"errors={self.errors}, "
            f"last_cleanup={self.last_cleanup})"
        )


class PeriodicCleanup:
    """
    A utility class for periodically cleaning up old request and response files.

    This class can be used in two modes:
    1. Standalone: Run as a background thread that periodically performs cleanup
    2. Integrated: Used within SyftEvents server for automatic cleanup

    Features:
    - Configurable cleanup intervals
    - Age-based file deletion
    - Statistics tracking
    - Error handling and logging
    - Graceful shutdown
    """

    def __init__(
        self,
        app_name: str,
        cleanup_interval: str = "1d",
        cleanup_expiry: str = "30d",
        client: Optional[Client] = None,
        on_cleanup_complete: Optional[Callable[[CleanupStats], None]] = None,
    ):
        """
        Initialize the periodic cleanup utility.

        Args:
            app_name: Name of the Syft application
            cleanup_interval: How often to run cleanup. Can be:
                - String: Human-readable format (e.g., "1d", "2h", "30m", "1d2h30m")
            cleanup_expiry: How long to keep files. Can be:
                - String: Human-readable format (e.g., "1d", "2h", "30m", "1d2h30m")
            client: Syft client instance (auto-loaded if not provided)
            on_cleanup_complete: Optional callback function called after each cleanup
        """
        self.app_name = app_name

        # Parse cleanup interval
        self.cleanup_interval_seconds = parse_time_interval(cleanup_interval)
        self.cleanup_interval_str = cleanup_interval

        # Parse cleanup expiry
        self.cleanup_expiry_seconds = parse_time_interval(cleanup_expiry)
        self.cleanup_expiry_str = cleanup_expiry

        self.client = client or Client.load()
        self.on_cleanup_complete = on_cleanup_complete

        # Setup paths
        self.app_dir = self.client.app_data(self.app_name)
        self.app_rpc_dir = self.app_dir / "rpc"

        # Threading control
        self._stop_event = Event()
        self._cleanup_thread: Optional[Thread] = None
        self._is_running = False

        # Statistics
        self.stats = CleanupStats()

    def start(self) -> None:
        """Start the periodic cleanup in a background thread."""
        if self._is_running:
            logger.warning("PeriodicCleanup is already running")
            return

        self._stop_event.clear()
        self._cleanup_thread = Thread(
            target=self._cleanup_loop,
            name=f"PeriodicCleanup-{self.app_name}",
            daemon=True,
        )
        self._cleanup_thread.start()
        self._is_running = True

    def stop(self) -> None:
        """Stop the periodic cleanup."""
        if not self._is_running:
            return

        logger.info(f"Stopping periodic cleanup for {self.app_name}")
        self._stop_event.set()

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=10)
            if self._cleanup_thread.is_alive():
                logger.warning("Cleanup thread did not stop gracefully")

        self._is_running = False
        logger.info(f"Stopped periodic cleanup for {self.app_name}")

    def _cleanup_loop(self) -> None:
        """Main cleanup loop that runs in the background thread."""
        logger.info(
            f"🧹 Started cleanup service for {self.app_name} - "
            f"will run every {self.cleanup_interval_str} and delete files older than "
            f"{self.cleanup_expiry_str}"
        )

        while not self._stop_event.is_set():
            try:
                # Perform cleanup
                self.perform_cleanup()

                # Wait for next cleanup interval or until stopped
                self._stop_event.wait(timeout=self.cleanup_interval_seconds)

            except Exception as e:
                logger.error(f"Error in cleanup loop for {self.app_name}: {e}")
                # Wait a bit before retrying
                self._stop_event.wait(timeout=300)  # 5 minutes

    def perform_cleanup(self) -> CleanupStats:
        """
        Perform a single cleanup operation.

        Returns:
            CleanupStats object with the results of the cleanup
        """
        logger.info(
            f"🧹 Cleaning up {self.app_name} - deleting files older than "
            f"{self.cleanup_expiry_str}"
        )

        # Reset statistics
        self.stats.reset()
        self.stats.last_cleanup = datetime.now(timezone.utc)

        if not self.app_rpc_dir.exists():
            logger.warning(f"RPC directory does not exist: {self.app_rpc_dir}")
            return self.stats

        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            seconds=self.cleanup_expiry_seconds
        )

        # Find and clean up request files
        for request_path in self.app_rpc_dir.glob("**/*.request"):
            try:
                self._cleanup_single_request(request_path, cutoff_date)
            except Exception as e:
                logger.error(f"Error cleaning up {request_path}: {e}")
                self.stats.errors += 1

        # Call completion callback if provided
        if self.on_cleanup_complete:
            try:
                self.on_cleanup_complete(self.stats)
            except Exception as e:
                logger.error(f"Error in cleanup completion callback: {e}")

        return self.stats

    def _cleanup_single_request(
        self, request_path: Path, cutoff_date: datetime
    ) -> None:
        """Clean up a single request file and its corresponding response."""
        if not request_path.exists():
            return

        try:
            # Load the request to check its creation date
            req = SyftRequest.load(request_path)

            created = req.created
            created = created.astimezone(timezone.utc)
            cutoff_date = cutoff_date.astimezone(timezone.utc)

            if created < cutoff_date:
                # Delete request file
                request_path.unlink(missing_ok=True)
                self.stats.requests_deleted += 1

                # Delete corresponding response file if it exists
                response_path = request_path.with_suffix(".response")
                if response_path.exists():
                    response_path.unlink(missing_ok=True)
                    self.stats.responses_deleted += 1

        except Exception as e:
            logger.warning(f"Error processing {request_path}: {e}")
            self.stats.errors += 1

    def cleanup_now(self) -> CleanupStats:
        """
        Perform cleanup immediately without waiting for the next interval.

        Returns:
            CleanupStats object with the results
        """
        return self.perform_cleanup()

    def get_stats(self) -> CleanupStats:
        """Get the current cleanup statistics."""
        return self.stats

    def is_running(self) -> bool:
        """Check if the periodic cleanup is currently running."""
        return self._is_running


def create_cleanup_callback(app_name: str) -> Callable[[CleanupStats], None]:
    """
    Create a standard cleanup completion callback that logs statistics.

    Args:
        app_name: Name of the application for logging context

    Returns:
        Callback function that logs cleanup statistics
    """

    def callback(stats: CleanupStats) -> None:
        logger.info(
            f"[{app_name}] Cleanup completed: "
            f"{stats.requests_deleted} requests, "
            f"{stats.responses_deleted} responses, "
            f"{stats.errors} errors, "
        )

    return callback


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up old Syft request/response files"
    )
    parser.add_argument("--app", help="Specific app to clean up (default: all apps)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't actually delete files"
    )
    parser.add_argument(
        "--interval",
        default="24h",
        help="Cleanup interval (e.g., '1d', '2h', '30m', '1d2h30m')",
    )

    args = parser.parse_args()

    if args.app:
        cleanup = PeriodicCleanup(
            app_name=args.app,
            cleanup_interval=args.interval,
        )

        try:
            cleanup.start()
            print(f"Periodic cleanup started for {args.app}. Press Ctrl+C to stop.")
        except KeyboardInterrupt:
            print("\nStopping periodic cleanup...")
            cleanup.stop()
            exit(0)
    else:
        print("No app specified. Please specify an app to clean up.")
        exit(1)
