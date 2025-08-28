"""Test the types module for syft-event package."""

import pytest
from syft_core.url import SyftBoxURL
from syft_event.types import Request, Response


class TestRequest:
    """Test Request model."""

    def test_request_creation(self):
        """Test creating a Request with required fields."""
        req = Request(
            id="test-123",
            sender="alice@example.com",
            url=SyftBoxURL("syft://alice@example.com/app_data/my_app/rpc/test"),
            method="GET",
            body=None,
        )
        assert req.id == "test-123"
        assert req.sender == "alice@example.com"
        assert str(req.url) == "syft://alice@example.com/app_data/my_app/rpc/test"
        assert req.method == "GET"
        assert req.body is None
        assert req.headers == {}

    def test_request_with_headers_and_body(self):
        """Test creating a Request with headers and body."""
        headers = {"Content-Type": "application/json", "Authorization": "Bearer token"}
        body = b'{"message": "hello"}'

        req = Request(
            id="test-456",
            sender="bob@example.com",
            url=SyftBoxURL("syft://bob@example.com/app_data/data_app/rpc/data"),
            method="POST",
            headers=headers,
            body=body,
        )

        assert req.headers == headers
        assert req.body == body
        assert req.method == "POST"

    def test_request_url_types(self):
        """Test Request accepts various URL types."""
        # Test with string URL
        req1 = Request(
            id="test-789",
            sender="carol@example.com",
            url=SyftBoxURL("syft://carol@example.com/app_data/api_app/rpc/endpoint"),
            method="PUT",
            body=None,
        )
        assert str(req1.url) == "syft://carol@example.com/app_data/api_app/rpc/endpoint"

    def test_request_validation_errors(self):
        """Test Request validation errors."""
        # Missing required fields
        with pytest.raises(ValueError):
            Request(
                id="test",
                sender="user@example.com",
                # missing url
                method="GET",
                body=None,
            )


class TestResponse:
    """Test Response model."""

    def test_response_defaults(self):
        """Test Response with default values."""
        resp = Response()
        assert resp.body is None
        assert resp.status_code == 200
        assert resp.headers is None

    def test_response_with_body(self):
        """Test Response with body."""
        resp = Response(body={"result": "success", "data": [1, 2, 3]})
        assert resp.body == {"result": "success", "data": [1, 2, 3]}
        assert resp.status_code == 200

    def test_response_with_all_fields(self):
        """Test Response with all fields."""
        headers = {"Content-Type": "application/json", "X-Custom": "value"}
        body = {"message": "Created successfully"}

        resp = Response(
            body=body,
            status_code=201,
            headers=headers,
        )

        assert resp.body == body
        assert resp.status_code == 201
        assert resp.headers == headers

    def test_response_error_codes(self):
        """Test Response with various status codes."""
        # 400 Bad Request
        resp1 = Response(
            body={"error": "Invalid input"},
            status_code=400,
        )
        assert resp1.status_code == 400

        # 404 Not Found
        resp2 = Response(
            body={"error": "Resource not found"},
            status_code=404,
        )
        assert resp2.status_code == 404

        # 500 Internal Server Error
        resp3 = Response(
            body={"error": "Internal server error"},
            status_code=500,
        )
        assert resp3.status_code == 500

    def test_response_with_different_body_types(self):
        """Test Response with different body types."""
        # String body
        resp1 = Response(body="Plain text response")
        assert resp1.body == "Plain text response"

        # List body
        resp2 = Response(body=[1, 2, 3, 4, 5])
        assert resp2.body == [1, 2, 3, 4, 5]

        # None body
        resp3 = Response(body=None)
        assert resp3.body is None

        # Complex nested structure
        complex_body = {
            "users": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            "meta": {
                "total": 2,
                "page": 1,
            },
        }
        resp4 = Response(body=complex_body)
        assert resp4.body == complex_body


def test_request_response_integration():
    """Test Request and Response used together."""
    # Simulate a request-response cycle
    request = Request(
        id="integration-test",
        sender="test@example.com",
        url=SyftBoxURL("syft://test@example.com/app_data/echo_app/rpc/echo"),
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b'{"echo": "Hello, World!"}',
    )

    # Process request and create response
    response = Response(
        body={"echoed": "Hello, World!", "request_id": request.id},
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    assert response.body["request_id"] == request.id
    assert response.headers["Content-Type"] == request.headers["Content-Type"]
