# Syft-Event Package Documentation

## Overview

The `syft-event` package provides an event-driven RPC (Remote Procedure Call) system for SyftBox applications. It enables applications to communicate with each other through a request-response pattern using SyftBox URLs and a simple routing mechanism. The package includes automatic cleanup utilities for managing old request/response files and user-specific directory organization for better request management.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         syft-event                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Request    │    │   Response   │    │   EventRouter    │ │
│  │              │    │              │    │                  │ │
│  │ - ID         │    │ - Body       │    │ - Routes map     │ │
│  │ - Sender     │    │ - Status     │    │ - on_request()   │ │
│  │ - URL        │    │ - Headers    │    │ - Handler funcs  │ │
│  │ - Headers    │    │              │    │                  │ │
│  │ - Body       │    │              │    │                  │ │
│  │ - Method     │    │              │    │                  │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Schema     │    │  SyftEvents  │    │   Handlers       │ │
│  │              │    │              │    │                  │ │
│  │ - Type info  │    │ - Server     │    │ - File watch     │ │
│  │ - Generate   │    │ - Process    │    │ - Process req    │ │
│  │ - Validate   │    │ - Lifecycle  │    │ - Send response  │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Cleanup    │    │   File       │    │   Migration      │ │
│  │              │    │   System     │    │                  │ │
│  │ - Periodic   │    │ - User dirs  │    │ - Legacy files   │ │
│  │ - Statistics │    │ - Organized  │    │ - Auto migrate   │ │
│  │ - Config     │    │ - Structure  │    │ - Backward comp  │ │
│  └──────────────┘    └──────────────┘    └──────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Request-Response Flow

```
┌─────────────┐                                      ┌─────────────┐
│   Client    │                                      │   Server    │
│    App A    │                                      │    App B    │
└──────┬──────┘                                      └──────┬──────┘
       │                                                     │
       │  1. Create Request                                  │
       │     syft://bob@example.com/                        │
       │     app_data/app_b/rpc/endpoint                    │
       │                                                     │
       │  2. Send Request ───────────────────────────────►  │
       │     (Write to filesystem)                          │
       │                                                     │
       │                                             3. EventRouter
       │                                                matches
       │                                              /endpoint
       │                                                     │
       │                                             4. Handler
       │                                               processes
       │                                                request
       │                                                     │
       │  ◄─────────────────────────────────── 5. Send Response
       │                                         (Write to filesystem)
       │                                                     │
       │  6. Process Response                                │
       │                                                     │
       ▼                                                     ▼
```

## Core Components

### 1. Request and Response Types

**Request** - Represents an incoming RPC request:
```python
from syft_event.types import Request
from syft_core.url import SyftBoxURL

request = Request(
    id="unique-request-id",
    sender="alice@example.com",
    url=SyftBoxURL("syft://bob@example.com/app_data/my_app/rpc/users"),
    method="POST",
    headers={"Content-Type": "application/json"},
    body=b'{"action": "list_users"}'
)
```

**Response** - Represents the response to a request:
```python
from syft_event.types import Response

response = Response(
    body={"users": ["alice", "bob", "charlie"]},
    status_code=200,
    headers={"Content-Type": "application/json"}
)

# Error response
error_response = Response(
    body={"error": "User not found"},
    status_code=404
)
```

### 2. EventRouter

The EventRouter provides a simple way to register and organize RPC endpoints:

```python
from syft_event import EventRouter, Request, Response

# Create a router
router = EventRouter()

# Register handlers for different endpoints
@router.on_request("/users")
def handle_users(request: Request) -> Response:
    # Process the request
    return Response(body={"users": ["alice", "bob"]})

@router.on_request("/data/{id}")
def handle_data(request: Request) -> Response:
    # Extract ID from URL path
    data_id = request.url.path.split("/")[-1]
    return Response(body={"data_id": data_id, "value": 42})

@router.on_request("/echo")
def echo_handler(request: Request) -> Response:
    # Echo back the request body
    return Response(body=request.body)
```

### 3. Schema Generation

The schema module can introspect your handlers to generate API documentation:

