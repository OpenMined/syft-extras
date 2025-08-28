"""Test the schema module for syft-event package."""

from typing import List, Optional

from pydantic import BaseModel
from syft_event.schema import generate_schema, get_type_schema
from syft_event.types import Request, Response


class UserModel(BaseModel):
    """Test user model."""

    id: int
    name: str
    email: Optional[str] = None
    tags: List[str] = []


class TestGetTypeSchema:
    """Test get_type_schema function."""

    def test_basic_types(self):
        """Test schema for basic Python types."""
        assert get_type_schema(str) == "str"
        assert get_type_schema(int) == "int"
        assert get_type_schema(float) == "float"
        assert get_type_schema(bool) == "bool"
        assert get_type_schema(None) == "null"

    def test_list_types(self):
        """Test schema for List types."""
        schema = get_type_schema(List[str])
        assert schema["type"] == "array"
        assert schema["items"] == "str"

        schema = get_type_schema(List[int])
        assert schema["type"] == "array"
        assert schema["items"] == "int"

    def test_optional_types(self):
        """Test schema for Optional types."""
        assert get_type_schema(Optional[str]) == "str"
        assert get_type_schema(Optional[int]) == "int"

        # Optional list
        schema = get_type_schema(Optional[List[str]])
        assert schema["type"] == "array"
        assert schema["items"] == "str"

    def test_pydantic_model(self):
        """Test schema for Pydantic models."""
        schema = get_type_schema(UserModel)
        assert schema["type"] == "model"
        assert schema["name"] == "UserModel"
        assert "schema" in schema

        # Check the Pydantic schema has expected fields
        model_schema = schema["schema"]
        assert "properties" in model_schema
        assert "id" in model_schema["properties"]
        assert "name" in model_schema["properties"]
        assert "email" in model_schema["properties"]
        assert "tags" in model_schema["properties"]

    def test_nested_types(self):
        """Test schema for nested types."""
        schema = get_type_schema(List[UserModel])
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "model"
        assert schema["items"]["name"] == "UserModel"

    def test_any_type(self):
        """Test schema for Any type."""
        from typing import Any

        assert get_type_schema(Any) == "any"


