"""Test the client module for syft-http-bridge package."""

import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from syft_http_bridge.client import (
    _prepare_request,
    send_request_file,
    wait_for_response_file,
    get_response_file,
    FileSystemTransport,
    SyftFileTransport,
    create_syft_http_client,
)
from syft_http_bridge.constants import REQUEST_ID_HEADER, USER_HEADER
from syft_http_bridge.serde import serialize_response, deserialize_request


class TestPrepareRequest:
    """Test request preparation function."""

    def test_prepare_request_basic(self):
        """Test basic request preparation."""
        request = httpx.Request("GET", "https://example.com")
        request_id = uuid.uuid4()
        
        prepared = _prepare_request(request, request_id)
        
        assert REQUEST_ID_HEADER in prepared.headers
        assert prepared.headers[REQUEST_ID_HEADER] == str(request_id)
        assert USER_HEADER not in prepared.headers

    def test_prepare_request_with_user(self):
        """Test request preparation with user."""
        request = httpx.Request("POST", "https://example.com/api")
        request_id = uuid.uuid4()
        user = "alice@example.com"
        
        prepared = _prepare_request(request, request_id, requesting_user=user)
        
        assert prepared.headers[REQUEST_ID_HEADER] == str(request_id)
        assert prepared.headers[USER_HEADER] == user

    def test_prepare_request_preserves_existing_headers(self):
        """Test that existing headers are preserved."""
        headers = {
            "Authorization": "Bearer token",
            "Content-Type": "application/json",
        }
        request = httpx.Request("GET", "https://example.com", headers=headers)
        request_id = uuid.uuid4()
        
        prepared = _prepare_request(request, request_id)
        
        # Original headers should be preserved
        assert prepared.headers["Authorization"] == "Bearer token"
        assert prepared.headers["Content-Type"] == "application/json"
        # New headers should be added
        assert REQUEST_ID_HEADER in prepared.headers