```python
from syft_event.schema import generate_schema
from typing import List, Optional
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: Optional[str] = None

def get_users(request: Request, limit: int = 10) -> Response:
    """Retrieve a list of users."""
    # Implementation
    return Response(body={"users": []})

# Generate schema
schema = generate_schema(get_users)
print(schema)
# Output:
# {
#     "description": "Retrieve a list of users.",
#     "args": {
#         "limit": {"type": "int", "required": False}
#     },
#     "returns": "any"
# }
```

### 4. Cleanup System

The cleanup system provides automatic management of old request and response files:

```python
from syft_event.cleanup import PeriodicCleanup, CleanupStats

# Create cleanup instance
cleanup = PeriodicCleanup(
    app_name="my_app",
    cleanup_interval="1d",    # Run cleanup daily
    cleanup_expiry="7d"       # Keep files for 7 days
)

# Start automatic cleanup
cleanup.start()

# Get statistics
stats = cleanup.get_stats()
print(f"Deleted {stats.requests_deleted} requests")

# Stop cleanup
cleanup.stop()
```

**Key Features:**
- **Automatic cleanup** of old request/response files
- **Configurable retention** periods and cleanup intervals
- **Statistics tracking** for monitoring cleanup operations
- **Background operation** with graceful shutdown
- **Error handling** and logging for robust operation

## Usage Patterns

### Basic Event Handler Application

```python
from syft_event import SyftEvents, EventRouter, Request, Response
from syft_core import Client

# Initialize
client = Client.load()
router = EventRouter()

# Define handlers
@router.on_request("/calculate")
def calculate(request: Request) -> Response:
    import json
    
    if request.body:
        data = json.loads(request.body.decode())
        result = data["a"] + data["b"]
        return Response(body={"result": result})
    
    return Response(
        body={"error": "No data provided"},
        status_code=400
    )

# Create and run the event server
app = SyftEvents(
    app_name="calculator",
    client=client,
    router=router
)

# Start processing events
app.run()
```

### Advanced Routing Patterns

```python
router = EventRouter()

# Different HTTP methods
@router.on_request("/items")
def list_items(request: Request) -> Response:
    if request.method == "GET":
        return Response(body={"items": []})
    elif request.method == "POST":
        # Create new item
        return Response(body={"created": True}, status_code=201)
    else:
        return Response(
            body={"error": "Method not allowed"},
            status_code=405
        )

# Pattern matching
@router.on_request("/users/{email}/profile")
def user_profile(request: Request) -> Response:
    # Extract email from path
    parts = request.url.path.split("/")
    email = parts[2]  # Assuming /users/{email}/profile
    
    return Response(body={
        "email": email,
        "profile": {"name": "User Name"}
    })

# Wildcard patterns
@router.on_request("/api/**")
def api_handler(request: Request) -> Response:
    # Handle all /api/* requests
    return Response(body={"api": "v1"})
```

### Request Processing

```python
@router.on_request("/process")
def process_handler(request: Request) -> Response:
    # Access request properties
    sender = request.sender
    request_id = request.id
    
    # Parse headers
    content_type = request.headers.get("Content-Type", "")
    auth_token = request.headers.get("Authorization", "")
    
    # Process body based on content type
    if content_type == "application/json":
        import json
        data = json.loads(request.body.decode())
    elif content_type == "application/x-www-form-urlencoded":
        from urllib.parse import parse_qs
        data = parse_qs(request.body.decode())
    else:
        data = request.body
    
    # Return appropriate response
    return Response(
        body={
            "processed": True,
            "request_id": request_id,
            "sender": sender
        },
        headers={"X-Request-ID": request_id}
    )
```

### Error Handling

```python
@router.on_request("/protected")
def protected_handler(request: Request) -> Response:
    # Check authorization
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header.startswith("Bearer "):
        return Response(
            body={"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        # Process protected resource
        token = auth_header.split(" ")[1]
        # Validate token...
        
        return Response(body={"data": "secret"})
        
    except ValueError as e:
        return Response(
            body={"error": str(e)},
            status_code=400
        )
    except Exception as e:
        # Log error
        return Response(
            body={"error": "Internal server error"},
            status_code=500
        )
```

## SyftBox URL Structure

Understanding the URL structure is crucial for event routing:

```
syft://alice@example.com/app_data/my_app/rpc/endpoint
  │     │                │         │       │    │
  │     │                │         │       │    └─► Endpoint path
  │     │                │         │       └──────► RPC indicator
  │     │                │         └──────────────► App name
  │     │                └────────────────────────► App data folder
  │     └─────────────────────────────────────────► User email
  └───────────────────────────────────────────────► Protocol
```

