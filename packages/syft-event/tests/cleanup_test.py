"""
Unit tests for the cleanup module in syft-event package.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger


class TestParseTimeInterval:
    """Test the parse_time_interval function."""

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_parse_single_units(self, mock_syft_request, mock_client):
        """Test parsing single time units."""
        from syft_event.cleanup import parse_time_interval

        assert parse_time_interval("1d") == 24 * 60 * 60  # 1 day
        assert parse_time_interval("2h") == 2 * 60 * 60  # 2 hours
        assert parse_time_interval("30m") == 30 * 60  # 30 minutes
        assert parse_time_interval("45s") == 45  # 45 seconds

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_parse_combined_units(self, mock_syft_request, mock_client):
        """Test parsing combined time units."""
        from syft_event.cleanup import parse_time_interval

        assert parse_time_interval("1d2h30m") == (24 * 60 * 60) + (2 * 60 * 60) + (
            30 * 60
        )
        assert parse_time_interval("2h15m30s") == (2 * 60 * 60) + (15 * 60) + 30
        assert (
            parse_time_interval("1d12h30m45s")
            == (24 * 60 * 60) + (12 * 60 * 60) + (30 * 60) + 45
        )

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_parse_case_insensitive(self, mock_syft_request, mock_client):
        """Test that parsing is case insensitive."""
        from syft_event.cleanup import parse_time_interval

        assert parse_time_interval("1D") == parse_time_interval("1d")
        assert parse_time_interval("2H") == parse_time_interval("2h")
        assert parse_time_interval("30M") == parse_time_interval("30m")
        assert parse_time_interval("45S") == parse_time_interval("45s")

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_parse_empty_string(self, mock_syft_request, mock_client):
        """Test parsing empty string raises ValueError."""
        from syft_event.cleanup import parse_time_interval

        with pytest.raises(ValueError, match="Time interval cannot be empty"):
            parse_time_interval("")

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_parse_invalid_format(self, mock_syft_request, mock_client):
        """Test parsing invalid format raises ValueError."""
        from syft_event.cleanup import parse_time_interval

        with pytest.raises(ValueError, match="Invalid time interval format"):
            parse_time_interval("invalid")

        with pytest.raises(ValueError, match="Invalid time interval format"):
            parse_time_interval("1x")  # invalid unit


class TestCleanupStats:
    """Test the CleanupStats class."""

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_initialization(self, mock_syft_request, mock_client):
        """Test CleanupStats initialization."""
        from syft_event.cleanup import CleanupStats

        stats = CleanupStats()
        assert stats.requests_deleted == 0
        assert stats.responses_deleted == 0
        assert stats.errors == 0
        assert stats.last_cleanup is None

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_reset(self, mock_syft_request, mock_client):
        """Test resetting statistics."""
        from syft_event.cleanup import CleanupStats

        stats = CleanupStats()
        stats.requests_deleted = 5
        stats.responses_deleted = 3
        stats.errors = 1
        stats.last_cleanup = datetime.now(timezone.utc)

        stats.reset()

        assert stats.requests_deleted == 0
        assert stats.responses_deleted == 0
        assert stats.errors == 0
        # last_cleanup is not reset by reset() method

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_string_representation(self, mock_syft_request, mock_client):
        """Test string representation of CleanupStats."""
        from syft_event.cleanup import CleanupStats

        stats = CleanupStats()
        stats.requests_deleted = 5
        stats.responses_deleted = 3
        stats.errors = 1
        stats.last_cleanup = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        str_repr = str(stats)
        assert "requests=5" in str_repr
        assert "responses=3" in str_repr
        assert "errors=1" in str_repr
        assert "last_cleanup=2023-01-01 12:00:00+00:00" in str_repr


class TestPeriodicCleanup:
    """Test the PeriodicCleanup class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def mock_client(self, temp_dir):
        """Create a mock client for testing."""
        client = MagicMock()
        app_data_dir = temp_dir / "app_data"
        app_data_dir.mkdir(parents=True)
        client.app_data.return_value = app_data_dir
        return client

    @pytest.fixture
    def cleanup(self, mock_client):
        """Create a PeriodicCleanup instance for testing."""
        with patch("syft_event.cleanup.Client", return_value=mock_client):
            with patch("syft_event.cleanup.SyftRequest"):
                from syft_event.cleanup import PeriodicCleanup

                return PeriodicCleanup(
                    app_name="test_app",
                    cleanup_interval="1h",
                    cleanup_expiry="1d",
                    client=mock_client,
                )

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_initialization(self, mock_syft_request, mock_client):
        """Test PeriodicCleanup initialization."""
        from syft_event.cleanup import PeriodicCleanup

        cleanup = PeriodicCleanup(
            app_name="test_app",
            cleanup_interval="2h",
            cleanup_expiry="3d",
            client=mock_client,
        )

        assert cleanup.app_name == "test_app"
        assert cleanup.cleanup_interval_seconds == 2 * 60 * 60
        assert cleanup.cleanup_interval_str == "2h"
        assert cleanup.cleanup_expiry_seconds == 3 * 24 * 60 * 60
        assert cleanup.cleanup_expiry_str == "3d"
        assert cleanup.client == mock_client
        assert not cleanup._is_running
        from syft_event.cleanup import CleanupStats

        assert isinstance(cleanup.stats, CleanupStats)

    def test_start_and_stop(self, cleanup):
        """Test starting and stopping the cleanup service."""
        # Initially not running
        assert not cleanup.is_running()

        # Start the service
        cleanup.start()

        # Give the thread a moment to start
        import time

        time.sleep(0.1)
        assert cleanup.is_running()

        # Stop the service
        cleanup.stop()

        # Give the thread a moment to stop
        time.sleep(0.1)
        assert not cleanup.is_running()

    def test_cleanup_now_with_no_files(self, cleanup):
        """Test cleanup_now when no files exist."""
        # Create the RPC directory but no files
        cleanup.app_rpc_dir.mkdir(parents=True)

        stats = cleanup.cleanup_now()

        assert stats.requests_deleted == 0
        assert stats.responses_deleted == 0
        assert stats.errors == 0
        assert stats.last_cleanup is not None

    def test_cleanup_single_request_old_file(self, cleanup):
        """Test cleaning up an old request file."""
        # Create RPC directory structure
        cleanup.app_rpc_dir.mkdir(parents=True)
        sender_dir = cleanup.app_rpc_dir / "alice@example.com"
        sender_dir.mkdir()

        # Create old request file
        request_path = sender_dir / "test.request"
        request_path.touch()

        # Use current time as base to ensure consistency with cleanup logic
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(seconds=cleanup.cleanup_expiry_seconds)

        def mock_load(path):
            class MockRequest:
                def __init__(self, created_time):
                    # Ensure timezone-aware datetime
                    self.created = (
                        created_time.replace(tzinfo=timezone.utc)
                        if created_time.tzinfo is None
                        else created_time
                    )

            # File is older than cutoff (should be deleted)
            old_time = cutoff_date - timedelta(hours=1)
            return MockRequest(old_time)

        with patch("syft_rpc.protocol.SyftRequest.load", side_effect=mock_load):
            cleanup._cleanup_single_request(request_path, cutoff_date)

            # File should be deleted
            assert not request_path.exists()

    def test_cleanup_single_request_new_file(self, cleanup):
        """Test that new files are not deleted."""
        # Create RPC directory structure
        cleanup.app_rpc_dir.mkdir(parents=True)
        sender_dir = cleanup.app_rpc_dir / "alice@example.com"
        sender_dir.mkdir()

        # Create new request file
        request_path = sender_dir / "test.request"
        request_path.touch()

        # Use current time as base to ensure consistency with cleanup logic
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(seconds=cleanup.cleanup_expiry_seconds)

        def mock_load(path):
            class MockRequest:
                def __init__(self, created_time):
                    # Ensure timezone-aware datetime
                    self.created = (
                        created_time.replace(tzinfo=timezone.utc)
                        if created_time.tzinfo is None
                        else created_time
                    )

            # File is newer than cutoff (should NOT be deleted)
            new_time = cutoff_date + timedelta(hours=1)
            return MockRequest(new_time)

        with patch("syft_rpc.protocol.SyftRequest.load", side_effect=mock_load):
            cleanup._cleanup_single_request(request_path, cutoff_date)

            # File should still exist
            assert request_path.exists()

    def test_perform_cleanup_with_files(self, cleanup):
        """Test perform_cleanup with actual files."""
        # Create RPC directory structure
        cleanup.app_rpc_dir.mkdir(parents=True)
        sender_dir = cleanup.app_rpc_dir / "alice@example.com"
        sender_dir.mkdir()

        # Create old request files
        old_request = sender_dir / "old.request"
        old_request.touch()

        new_request = sender_dir / "new.request"
        new_request.touch()

        # Mock SyftRequest.load to return different timestamps
        # Use current time as base to ensure consistency with cleanup logic
        now = datetime.now(timezone.utc)

        # Calculate the cutoff date that the cleanup logic will use
        cutoff_date = now - timedelta(seconds=cleanup.cleanup_expiry_seconds)

        logger.info(f"Debug: cleanup_expiry_seconds = {cleanup.cleanup_expiry_seconds}")
        logger.info(f"Debug: now = {now}")
        logger.info(f"Debug: cutoff_date = {cutoff_date}")

        # Mock SyftRequest.load to return controlled timestamps
        # This tests the actual time-based logic
        def mock_load(path):
            # Create a simple object with a real datetime attribute
            class MockRequest:
                def __init__(self, created_time):
                    self.created = created_time

            logger.info(f"Debug: path = {path}")
            logger.info(f"Debug: cutoff_date = {cutoff_date}")
            if "old" in str(path):
                # Old file: definitely older than cutoff (should be deleted)
                old_time = cutoff_date - timedelta(hours=2)
                logger.info(f"Debug: old_time = {old_time}")
                return MockRequest(old_time)
            else:
                # New file: definitely newer than cutoff (should NOT be deleted)
                new_time = cutoff_date + timedelta(hours=2)
                logger.info(f"Debug: new_time = {new_time}")
                return MockRequest(new_time)

        with patch("syft_rpc.protocol.SyftRequest.load", side_effect=mock_load):
            logger.info(
                f"Debug: Performing cleanup, old_request = {old_request}, new_request = {new_request}"
            )
            stats = cleanup.perform_cleanup()

            logger.info(f"Debug: Stats = {stats}")

            # Only old file should be deleted (cleanup_expiry="1d")
            assert (
                not old_request.exists()
            ), f"Old file should be deleted. Path: {old_request}"
            assert (
                new_request.exists() is True
            ), f"New file should still exist. Path: {new_request}"
            assert (
                stats.requests_deleted == 1
            ), f"Expected 1 request deleted, got {stats.requests_deleted}"
            assert stats.errors == 0, f"Expected 0 errors, got {stats.errors}"

    def test_get_stats(self, cleanup):
        """Test getting cleanup statistics."""
        from syft_event.cleanup import CleanupStats

        stats = cleanup.get_stats()
        assert isinstance(stats, CleanupStats)
        assert stats == cleanup.stats


class TestCreateCleanupCallback:
    """Test the create_cleanup_callback function."""

    @patch("syft_event.cleanup.Client")
    @patch("syft_event.cleanup.SyftRequest")
    def test_create_cleanup_callback(self, mock_syft_request, mock_client):
        """Test creating a cleanup callback function."""
        from syft_event.cleanup import CleanupStats, create_cleanup_callback

        app_name = "test_app"
        callback = create_cleanup_callback(app_name)

        assert callable(callback)

        # Test the callback with mock stats
        stats = CleanupStats()
        stats.requests_deleted = 5
        stats.responses_deleted = 3
        stats.errors = 1

        # Should not raise exception
        callback(stats)
