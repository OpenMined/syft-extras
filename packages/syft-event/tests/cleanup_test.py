"""
Unit tests for the cleanup module in syft-event package.
"""

import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add the source directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Mock the dependencies before importing

# Mock syft_core
mock_syft_core = types.ModuleType("syft_core")
mock_client = types.ModuleType("Client")
mock_syft_core.Client = mock_client
sys.modules["syft_core"] = mock_syft_core

# Mock syft_rpc
mock_syft_rpc = types.ModuleType("syft_rpc")
mock_protocol = types.ModuleType("protocol")
mock_syft_rpc.protocol = mock_protocol
sys.modules["syft_rpc"] = mock_syft_rpc
sys.modules["syft_rpc.protocol"] = mock_protocol


# Mock SyftRequest
class MockSyftRequest:
    def __init__(self, created=None):
        self.created = created or datetime.now(timezone.utc)

    @classmethod
    def load(cls, path):
        return cls()


mock_protocol.SyftRequest = MockSyftRequest


# Mock Client
class MockClient:
    def __init__(self):
        pass

    @classmethod
    def load(cls):
        return cls()

    def app_data(self, app_name):
        return Path("/tmp/test_app_data")


mock_syft_core.Client = MockClient

# Now import the cleanup module directly
spec = importlib.util.spec_from_file_location(
    "cleanup", os.path.join(os.path.dirname(__file__), "..", "syft_event", "cleanup.py")
)
cleanup_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup_module)

# Extract the classes and functions
parse_time_interval = cleanup_module.parse_time_interval
CleanupStats = cleanup_module.CleanupStats
PeriodicCleanup = cleanup_module.PeriodicCleanup
create_cleanup_callback = cleanup_module.create_cleanup_callback


class TestParseTimeInterval:
    """Test the parse_time_interval function."""

    def test_parse_single_units(self):
        """Test parsing single time units."""
        assert parse_time_interval("1d") == 24 * 60 * 60  # 1 day
        assert parse_time_interval("2h") == 2 * 60 * 60  # 2 hours
        assert parse_time_interval("30m") == 30 * 60  # 30 minutes
        assert parse_time_interval("45s") == 45  # 45 seconds

    def test_parse_combined_units(self):
        """Test parsing combined time units."""
        assert parse_time_interval("1d2h30m") == (24 * 60 * 60) + (2 * 60 * 60) + (
            30 * 60
        )
        assert parse_time_interval("2h15m30s") == (2 * 60 * 60) + (15 * 60) + 30
        assert (
            parse_time_interval("1d12h30m45s")
            == (24 * 60 * 60) + (12 * 60 * 60) + (30 * 60) + 45
        )

    def test_parse_case_insensitive(self):
        """Test that parsing is case insensitive."""
        assert parse_time_interval("1D") == parse_time_interval("1d")
        assert parse_time_interval("2H") == parse_time_interval("2h")
        assert parse_time_interval("30M") == parse_time_interval("30m")
        assert parse_time_interval("45S") == parse_time_interval("45s")

    def test_parse_empty_string(self):
        """Test parsing empty string raises ValueError."""
        with pytest.raises(ValueError, match="Time interval cannot be empty"):
            parse_time_interval("")

    def test_parse_invalid_format(self):
        """Test parsing invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid time interval format"):
            parse_time_interval("invalid")

        with pytest.raises(ValueError, match="Invalid time interval format"):
            parse_time_interval("1x")  # invalid unit


class TestCleanupStats:
    """Test the CleanupStats class."""

    def test_initialization(self):
        """Test CleanupStats initialization."""
        stats = CleanupStats()
        assert stats.requests_deleted == 0
        assert stats.responses_deleted == 0
        assert stats.errors == 0
        assert stats.last_cleanup is None

    def test_reset(self):
        """Test resetting statistics."""
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

    def test_string_representation(self):
        """Test string representation of CleanupStats."""
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
        client = MagicMock(spec=MockClient)
        app_data_dir = temp_dir / "app_data"
        app_data_dir.mkdir(parents=True)
        client.app_data.return_value = app_data_dir
        return client

    @pytest.fixture
    def cleanup(self, mock_client):
        """Create a PeriodicCleanup instance for testing."""
        return PeriodicCleanup(
            app_name="test_app",
            cleanup_interval="1h",
            cleanup_expiry="1d",
            client=mock_client,
        )

    def test_initialization(self, mock_client):
        """Test PeriodicCleanup initialization."""
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
        assert isinstance(cleanup.stats, CleanupStats)

    def test_start_and_stop(self, cleanup):
        """Test starting and stopping the cleanup service."""
        # Initially not running
        assert not cleanup.is_running()

        # Start the service
        cleanup.start()
        assert cleanup.is_running()

        # Stop the service
        cleanup.stop()
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
        old_time = datetime.now(timezone.utc) - timedelta(days=2)

        # Mock SyftRequest.load to return a request with old timestamp
        mock_request = MagicMock()
        mock_request.created = old_time

        with patch.object(cleanup_module, "SyftRequest", MockSyftRequest):
            # Override the load method
            original_load = MockSyftRequest.load
            MockSyftRequest.load = lambda path: mock_request

            try:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=1)
                cleanup._cleanup_single_request(request_path, cutoff_date)

                # File should be deleted
                assert not request_path.exists()
            finally:
                MockSyftRequest.load = original_load

    def test_cleanup_single_request_new_file(self, cleanup):
        """Test that new files are not deleted."""
        # Create RPC directory structure
        cleanup.app_rpc_dir.mkdir(parents=True)
        sender_dir = cleanup.app_rpc_dir / "alice@example.com"
        sender_dir.mkdir()

        # Create new request file
        request_path = sender_dir / "test.request"
        request_path.touch()

        new_time = datetime.now(timezone.utc) - timedelta(hours=1)

        # Mock SyftRequest.load to return a request with new timestamp
        mock_request = MagicMock()
        mock_request.created = new_time

        with patch.object(cleanup_module, "SyftRequest", MockSyftRequest):
            # Override the load method
            original_load = MockSyftRequest.load
            MockSyftRequest.load = lambda path: mock_request

            try:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=1)
                cleanup._cleanup_single_request(request_path, cutoff_date)

                # File should still exist
                assert request_path.exists()
            finally:
                MockSyftRequest.load = original_load

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
        def mock_load(path):
            mock_request = MagicMock()
            if "old" in str(path):
                mock_request.created = datetime.now(timezone.utc) - timedelta(days=2)
            else:
                mock_request.created = datetime.now(timezone.utc) - timedelta(hours=1)
            return mock_request

        with patch.object(cleanup_module, "SyftRequest", MockSyftRequest):
            # Override the load method
            original_load = MockSyftRequest.load
            MockSyftRequest.load = mock_load

            try:
                stats = cleanup.perform_cleanup()

                # Only old file should be deleted
                assert not old_request.exists()
                assert new_request.exists()
                assert stats.requests_deleted == 1
                assert stats.errors == 0
            finally:
                MockSyftRequest.load = original_load

    def test_get_stats(self, cleanup):
        """Test getting cleanup statistics."""
        stats = cleanup.get_stats()
        assert isinstance(stats, CleanupStats)
        assert stats == cleanup.stats


class TestCreateCleanupCallback:
    """Test the create_cleanup_callback function."""

    def test_create_cleanup_callback(self):
        """Test creating a cleanup callback function."""
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
