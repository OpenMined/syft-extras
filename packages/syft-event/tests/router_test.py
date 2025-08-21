"""Test the router module for syft-event package."""

from syft_core.url import SyftBoxURL
from syft_event.router import EventRouter
from syft_event.types import Request, Response


class TestEventRouter:
    """Test EventRouter class."""

    def test_router_initialization(self):
        """Test router initializes with empty routes."""
        router = EventRouter()
        assert router.routes == {}
        assert isinstance(router.routes, dict)

    def test_register_single_route(self):
        """Test registering a single route."""
        router = EventRouter()

        @router.on_request("/api/hello")
        def hello_handler(request: Request) -> Response:
            return Response(body={"message": "Hello, World!"})

        assert "/api/hello" in router.routes
        assert router.routes["/api/hello"] == hello_handler
        assert len(router.routes) == 1

    def test_register_multiple_routes(self):
        """Test registering multiple routes."""
        router = EventRouter()

        @router.on_request("/api/users")
        def users_handler(request: Request) -> Response:
            return Response(body={"users": []})

        @router.on_request("/api/posts")
        def posts_handler(request: Request) -> Response:
            return Response(body={"posts": []})

        @router.on_request("/api/comments")
        def comments_handler(request: Request) -> Response:
            return Response(body={"comments": []})

        assert len(router.routes) == 3
        assert "/api/users" in router.routes
        assert "/api/posts" in router.routes
        assert "/api/comments" in router.routes

    def test_route_handler_execution(self):
        """Test executing registered route handlers."""
        router = EventRouter()

        @router.on_request("/api/echo")
        def echo_handler(request: Request) -> Response:
            body = request.body.decode() if request.body else ""
            return Response(body={"echoed": body, "sender": request.sender})

        # Create a test request
        test_request = Request(
            id="test-echo",
            sender="alice@example.com",
            url=SyftBoxURL("syft://alice@example.com/app_data/echo_app/rpc/echo"),
            method="POST",
            body=b"Hello, Echo!",
        )

        # Execute the handler
        handler = router.routes["/api/echo"]
        response = handler(test_request)

        assert response.body["echoed"] == "Hello, Echo!"
        assert response.body["sender"] == "alice@example.com"

    def test_route_overwrite(self):
        """Test that registering the same route overwrites the previous handler."""
        router = EventRouter()

        @router.on_request("/api/data")
        def first_handler(request: Request) -> Response:
            return Response(body={"version": 1})

        @router.on_request("/api/data")
        def second_handler(request: Request) -> Response:
            return Response(body={"version": 2})

        assert len(router.routes) == 1
        handler = router.routes["/api/data"]

        # Create a dummy request
        test_request = Request(
            id="test",
            sender="test@example.com",
            url=SyftBoxURL("syft://test@example.com/app_data/data_app/rpc/data"),
            method="GET",
            body=None,
        )

        response = handler(test_request)
        assert response.body["version"] == 2

    def test_complex_route_patterns(self):
        """Test various route patterns."""
        router = EventRouter()

        routes = [
            "/",
            "/api",
            "/api/v1/users",
            "/api/v1/users/{id}",
            "/api/v2/posts/{id}/comments",
            "/webhooks/github",
            "/static/assets/main.css",
        ]

        for route in routes:

            @router.on_request(route)
            def handler(request: Request) -> Response:
                return Response(body={"route": route})

        assert len(router.routes) == len(routes)
        for route in routes:
            assert route in router.routes

    def test_handler_with_different_response_types(self):
        """Test handlers returning different response types."""
        router = EventRouter()

        @router.on_request("/api/json")
        def json_handler(request: Request) -> Response:
            return Response(
                body={"type": "json", "data": [1, 2, 3]},
                headers={"Content-Type": "application/json"},
            )

        @router.on_request("/api/text")
        def text_handler(request: Request) -> Response:
            return Response(
                body="Plain text response",
                headers={"Content-Type": "text/plain"},
            )

        @router.on_request("/api/error")
        def error_handler(request: Request) -> Response:
            return Response(
                body={"error": "Something went wrong"},
                status_code=500,
            )

        # Test each handler
        dummy_request = Request(
            id="test",
            sender="test@example.com",
            url=SyftBoxURL("syft://test@example.com/app_data/test_app/rpc/test"),
            method="GET",
            body=None,
        )

        json_response = router.routes["/api/json"](dummy_request)
        assert json_response.body["type"] == "json"
        assert json_response.headers["Content-Type"] == "application/json"

        text_response = router.routes["/api/text"](dummy_request)
        assert text_response.body == "Plain text response"
        assert text_response.headers["Content-Type"] == "text/plain"

        error_response = router.routes["/api/error"](dummy_request)
        assert error_response.status_code == 500
        assert "error" in error_response.body

    def test_handler_with_request_processing(self):
        """Test handlers that process request data."""
        router = EventRouter()

        @router.on_request("/api/calculate")
        def calculate_handler(request: Request) -> Response:
            import json

            if request.body:
                data = json.loads(request.body.decode())
                a = data.get("a", 0)
                b = data.get("b", 0)
                operation = data.get("operation", "add")

                if operation == "add":
                    result = a + b
                elif operation == "subtract":
                    result = a - b
                elif operation == "multiply":
                    result = a * b
                elif operation == "divide":
                    result = a / b if b != 0 else "Error: Division by zero"
                else:
                    result = "Error: Unknown operation"

                return Response(body={"result": result})

            return Response(
                body={"error": "No data provided"},
                status_code=400,
            )

        # Test calculation
        calc_request = Request(
            id="calc-test",
            sender="math@example.com",
            url=SyftBoxURL("syft://math@example.com/app_data/calc_app/rpc/calculate"),
            method="POST",
            body=b'{"a": 10, "b": 5, "operation": "multiply"}',
        )

        handler = router.routes["/api/calculate"]
        response = handler(calc_request)
        assert response.body["result"] == 50


def test_multiple_routers():
    """Test using multiple router instances."""
    # API v1 router
    v1_router = EventRouter()

    @v1_router.on_request("/users")
    def v1_users(request: Request) -> Response:
        return Response(body={"version": "v1", "users": ["alice", "bob"]})

    # API v2 router
    v2_router = EventRouter()

    @v2_router.on_request("/users")
    def v2_users(request: Request) -> Response:
        return Response(
            body={
                "version": "v2",
                "users": [
                    {"id": 1, "name": "alice"},
                    {"id": 2, "name": "bob"},
                ],
            }
        )

    # Both routers have the same endpoint but different handlers
    assert "/users" in v1_router.routes
    assert "/users" in v2_router.routes

    # Execute handlers from both routers
    dummy_request = Request(
        id="test",
        sender="test@example.com",
        url=SyftBoxURL("syft://test@example.com/app_data/users_app/rpc/users"),
        method="GET",
        body=None,
    )

    v1_response = v1_router.routes["/users"](dummy_request)
    v2_response = v2_router.routes["/users"](dummy_request)

    assert v1_response.body["version"] == "v1"
    assert v2_response.body["version"] == "v2"
    assert isinstance(v1_response.body["users"], list)
    assert isinstance(v2_response.body["users"][0], dict)