### URL Examples

```python
# Basic RPC endpoint
url1 = SyftBoxURL("syft://bob@example.com/app_data/chat/rpc/messages")

# Nested endpoint
url2 = SyftBoxURL("syft://alice@example.com/app_data/api/rpc/v1/users")

# With path parameters
url3 = SyftBoxURL("syft://carol@example.com/app_data/store/rpc/products/123")
```

## Integration with SyftBox

### File-based Communication

Events in SyftBox are communicated through the filesystem with user-specific organization:

```
datasites/
└── bob@example.com/
    └── app_data/
        └── my_app/
            └── rpc/
                ├── syft.pub.yaml          # Permission configuration
                ├── rpc.schema.json        # Generated API schema
                └── {endpoint}/            # Endpoint directories
                    ├── .syftkeep         # Directory marker
                    └── {sender-email}/    # User-specific subdirectories
                        ├── request_123.request    # Incoming request
                        ├── request_456.request    # Another request
                        ├── request_123.response   # Outgoing response
                        └── request_456.response   # Another response
```

#### Directory Organization Benefits

- **User Isolation**: Requests are organized by sender email address
- **Better Organization**: Clear separation of requests from different users
- **Automatic Cleanup**: Old files are automatically cleaned up based on configurable retention
- **Legacy Support**: Automatic migration of old request files to new structure

### Watching for Events

The SyftEvents server uses file system watchers to detect new requests with enhanced event handling:

```python
from syft_event import SyftEvents

# The server automatically:
# 1. Watches for new request files using both FileCreatedEvent and FileMovedEvent
# 2. Parses the request
# 3. Routes to appropriate handler
# 4. Writes response to responses directory
# 5. Prevents duplicate processing of the same request

app = SyftEvents(
    app_name="my_service",
    client=client,
    router=router,
    poll_interval=1.0  # Check for new requests every second
)
```

#### Request File Delivery Mechanisms

The system monitors both `FileCreatedEvent` and `FileMovedEvent` for RPC endpoints because request files can arrive through two different delivery mechanisms:

- **WebSocket Delivery**: Files delivered through websockets are initially stored as temporary files and then renamed to the target request file location (triggering a `FileMovedEvent`)
- **Blob Store Download**: Files downloaded directly from the blob store are created directly as request files (triggering a `FileCreatedEvent`)

This dual-event monitoring ensures reliable request detection regardless of the delivery mechanism used.

### Automatic Cleanup System

The SyftEvents server includes an automatic cleanup system to manage old request and response files:

#### Basic Cleanup Configuration

```python
from syft_event import SyftEvents

# Create with custom cleanup settings
app = SyftEvents(
    app_name="my_service",
    cleanup_expiry="7d",    # Keep files for 7 days (default: 30d)
    cleanup_interval="1h"   # Run cleanup every hour (default: 1d)
)

# Check if cleanup is running
if app.is_cleanup_running():
    print("Cleanup service is active")

# Get cleanup statistics
stats = app.get_cleanup_stats()
print(f"Deleted {stats.requests_deleted} requests and {stats.responses_deleted} responses")
```

#### Standalone Cleanup Utility

For more control, you can use the cleanup utility independently:

```python
from syft_event.cleanup import PeriodicCleanup, CleanupStats

# Create a standalone cleanup instance
cleanup = PeriodicCleanup(
    app_name="my_service",
    cleanup_interval="1d",      # How often to run cleanup
    cleanup_expiry="30d",       # How long to keep files
    on_cleanup_complete=lambda stats: print(f"Cleaned up {stats.requests_deleted} files")
)

# Start cleanup in background
cleanup.start()

# Or run cleanup immediately
stats = cleanup.cleanup_now()
print(f"Immediate cleanup: {stats.requests_deleted} files deleted")

# Stop cleanup
cleanup.stop()
```

#### Time Interval Format

The cleanup utility supports human-readable time intervals:

```python
# Single units
"1d"    # 1 day
"2h"    # 2 hours  
"30m"   # 30 minutes
"45s"   # 45 seconds

# Combined units
"1d2h30m"     # 1 day, 2 hours, 30 minutes
"2h15m30s"    # 2 hours, 15 minutes, 30 seconds
"1d12h30m45s" # 1 day, 12 hours, 30 minutes, 45 seconds

# Case insensitive
"1D" == "1d"  # True
```

