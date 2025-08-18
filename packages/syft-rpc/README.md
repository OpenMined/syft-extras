# SyftRPC: Request/Response Serialization Protocol

SyftRPC provides low-level serialization and RPC (Remote Procedure Call) primitives for SyftBox applications. It enables asynchronous communication between distributed applications using filesystem-based transport with robust serialization support for Python objects.

## Overview

SyftRPC implements a request/response pattern that works entirely through the filesystem, eliminating the need for direct network connections. It provides comprehensive serialization support for Python objects, including Pydantic models, dataclasses, and built-in types, with full UTF-8 support and type validation.

## Key Features

- **Asynchronous RPC**: Send requests and receive responses asynchronously via filesystem transport
- **Rich Serialization**: Support for Pydantic models, dataclasses, dictionaries, and primitive types  
- **Full UTF-8 Support**: Handle international text and special characters correctly
- **Type Validation**: Built-in validation and error handling with Pydantic
- **Expiration Management**: Automatic cleanup of expired requests and responses
- **Bulk Operations**: Send requests to multiple endpoints simultaneously
- **Request Caching**: Optional caching to avoid duplicate requests
- **Futures Pattern**: Non-blocking operations with `.wait()` and `.resolve()` methods

## Architecture

SyftRPC operates on a simple request/response model:

1. **Client A** calls `send()` to create a request file
2. **Client B** discovers and processes the request file  
3. **Client B** calls `reply_to()` to create a response file
4. **Client A** receives the response via the returned future

## Installation

```bash
pip install syft-rpc
```

## Quick Start

### Basic Request/Response

**Sending a Request:**
```python
from syft_rpc import send, SyftMethod

# Send an asynchronous request
future = send(
    url="syft://user@domain.com/app_data/my_app/rpc/process_data",
    method=SyftMethod.POST,
    body={"data": "Hello World", "count": 42},
    expiry="15m"
)

# Wait for response
response = future.wait(timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text()}")
```

**Handling Requests:**
```python
from syft_rpc import reply_to, SyftStatus
from syft_core import Client
from pathlib import Path

def handle_request(request_path: Path):
    # Load the request
    from syft_rpc.protocol import SyftRequest
    request = SyftRequest.load(request_path)
    
    # Process the request
    data = request.json()
    result = {"processed": data["data"], "double_count": data["count"] * 2}
    
    # Send response
    response = reply_to(
        request=request,
        body=result,
        status_code=SyftStatus.SYFT_200_OK
    )
    
    return response
```

### Working with Pydantic Models

```python
from pydantic import BaseModel
from syft_rpc import send

class ProcessingRequest(BaseModel):
    text: str
    language: str = "en"
    max_length: int = 100

class ProcessingResponse(BaseModel):
    result: str
    word_count: int
    language: str

# Send structured request
request_data = ProcessingRequest(
    text="Hello, world!", 
    language="en",
    max_length=50
)

future = send(
    url="syft://user@domain.com/app_data/nlp/rpc/process",
    method="POST",
    body=request_data,  # Automatically serialized
    expiry="5m"
)

response = future.wait()
if response.is_success:
    # Parse response back to Pydantic model
    result = response.model(ProcessingResponse)
    print(f"Processed: {result.result}")
    print(f"Word count: {result.word_count}")
```

### Broadcast to Multiple Endpoints

```python
from syft_rpc import broadcast

# Send the same request to multiple endpoints
bulk_future = broadcast(
    urls=[
        "syft://user1@domain.com/app_data/worker/rpc/task",
        "syft://user2@domain.com/app_data/worker/rpc/task", 
        "syft://user3@domain.com/app_data/worker/rpc/task"
    ],
    body={"task": "compute_stats", "dataset": "sample.csv"},
    expiry="10m"
)

# Wait for all responses
responses = bulk_future.gather_completed(timeout=60)

# Process results
successful = [r for r in responses if r.is_success]
failed = [r for r in responses if not r.is_success]

print(f"Successful: {len(successful)}, Failed: {len(failed)}")
```

## API Reference

### Core Functions

#### `send(url, method="GET", body=None, headers=None, expiry="15m", cache=False, client=None) -> SyftFuture`

Send an asynchronous request to a SyftBox endpoint.