class TestGenerateSchema:
    """Test generate_schema function."""

    def test_simple_function(self):
        """Test schema generation for simple function."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        schema = generate_schema(add)

        assert schema["description"] == "Add two numbers."
        assert "args" in schema
        assert "a" in schema["args"]
        assert "b" in schema["args"]
        assert schema["args"]["a"]["type"] == "int"
        assert schema["args"]["a"]["required"] is True
        assert schema["args"]["b"]["type"] == "int"
        assert schema["args"]["b"]["required"] is True
        assert schema["returns"] == "int"

    def test_function_with_defaults(self):
        """Test schema generation for function with default values."""

        def greet(name: str, greeting: str = "Hello") -> str:
            """Greet a person."""
            return f"{greeting}, {name}!"

        schema = generate_schema(greet)

        assert schema["description"] == "Greet a person."
        assert schema["args"]["name"]["required"] is True
        assert schema["args"]["greeting"]["required"] is False
        assert schema["args"]["greeting"]["type"] == "str"

    def test_function_with_optional(self):
        """Test schema generation for function with Optional parameters."""

        def create_user(name: str, email: Optional[str] = None) -> UserModel:
            """Create a new user."""
            return UserModel(id=1, name=name, email=email)

        schema = generate_schema(create_user)

        assert schema["description"] == "Create a new user."
        assert schema["args"]["name"]["type"] == "str"
        assert schema["args"]["email"]["type"] == "str"
        assert schema["args"]["email"]["required"] is False
        assert schema["returns"]["type"] == "model"
        assert schema["returns"]["name"] == "UserModel"

    def test_function_with_request_param(self):
        """Test schema generation for function with Request parameter."""

        def handle_request(request: Request, action: str) -> Response:
            """Handle an incoming request."""
            return Response(body={"action": action})

        schema = generate_schema(handle_request)

        # Request parameter should be filtered out
        assert "request" not in schema["args"]
        assert "action" in schema["args"]
        assert schema["args"]["action"]["type"] == "str"
        # Response return type should become Any
        assert schema["returns"] == "any"

    def test_function_with_list_params(self):
        """Test schema generation for function with List parameters."""

        def process_items(items: List[str], count: int) -> List[UserModel]:
            """Process a list of items."""
            return []

        schema = generate_schema(process_items)

        assert schema["args"]["items"]["type"]["type"] == "array"
        assert schema["args"]["items"]["type"]["items"] == "str"
        assert schema["args"]["count"]["type"] == "int"
        assert schema["returns"]["type"] == "array"
        assert schema["returns"]["items"]["type"] == "model"

    def test_function_with_no_annotations(self):
        """Test schema generation for function without type annotations."""

        def mystery_function(x, y):
            """A mysterious function."""
            return x + y

        schema = generate_schema(mystery_function)

        assert schema["description"] == "A mysterious function."
        assert schema["args"]["x"]["type"] == "any"
        assert schema["args"]["y"]["type"] == "any"
        assert schema["returns"] == "any"

    def test_function_with_complex_types(self):
        """Test schema generation for function with complex types."""

        def complex_function(
            users: List[UserModel],
            tags: Optional[List[str]] = None,
            metadata: dict = {},
        ) -> dict:
            """Process complex data structures."""
            return {"processed": True}

        schema = generate_schema(complex_function)

        assert schema["description"] == "Process complex data structures."
        assert schema["args"]["users"]["type"]["type"] == "array"
        assert schema["args"]["users"]["type"]["items"]["type"] == "model"
        assert schema["args"]["users"]["required"] is True
        assert schema["args"]["tags"]["type"]["type"] == "array"
        assert schema["args"]["tags"]["required"] is False
        assert schema["args"]["metadata"]["type"] == "dict"
        assert schema["args"]["metadata"]["required"] is False

    def test_function_without_docstring(self):
        """Test schema generation for function without docstring."""

        def no_docs(value: int) -> int:
            return value * 2

        schema = generate_schema(no_docs)

        assert schema["description"] is None
        assert schema["args"]["value"]["type"] == "int"
        assert schema["returns"] == "int"


def test_integration_with_event_handlers():
    """Test schema generation with typical event handler functions."""

    def get_users(request: Request, limit: int = 10, offset: int = 0) -> Response:
        """Retrieve a list of users with pagination."""
        return Response(body={"users": [], "limit": limit, "offset": offset})

    def create_user(request: Request, user: UserModel) -> Response:
        """Create a new user in the system."""
        return Response(body={"created": user.model_dump()}, status_code=201)

    def update_user(request: Request, user_id: int, updates: dict) -> Response:
        """Update an existing user."""
        return Response(body={"updated": True})

    # Generate schemas
    get_users_schema = generate_schema(get_users)
    create_user_schema = generate_schema(create_user)
    update_user_schema = generate_schema(update_user)

    # Verify get_users schema
    assert "request" not in get_users_schema["args"]
    assert get_users_schema["args"]["limit"]["type"] == "int"
    assert get_users_schema["args"]["limit"]["required"] is False
    assert get_users_schema["args"]["offset"]["type"] == "int"
    assert get_users_schema["args"]["offset"]["required"] is False

    # Verify create_user schema
    assert "request" not in create_user_schema["args"]
    assert create_user_schema["args"]["user"]["type"]["type"] == "model"
    assert create_user_schema["args"]["user"]["type"]["name"] == "UserModel"
    assert create_user_schema["args"]["user"]["required"] is True

    # Verify update_user schema
    assert "request" not in update_user_schema["args"]
    assert update_user_schema["args"]["user_id"]["type"] == "int"
    assert update_user_schema["args"]["updates"]["type"] == "dict"