class TestSendRequestFile:
    """Test sending request files."""

    def test_send_request_file_basic(self):
        """Test basic request file sending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            request = httpx.Request("GET", "https://example.com/test")
            
            request_id = send_request_file(request, requests_dir)
            
            # Check that request_id is a valid UUID
            assert isinstance(request_id, uuid.UUID)
            
            # Check that file was created
            request_file = requests_dir / f"{request_id}.request"
            assert request_file.exists()
            
            # Verify file content
            saved_data = request_file.read_bytes()
            deserialized = deserialize_request(saved_data)
            assert deserialized.method == "GET"
            assert str(deserialized.url) == "https://example.com/test"
            assert deserialized.headers[REQUEST_ID_HEADER] == str(request_id)

    def test_send_request_file_with_user(self):
        """Test sending request file with user."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            request = httpx.Request("POST", "https://example.com/api")
            user = "bob@example.com"
            
            request_id = send_request_file(request, requests_dir, requesting_user=user)
            
            # Verify file content
            request_file = requests_dir / f"{request_id}.request"
            saved_data = request_file.read_bytes()
            deserialized = deserialize_request(saved_data)
            assert deserialized.headers[USER_HEADER] == user

    def test_send_request_file_creates_directory(self):
        """Test that send_request_file creates directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a non-existent subdirectory
            requests_dir = Path(tmpdir) / "deep" / "nested" / "requests"
            assert not requests_dir.exists()
            
            request = httpx.Request("GET", "https://example.com")
            request_id = send_request_file(request, requests_dir)
            
            # Directory should now exist
            assert requests_dir.exists()
            assert (requests_dir / f"{request_id}.request").exists()


class TestGetResponseFile:
    """Test getting response files."""

    def test_get_response_file_exists(self):
        """Test getting a response file that exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create a mock response file
            response = httpx.Response(200, content=b'{"status": "ok"}')
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(serialize_response(response))
            
            # Get response
            result = get_response_file(request_id, responses_dir, delete_response=False)
            
            assert result is not None
            assert result.status_code == 200
            assert result.content == b'{"status": "ok"}'
            assert response_file.exists()  # File should still exist

    def test_get_response_file_with_delete(self):
        """Test getting a response file with deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create a mock response file
            response = httpx.Response(200, content=b'{"deleted": true}')
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(serialize_response(response))
            
            # Get response with deletion
            result = get_response_file(request_id, responses_dir, delete_response=True)
            
            assert result is not None
            assert result.status_code == 200
            assert not response_file.exists()  # File should be deleted

    def test_get_response_file_not_exists(self):
        """Test getting a response file that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Try to get non-existent response
            result = get_response_file(request_id, responses_dir)
            
            assert result is None

    def test_get_response_file_invalid_data(self):
        """Test getting a response file with invalid data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create invalid response file
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(b"invalid data")
            
            # Should return None on error
            result = get_response_file(request_id, responses_dir)
            assert result is None


class TestWaitForResponseFile:
    """Test waiting for response files."""

    def test_wait_for_response_file_immediate(self):
        """Test waiting for a response that's already there."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create a mock response file
            response = httpx.Response(200, content=b'{"status": "ok"}')
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(serialize_response(response))
            
            # Wait for response
            result = wait_for_response_file(request_id, responses_dir, timeout=1.0)
            
            assert result is not None
            assert result.status_code == 200
            assert result.content == b'{"status": "ok"}'

    def test_wait_for_response_file_delayed(self):
        """Test waiting for a response that appears later."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create response file after a delay in a separate thread
            import threading
            
            def create_response_after_delay():
                time.sleep(0.2)  # 200ms delay
                response = httpx.Response(201, content=b"Created")
                response_file = responses_dir / f"{request_id}.response"
                response_file.write_bytes(serialize_response(response))
            
            thread = threading.Thread(target=create_response_after_delay)
            thread.start()
            
            # Wait for response
            start_time = time.time()
            result = wait_for_response_file(request_id, responses_dir, timeout=1.0)
            elapsed = time.time() - start_time
            
            thread.join()
            
            assert result is not None
            assert result.status_code == 201
            assert 0.2 <= elapsed < 0.5  # Should take around 200ms

    def test_wait_for_response_file_timeout(self):
        """Test waiting for a response that never comes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Wait for response that will never come
            start_time = time.time()
            with pytest.raises(TimeoutError):
                wait_for_response_file(request_id, responses_dir, timeout=0.5)
            elapsed = time.time() - start_time
            
            assert 0.5 <= elapsed < 0.7  # Should timeout after ~500ms

    def test_wait_for_response_file_invalid_response(self):
        """Test waiting when response file contains invalid data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            responses_dir = Path(tmpdir) / "responses"
            responses_dir.mkdir(parents=True)
            
            request_id = uuid.uuid4()
            
            # Create invalid response file
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(b"invalid data")
            
            # Should raise TimeoutError because get_response_file returns None for invalid data
            with pytest.raises(TimeoutError):
                wait_for_response_file(request_id, responses_dir, timeout=0.5)


class TestFileSystemTransport:
    """Test FileSystemTransport class."""

    def test_transport_initialization(self):
        """Test transport initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            responses_dir = Path(tmpdir) / "responses"
            
            transport = FileSystemTransport(
                requests_dir=requests_dir,
                responses_dir=responses_dir,
                requesting_user="user@example.com",
                timeout=30.0,
            )
            
            assert transport.requests_dir == requests_dir
            assert transport.responses_dir == responses_dir
            assert transport.requesting_user == "user@example.com"
            assert transport.timeout == 30.0
            assert requests_dir.exists()
            assert responses_dir.exists()

    @patch('syft_http_bridge.client.send_request_file')
    @patch('syft_http_bridge.client.wait_for_response_file')
    def test_transport_handle_request_success(self, mock_wait, mock_send):
        """Test successful request handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            responses_dir = Path(tmpdir) / "responses"
            
            request_id = uuid.uuid4()
            mock_send.return_value = request_id
            
            mock_response = httpx.Response(200, content=b'{"result": "success"}')
            mock_wait.return_value = mock_response
            
            # Create transport
            transport = FileSystemTransport(
                requests_dir=requests_dir,
                responses_dir=responses_dir,
                requesting_user="user@example.com",
            )
            
            # Make request
            request = httpx.Request("GET", "https://api.example.com/data")
            response = transport.handle_request(request)
            
            # Verify calls
            mock_send.assert_called_once()
            mock_wait.assert_called_once_with(
                request_id,
                transport.responses_dir,
                transport.timeout,
                transport.poll_interval,
                transport.delete_response,
            )
            
            # Verify response
            assert response.status_code == 200
            assert response.content == b'{"result": "success"}'

    @patch('syft_http_bridge.client.send_request_file')
    @patch('syft_http_bridge.client.wait_for_response_file')
    def test_transport_handle_request_timeout(self, mock_wait, mock_send):
        """Test request timeout handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            responses_dir = Path(tmpdir) / "responses"
            
            request_id = uuid.uuid4()
            mock_send.return_value = request_id
            mock_wait.side_effect = TimeoutError("Timed out")
            
            # Create transport with short timeout
            transport = FileSystemTransport(
                requests_dir=requests_dir,
                responses_dir=responses_dir,
                requesting_user="user@example.com",
                timeout=0.1,
            )
            
            # Make request - should raise TimeoutError
            request = httpx.Request("GET", "https://api.example.com/data")
            with pytest.raises(TimeoutError):
                transport.handle_request(request)