#### Cleanup Statistics

Track cleanup operations with detailed statistics:

```python
stats = cleanup.get_stats()

print(f"Requests deleted: {stats.requests_deleted}")
print(f"Responses deleted: {stats.responses_deleted}")
print(f"Errors encountered: {stats.errors}")
print(f"Last cleanup: {stats.last_cleanup}")

# Reset statistics
stats.reset()
```

## Best Practices

### 1. Endpoint Design

Follow RESTful conventions:
- `/users` - List all users (GET) or create user (POST)
- `/users/{id}` - Get, update, or delete specific user
- `/users/{id}/posts` - Get user's posts
- Use HTTP methods appropriately

### 2. Error Handling

Always return appropriate status codes:
```python
# Success codes
200 - OK
201 - Created
204 - No Content

# Client errors
400 - Bad Request
401 - Unauthorized
403 - Forbidden
404 - Not Found

# Server errors
500 - Internal Server Error
502 - Bad Gateway
503 - Service Unavailable
```

### 3. Request Validation

```python
@router.on_request("/api/create")
def create_handler(request: Request) -> Response:
    if not request.body:
        return Response(
            body={"error": "Request body required"},
            status_code=400
        )
    
    try:
        data = json.loads(request.body.decode())
    except json.JSONDecodeError:
        return Response(
            body={"error": "Invalid JSON"},
            status_code=400
        )
    
    # Validate required fields
    required = ["name", "email"]
    missing = [f for f in required if f not in data]
    
    if missing:
        return Response(
            body={"error": f"Missing fields: {missing}"},
            status_code=400
        )
    
    # Process valid request...
```

### 4. Cleanup Management

Configure cleanup settings based on your application needs:

```python
# For high-traffic applications
app = SyftEvents(
    app_name="high_traffic_app",
    cleanup_expiry="1d",     # Keep files for 1 day
    cleanup_interval="1h"    # Clean up every hour
)

# For low-traffic applications
app = SyftEvents(
    app_name="low_traffic_app", 
    cleanup_expiry="30d",    # Keep files for 30 days
    cleanup_interval="1d"    # Clean up daily
)

# For debugging/development
app = SyftEvents(
    app_name="debug_app",
    cleanup_expiry="7d",     # Keep files for 7 days
    cleanup_interval="1d"    # Clean up daily
)
```

Monitor cleanup operations:

```python
# Check cleanup status
if app.is_cleanup_running():
    stats = app.get_cleanup_stats()
    print(f"Cleanup active - Last run: {stats.last_cleanup}")
    print(f"Files deleted: {stats.requests_deleted + stats.responses_deleted}")
else:
    print("Cleanup service not running")
```

### 5. Async Patterns

For long-running operations:

```python
@router.on_request("/async/job")
def start_job(request: Request) -> Response:
    import uuid
    
    # Start async job
    job_id = str(uuid.uuid4())
    
    # Return immediately with job ID
    return Response(
        body={
            "job_id": job_id,
            "status": "pending",
            "check_url": f"/async/job/{job_id}"
        },
        status_code=202  # Accepted
    )

@router.on_request("/async/job/{id}")
def check_job(request: Request) -> Response:
    job_id = request.url.path.split("/")[-1]
    
    # Check job status
    status = get_job_status(job_id)  # Your implementation
    
    return Response(body={"job_id": job_id, "status": status})
```

## Testing

### Unit Testing Handlers

```python
import pytest
from syft_event import Request, Response
from syft_core.url import SyftBoxURL

def test_echo_handler():
    # Create test request
    request = Request(
        id="test-123",
        sender="test@example.com",
        url=SyftBoxURL("syft://test@example.com/app_data/test/rpc/echo"),
        method="POST",
        body=b"Hello, World!"
    )
    
    # Call handler
    response = echo_handler(request)
    
    # Assert response
    assert response.status_code == 200
    assert response.body == b"Hello, World!"

def test_error_handling():
    request = Request(
        id="test-456",
        sender="test@example.com",
        url=SyftBoxURL("syft://test@example.com/app_data/test/rpc/protected"),
        method="GET",
        headers={},  # No auth header
        body=None
    )
    
    response = protected_handler(request)
    
    assert response.status_code == 401
    assert "error" in response.body
```