**Parameters:**
- `url`: Destination URL (SyftBoxURL or string)
- `method`: HTTP method (GET, POST, PUT, DELETE, etc.)
- `body`: Request body (str, bytes, dict, list, Pydantic model, etc.)
- `headers`: Optional HTTP headers dictionary
- `expiry`: Duration string ("15m", "1h", "1d")
- `cache`: Enable request caching to avoid duplicates
- `client`: SyftBox client (auto-loaded if not provided)

**Returns:**
- `SyftFuture`: Future object for tracking the response

#### `broadcast(urls, body=None, headers=None, expiry="15m", cache=False, client=None) -> SyftBulkFuture`

Send the same request to multiple endpoints simultaneously.

**Parameters:**
- `urls`: List of destination URLs
- Other parameters same as `send()`

**Returns:**
- `SyftBulkFuture`: Bulk future for tracking multiple responses

#### `reply_to(request, body=None, headers=None, status_code=200, client=None) -> SyftResponse`

Create and store a response to a SyftRequest.

**Parameters:**
- `request`: Original SyftRequest to respond to
- `body`: Response body (any serializable type)
- `headers`: Optional HTTP headers dictionary  
- `status_code`: HTTP status code (SyftStatus enum)
- `client`: SyftBox client (auto-loaded if not provided)

**Returns:**
- `SyftResponse`: The created response object

### Data Classes

#### `SyftRequest`

Represents an RPC request with full serialization support.

**Key Properties:**
- `id`: Unique request identifier
- `sender`: Email of the sender
- `url`: Target SyftBox URL
- `method`: HTTP method
- `body`: Serialized request body
- `headers`: Request headers
- `created`: Creation timestamp
- `expires`: Expiration timestamp

**Key Methods:**
- `text()`: Decode body as string
- `json()`: Parse body as JSON
- `model(cls)`: Parse body into Pydantic model

#### `SyftResponse`

Represents an RPC response with status handling.

**Key Properties:**
- `id`: Request identifier (matches original request)
- `sender`: Email of the responder
- `url`: Original request URL
- `status_code`: HTTP status code
- `body`: Serialized response body
- `headers`: Response headers

**Key Methods:**
- `is_success`: Check if response indicates success
- `raise_for_status()`: Raise exception for error responses
- `text()`: Decode body as string
- `json()`: Parse body as JSON
- `model(cls)`: Parse body into Pydantic model

#### `SyftFuture`

Represents a pending request with async resolution.

**Key Methods:**
- `wait(timeout=300, poll_interval=0.1)`: Block until response available
- `resolve()`: Check for response without blocking (returns None if pending)
- `is_expired`: Check if request has expired
- `is_rejected`: Check if request was rejected

#### `SyftBulkFuture`

Manages multiple SyftFuture objects for bulk operations.

**Key Methods:**
- `gather_completed(timeout=300)`: Wait for all responses
- `resolve()`: Check all futures for new responses
- `pending`: List of unresolved futures
- `successes`: List of successful responses
- `failures`: List of failed responses

### Serialization

The `serialize()` function handles conversion of Python objects to bytes:

**Supported Types:**
- **Primitives**: `str`, `int`, `float`, `bool`, `None`
- **Collections**: `dict`, `list`, `tuple`
- **Pydantic Models**: Automatic JSON serialization
- **Dataclasses**: Converted to dict then serialized
- **Bytes**: Passed through unchanged

```python
from syft_rpc.rpc import serialize

# Primitives
assert serialize("hello") == b"hello"
assert serialize(42) == b"42" 
assert serialize([1, 2, 3]) == b"[1, 2, 3]"

# Pydantic models
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int

user = User(name="Alice", age=30)
data = serialize(user)  # b'{"name":"Alice","age":30}'
```

### URL Construction

#### `make_url(datasite, app_name, endpoint) -> SyftBoxURL`

Utility to construct SyftBox RPC URLs.

```python
from syft_rpc.rpc import make_url

url = make_url(
    datasite="user@domain.com",
    app_name="my_app", 
    endpoint="/process"
)
# Returns: syft://user@domain.com/app_data/my_app/rpc/process
```

## Error Handling

SyftRPC provides comprehensive error handling:

