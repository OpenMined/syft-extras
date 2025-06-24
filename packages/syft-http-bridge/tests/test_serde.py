"""Test the serialization/deserialization module for syft-http-bridge package."""

import pytest
import httpx
from syft_http_bridge.serde import (
    serialize_request,
    deserialize_request,
    serialize_response,
    deserialize_response,
    _read_content,
    _extract_serializable_extensions,
)


class TestHelperFunctions:
    """Test helper functions."""

    def test_read_content_from_request(self):
        """Test reading content from a request."""
        request = httpx.Request("GET", "https://example.com", content=b"test content")
        content = _read_content(request)
        assert content == b"test content"

    def test_read_content_from_response(self):
        """Test reading content from a response."""
        response = httpx.Response(200, content=b"response content")
        content = _read_content(response)
        assert content == b"response content"

    def test_extract_serializable_extensions(self):
        """Test extracting serializable values from extensions."""
        extensions = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "bytes": b"data",
            "list": [1, 2, 3],
            "dict": {"key": "value"},
            "none": None,
            "function": lambda x: x,  # Should be excluded
            "object": object(),  # Should be excluded
        }
        
        result = _extract_serializable_extensions(extensions)
        
        assert "string" in result
        assert "int" in result
        assert "float" in result
        assert "bool" in result
        assert "bytes" in result
        assert "list" in result
        assert "dict" in result
        assert "none" in result
        assert "function" not in result
        assert "object" not in result


class TestRequestSerialization:
    """Test request serialization and deserialization."""

    def test_simple_get_request(self):
        """Test serializing and deserializing a simple GET request."""
        original = httpx.Request("GET", "https://api.example.com/users")
        
        # Serialize
        serialized = serialize_request(original)
        assert isinstance(serialized, bytes)
        
        # Deserialize
        deserialized = deserialize_request(serialized)
        
        assert deserialized.method == original.method
        assert str(deserialized.url) == str(original.url)
        assert dict(deserialized.headers) == dict(original.headers)
        assert deserialized.content == original.content

    def test_post_request_with_json(self):
        """Test serializing POST request with JSON content."""
        original = httpx.Request(
            "POST",
            "https://api.example.com/users",
            json={"name": "Alice", "email": "alice@example.com"},
            headers={"Authorization": "Bearer token123"},
        )
        
        serialized = serialize_request(original)
        deserialized = deserialize_request(serialized)
        
        assert deserialized.method == "POST"
        assert str(deserialized.url) == "https://api.example.com/users"
        assert "Authorization" in deserialized.headers
        assert deserialized.headers["Authorization"] == "Bearer token123"
        # Check content contains the JSON data
        assert b"Alice" in deserialized.content
        assert b"alice@example.com" in deserialized.content

    def test_request_with_custom_headers(self):
        """Test request with multiple custom headers."""
        headers = {
            "X-API-Key": "secret-key",
            "X-Request-ID": "12345",
            "User-Agent": "TestClient/1.0",
            "Accept": "application/json",
        }
        original = httpx.Request("GET", "https://api.example.com/data", headers=headers)
        
        serialized = serialize_request(original)
        deserialized = deserialize_request(serialized)
        
        for key, value in headers.items():
            assert deserialized.headers[key] == value

    def test_request_with_query_params(self):
        """Test request with query parameters."""
        original = httpx.Request(
            "GET",
            "https://api.example.com/search",
            params={"q": "test query", "limit": 10, "offset": 20},
        )
        
        serialized = serialize_request(original)
        deserialized = deserialize_request(serialized)
        
        assert "q=test+query" in str(deserialized.url)
        assert "limit=10" in str(deserialized.url)
        assert "offset=20" in str(deserialized.url)

    def test_request_with_binary_content(self):
        """Test request with binary content."""
        binary_data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        original = httpx.Request(
            "PUT",
            "https://api.example.com/upload",
            content=binary_data,
            headers={"Content-Type": "application/octet-stream"},
        )
        
        serialized = serialize_request(original)
        deserialized = deserialize_request(serialized)
        
        assert deserialized.content == binary_data
        assert deserialized.headers["Content-Type"] == "application/octet-stream"

    def test_request_with_extensions(self):
        """Test request with extensions."""
        original = httpx.Request("GET", "https://api.example.com/test")
        original.extensions = {
            "timeout": 30,
            "retry_count": 3,
            "custom_flag": True,
        }
        
        serialized = serialize_request(original)
        deserialized = deserialize_request(serialized)
        
        assert deserialized.extensions["timeout"] == 30
        assert deserialized.extensions["retry_count"] == 3
        assert deserialized.extensions["custom_flag"] is True


