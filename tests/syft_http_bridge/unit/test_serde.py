import httpx
import pytest
from syft_http_bridge.serde import (
    deserialize_request,
    deserialize_response,
    serialize_request,
    serialize_response,
)


@pytest.mark.parametrize(
    "request_obj",
    [
        # Simple GET request
        httpx.Request(
            "GET",
            "https://api.example.com/users",
            headers={"Accept": "application/json"},
        ),
        # GET with query parameters
        httpx.Request(
            "GET",
            "https://api.example.com/search?q=python&limit=10",
            headers={"Accept": "application/json"},
        ),
        # POST with JSON body
        httpx.Request(
            "POST",
            "https://api.example.com/users",
            json={
                "name": "alice",
                "nested": {"key": "value"},
            },
        ),
        # PUT with binary content
        httpx.Request(
            "PUT",
            "https://api.example.com/files/123",
            headers={"Content-Type": "application/octet-stream"},
            content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        ),
        # POST with form data
        httpx.Request(
            "POST",
            "https://api.example.com/login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=b"username=admin&password=secure123",
        ),
        # POST with multipart form data
        httpx.Request(
            "POST",
            "https://api.example.com/upload",
            headers={"Authorization": "[secure]"},
            content=b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="test.jpg"\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xe0\x00\x10JFIF\r\n--boundary--\r\n',
        ),
        # POST with single file upload
        httpx.Request(
            "POST",
            "https://api.example.com/upload",
            files={
                "profile_pic": (
                    "photo.jpg",
                    b"\xff\xd8\xff\xe0\x00\x10JFIF",
                    "image/jpeg",
                ),
            },
            data={"name": "John Doe"},
        ),
        # POST with multiple file uploads
        httpx.Request(
            "POST",
            "https://api.example.com/upload",
            files={
                "profile_pic": (
                    "photo.jpg",
                    b"\xff\xd8\xff\xe0\x00\x10JFIF",
                    "image/jpeg",
                ),
                "resume": ("cv.pdf", b"%PDF-1.5\r\n", "application/pdf"),
            },
            data={"name": "John Doe"},
        ),
    ],
    ids=[
        "get",
        "get-with-params",
        "json-post",
        "binary-put",
        "form-post",
        "multipart-post",
        "single-file-upload",
        "multiple-file-upload",
    ],
)
def test_request_serialization(request_obj):
    """Test that HTTP requests can be serialized and deserialized correctly."""
    serialized = serialize_request(request_obj)
    deserialized = deserialize_request(serialized)

    assert request_obj.method == deserialized.method
    assert str(request_obj.url) == str(deserialized.url)
    assert dict(request_obj.headers.items()) == dict(deserialized.headers.items())
    assert request_obj.content == deserialized.content


@pytest.mark.parametrize(
    "response_obj",
    [
        # Simple text response
        httpx.Response(status_code=200, text="OK"),
        # JSON response
        httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json={"status": "success"},
        ),
        # Error response with headers
        httpx.Response(
            status_code=404,
            headers={
                "Content-Type": "application/json",
                "X-Error-Code": "NOT_FOUND",
            },
            json={"error": "Resource not found"},
        ),
        # JSON with raw content
        httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=b'{"status": "success", "data": {"id": 123}}',
        ),
        # HTML response
        httpx.Response(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<!DOCTYPE html><html><body><h1>Hello World</h1></body></html>",
        ),
        # Binary response
        httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/octet-stream"},
            content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00",
        ),
        # Redirect response
        httpx.Response(
            status_code=302,
            headers={
                "Location": "https://api.example.com/new-location",
                "Cache-Control": "no-cache",
            },
            content=b"",
        ),
    ],
    ids=[
        "simple",
        "json",
        "error",
        "json-content",
        "html",
        "binary",
        "redirect",
    ],
)
def test_response_serialization(response_obj):
    """Test that HTTP responses can be serialized and deserialized correctly."""
    serialized = serialize_response(response_obj)
    deserialized = deserialize_response(serialized)

    assert response_obj.status_code == deserialized.status_code
    assert dict(response_obj.headers.items()) == dict(deserialized.headers.items())
    assert response_obj.content == deserialized.content