class TestCreateSyftHttpClient:
    """Test create_syft_http_client function."""

    def test_create_client_basic(self):
        """Test basic client creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "app_data"
            mock_syft_client = Mock()
            mock_syft_client.email = "test@example.com"
            mock_syft_client.app_data = Mock(return_value=app_dir)
            
            client = create_syft_http_client(
                app_name="my_app",
                host="example.com",
                syftbox_client=mock_syft_client,
            )
            
            assert isinstance(client, httpx.Client)
            assert isinstance(client._transport, SyftFileTransport)
            assert client._transport.app_name == "my_app"
            assert client._transport.syftbox_client.email == "test@example.com"

    def test_create_client_with_timeout(self):
        """Test client creation with custom timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "app_data"
            mock_syft_client = Mock()
            mock_syft_client.email = "default@example.com"
            mock_syft_client.app_data = Mock(return_value=app_dir)
            
            client = create_syft_http_client(
                app_name="custom_app",
                host="example.com",
                syftbox_client=mock_syft_client,
                timeout=30.0,
            )
            
            assert client._transport.timeout == 30.0

    def test_client_usage(self):
        """Test using the created client."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "app_data"
            mock_syft_client = Mock()
            mock_syft_client.email = "user@example.com"
            mock_syft_client.app_data = Mock(return_value=app_dir)
            
            client = create_syft_http_client(
                app_name="test_app",
                host="example.com",
                syftbox_client=mock_syft_client,
            )
            
            # Mock the transport's handle_request method
            mock_response = httpx.Response(200, json={"users": ["alice", "bob"]})
            client._transport.handle_request = Mock(return_value=mock_response)
            
            # Make a request
            response = client.get("https://api.example.com/users")
            
            assert response.status_code == 200
            assert response.json() == {"users": ["alice", "bob"]}
            client._transport.handle_request.assert_called_once()


def test_integration_request_response_cycle():
    """Test complete request-response cycle integration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        requests_dir = base_dir / "requests"
        responses_dir = base_dir / "responses"
        
        requests_dir.mkdir(parents=True)
        responses_dir.mkdir(parents=True)
        
        # Send request
        request = httpx.Request(
            "POST",
            "https://api.example.com/users",
            json={"name": "Alice", "role": "admin"},
        )
        
        request_id = send_request_file(request, requests_dir, requesting_user="admin@example.com")
        
        # Simulate processing the request and creating response
        import threading
        
        def process_request():
            time.sleep(0.1)
            # Read the request
            request_file = requests_dir / f"{request_id}.request"
            request_data = request_file.read_bytes()
            saved_request = deserialize_request(request_data)
            
            # Verify request properties
            assert saved_request.headers[USER_HEADER] == "admin@example.com"
            assert saved_request.headers[REQUEST_ID_HEADER] == str(request_id)
            
            # Create response
            response = httpx.Response(
                201,
                json={"id": 123, "name": "Alice", "role": "admin"},
                headers={"Content-Type": "application/json"},
            )
            
            # Save response
            response_file = responses_dir / f"{request_id}.response"
            response_file.write_bytes(serialize_response(response))
        
        # Start processing in background
        thread = threading.Thread(target=process_request)
        thread.start()
        
        # Wait for response
        response = wait_for_response_file(request_id, responses_dir, timeout=1.0)
        
        thread.join()
        
        # Verify response
        assert response is not None
        assert response.status_code == 201
        assert response.json() == {"id": 123, "name": "Alice", "role": "admin"}