```python
from syft_rpc import send, SyftTimeoutError, SyftError
from syft_rpc.protocol import SyftStatus

try:
    future = send(url="syft://user@domain.com/app_data/app/rpc/endpoint")
    response = future.wait(timeout=30)
    
    # Check for application-level errors
    if not response.is_success:
        if response.status_code == SyftStatus.SYFT_404_NOT_FOUND:
            print("Endpoint not found")
        elif response.status_code == SyftStatus.SYFT_403_FORBIDDEN:
            print("Permission denied")
        else:
            print(f"Request failed: {response.status_code}")
    
except SyftTimeoutError:
    print("Request timed out")
except SyftError as e:
    print(f"RPC error: {e}")
```

## Expiration and Cleanup

Requests automatically expire based on the `expiry` parameter:

```python
# Different expiry formats
send(url="...", expiry="30s")   # 30 seconds
send(url="...", expiry="5m")    # 5 minutes  
send(url="...", expiry="2h")    # 2 hours
send(url="...", expiry="1d")    # 1 day
```

Expired requests are automatically cleaned up when accessed through futures.

## Request Caching

Enable caching to avoid duplicate requests:

```python
# First request creates and caches
future1 = send(url="syft://user@domain.com/app_data/app/rpc/data", cache=True)

# Second identical request reuses cached version
future2 = send(url="syft://user@domain.com/app_data/app/rpc/data", cache=True)

# Both futures reference the same request
assert future1.id == future2.id
```

## File Locations

SyftRPC stores request/response files in the client's workspace:

```
{workspace}/datasites/{user@domain.com}/app_data/{app_name}/rpc/{endpoint}/
   {uuid}.request    # Request file
   {uuid}.response   # Response file (when ready)
   {uuid}.syftrejected.request  # Rejected marker (if rejected)
```

## Best Practices

### 1. Use Appropriate Expiry Times
```python
# Short for real-time operations
send(url="...", expiry="30s")

# Medium for background tasks
send(url="...", expiry="15m")

# Long for batch processing
send(url="...", expiry="1h")
```

### 2. Handle Timeouts Gracefully
```python
try:
    response = future.wait(timeout=10)
except SyftTimeoutError:
    # Check if request is still pending
    if future.resolve() is None:
        print("Still waiting for response...")
    else:
        print("Response arrived just after timeout")
```

### 3. Use Structured Data
```python
# Prefer Pydantic models over raw dicts
class TaskRequest(BaseModel):
    task_id: str
    parameters: dict
    priority: int = 1

request = TaskRequest(task_id="task_123", parameters={"key": "value"})
future = send(url="...", body=request)
```

### 4. Validate Responses
```python
response = future.wait()
if response.is_success:
    try:
        data = response.model(ExpectedResponseModel)
        # Process structured data
    except ValidationError:
        # Handle malformed response
        raw_data = response.json()
```

## Integration with SyftBox

SyftRPC integrates seamlessly with other SyftBox packages:

```python
from syft_core import Client
from syft_event import EventRouter
from syft_rpc import send, reply_to

# Use with syft-event for request handling
router = EventRouter()

@router.on_request("process")
def handle_process(request):
    # Process the request
    result = {"status": "processed", "data": request.json()}
    
    # Send response
    return reply_to(
        request=request,
        body=result,
        status_code=200
    )
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test categories  
pytest tests/serialize_test.py    # Serialization tests
pytest tests/utf8_test.py         # UTF-8 handling tests
```

### Project Structure

```
syft-rpc/
  ├── syft_rpc/
  │   ├── __init__.py        # Main exports: send, broadcast, reply_to, protocol classes
  │   ├── protocol.py        # Core messaging protocol with request/response classes and futures
  │   ├── py.typed           # Type annotations marker file
  │   ├── rpc_db.py          # SQLite database for persistent future tracking and storage
  │   ├── rpc.py             # Main RPC functions: send(), broadcast(), reply_to()
  │   └── util.py            # Duration parsing utilities (1h, 3d, 30s format)
  ├── tests/                 # Test suite directory
  ├── pyproject.toml         # Python project configuration and dependencies
  └── README.md              # Project documentation
```

## Dependencies

- `pydantic>=2.9.2`: Data validation and serialization
- `syft-core>=0.2.8`: SyftBox client and workspace management  
- `typing-extensions>=4.12.2`: Enhanced type hints

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is part of the OpenMined ecosystem. Please refer to the main repository for licensing information.