### Integration Testing

```python
def test_router_integration():
    router = EventRouter()
    
    @router.on_request("/test")
    def test_handler(request: Request) -> Response:
        return Response(body={"test": True})
    
    # Verify route is registered
    assert "/test" in router.routes
    
    # Create request and process
    request = create_test_request("/test")
    handler = router.routes["/test"]
    response = handler(request)
    
    assert response.body["test"] is True
```

## Performance Considerations

1. **Keep handlers lightweight** - Long operations should be async
2. **Minimize file I/O** - Cache frequently accessed data
3. **Use efficient serialization** - JSON for compatibility, MessagePack for performance
4. **Implement request throttling** - Prevent overwhelming the system
5. **Monitor resource usage** - Track memory and CPU usage
6. **Configure cleanup appropriately** - Balance file retention with disk space usage
7. **Monitor cleanup statistics** - Track cleanup performance and adjust intervals as needed
8. **Use user-specific directories** - Leverage the new directory structure for better organization
9. **Built-in duplicate prevention** - The system automatically prevents processing the same request multiple times by checking for existing response files

## Security

1. **Always validate input** - Never trust client data
2. **Implement authentication** - Use bearer tokens or API keys
3. **Rate limiting** - Prevent abuse
4. **Audit logging** - Track all requests
5. **Sanitize output** - Prevent information leakage

Example security middleware:
```python
def auth_required(handler):
    def wrapper(request: Request) -> Response:
        auth = request.headers.get("Authorization", "")
        if not validate_auth(auth):
            return Response(
                body={"error": "Unauthorized"},
                status_code=401
            )
        return handler(request)
    return wrapper

@router.on_request("/secure")
@auth_required
def secure_handler(request: Request) -> Response:
    return Response(body={"secure": "data"})
```

## Cleanup Utility API Reference

### PeriodicCleanup Class

The `PeriodicCleanup` class provides automatic cleanup of old request and response files.

#### Constructor

```python
PeriodicCleanup(
    app_name: str,
    cleanup_interval: str = "1d",
    cleanup_expiry: str = "30d", 
    client: Optional[Client] = None,
    on_cleanup_complete: Optional[Callable[[CleanupStats], None]] = None
)
```

**Parameters:**
- `app_name`: Name of the Syft application
- `cleanup_interval`: How often to run cleanup (e.g., "1d", "2h", "30m")
- `cleanup_expiry`: How long to keep files (e.g., "30d", "7d", "2h")
- `client`: Optional SyftBox client instance
- `on_cleanup_complete`: Optional callback function called after each cleanup

#### Methods

##### `start() -> None`
Start the periodic cleanup in a background thread.

##### `stop() -> None`
Stop the periodic cleanup service.

##### `cleanup_now() -> CleanupStats`
Perform cleanup immediately without waiting for the next interval.

##### `get_stats() -> CleanupStats`
Get current cleanup statistics.

##### `is_running() -> bool`
Check if the cleanup service is currently running.

### CleanupStats Class

Statistics for cleanup operations.

#### Properties

- `requests_deleted: int` - Number of request files deleted
- `responses_deleted: int` - Number of response files deleted  
- `errors: int` - Number of errors encountered during cleanup
- `last_cleanup: Optional[datetime]` - Timestamp of last cleanup operation

#### Methods

##### `reset() -> None`
Reset all statistics to zero.

##### `__str__() -> str`
String representation of the statistics.

### Time Interval Parsing

The `parse_time_interval()` function converts human-readable time strings to seconds:

```python
from syft_event.cleanup import parse_time_interval

# Single units
parse_time_interval("1d")    # 86400 seconds
parse_time_interval("2h")    # 7200 seconds
parse_time_interval("30m")   # 1800 seconds
parse_time_interval("45s")   # 45 seconds

# Combined units
parse_time_interval("1d2h30m")  # 95400 seconds
parse_time_interval("2h15m30s") # 8130 seconds

# Case insensitive
parse_time_interval("1D") == parse_time_interval("1d")  # True
```

**Supported Units:**
- `d` - Days
- `h` - Hours
- `m` - Minutes
- `s` - Seconds

**Error Handling:**
- Raises `ValueError` for invalid formats
- Raises `ValueError` for empty strings
- Raises `ValueError` for unknown time units