class TestResponseSerialization:
    """Test response serialization and deserialization."""

    def test_simple_success_response(self):
        """Test serializing a simple successful response."""
        original = httpx.Response(
            200,
            content=b'{"status": "success"}',
            headers={"Content-Type": "application/json"},
        )
        
        serialized = serialize_response(original)
        assert isinstance(serialized, bytes)
        
        deserialized = deserialize_response(serialized)
        
        assert deserialized.status_code == 200
        assert deserialized.content == b'{"status": "success"}'
        assert deserialized.headers["Content-Type"] == "application/json"

    def test_error_response(self):
        """Test serializing error responses."""
        original = httpx.Response(
            404,
            content=b'{"error": "Not found"}',
            headers={"Content-Type": "application/json"},
        )
        
        serialized = serialize_response(original)
        deserialized = deserialize_response(serialized)
        
        assert deserialized.status_code == 404
        assert b"Not found" in deserialized.content

    def test_response_with_multiple_headers(self):
        """Test response with multiple headers."""
        headers = {
            "Content-Type": "text/html",
            "Cache-Control": "no-cache",
            "X-RateLimit-Remaining": "99",
            "X-RateLimit-Reset": "1234567890",
        }
        original = httpx.Response(200, content=b"<html>...</html>", headers=headers)
        
        serialized = serialize_response(original)
        deserialized = deserialize_response(serialized)
        
        for key, value in headers.items():
            assert deserialized.headers[key] == value

    def test_response_with_large_content(self):
        """Test response with large content."""
        large_content = b"x" * 10000  # 10KB of data
        original = httpx.Response(200, content=large_content)
        
        serialized = serialize_response(original)
        deserialized = deserialize_response(serialized)
        
        assert deserialized.content == large_content
        assert len(deserialized.content) == 10000

    def test_response_with_extensions(self):
        """Test response with extensions."""
        original = httpx.Response(200, content=b"OK")
        original.extensions = {
            "processing_time": 0.123,
            "server_id": "server-01",
            "cached": False,
        }
        
        serialized = serialize_response(original)
        deserialized = deserialize_response(serialized)
        
        assert deserialized.extensions["processing_time"] == 0.123
        assert deserialized.extensions["server_id"] == "server-01"
        assert deserialized.extensions["cached"] is False

    def test_redirect_response(self):
        """Test serializing redirect responses."""
        original = httpx.Response(
            302,
            headers={"Location": "https://example.com/new-location"},
        )
        
        serialized = serialize_response(original)
        deserialized = deserialize_response(serialized)
        
        assert deserialized.status_code == 302
        assert deserialized.headers["Location"] == "https://example.com/new-location"


class TestRoundTripSerialization:
    """Test round-trip serialization for various scenarios."""

    def test_empty_request_response(self):
        """Test empty request and response."""
        # Empty GET request
        req = httpx.Request("GET", "https://example.com")
        serialized_req = serialize_request(req)
        deserialized_req = deserialize_request(serialized_req)
        assert deserialized_req.method == "GET"
        assert str(deserialized_req.url) == "https://example.com"
        
        # Empty response
        resp = httpx.Response(204)  # No Content
        serialized_resp = serialize_response(resp)
        deserialized_resp = deserialize_response(serialized_resp)
        assert deserialized_resp.status_code == 204
        assert deserialized_resp.content == b""

    def test_special_characters_in_content(self):
        """Test content with special characters."""
        content = "Special chars: é à ñ 中文 🚀 emoji".encode("utf-8")
        
        req = httpx.Request("POST", "https://example.com", content=content)
        serialized_req = serialize_request(req)
        deserialized_req = deserialize_request(serialized_req)
        assert deserialized_req.content == content
        
        resp = httpx.Response(200, content=content)
        serialized_resp = serialize_response(resp)
        deserialized_resp = deserialize_response(serialized_resp)
        assert deserialized_resp.content == content

    def test_all_http_methods(self):
        """Test serialization with all common HTTP methods."""
        methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
        
        for method in methods:
            req = httpx.Request(method, "https://example.com/test")
            serialized = serialize_request(req)
            deserialized = deserialize_request(serialized)
            assert deserialized.method == method

    def test_all_status_codes(self):
        """Test serialization with various status codes."""
        status_codes = [200, 201, 204, 301, 302, 400, 401, 403, 404, 500, 502, 503]
        
        for code in status_codes:
            resp = httpx.Response(code)
            serialized = serialize_response(resp)
            deserialized = deserialize_response(serialized)
            assert deserialized.status_code == code


def test_invalid_data_handling():
    """Test handling of invalid data."""
    # Test deserializing invalid data
    with pytest.raises(Exception):  # ormsgpack will raise an exception
        deserialize_request(b"invalid data")
    
    with pytest.raises(Exception):
        deserialize_response(b"invalid data")
    
    # Test deserializing empty data
    with pytest.raises(Exception):
        deserialize_request(b"")
    
    with pytest.raises(Exception):
        deserialize_response(b"")