# SyftEvent

[![PyPI version](https://badge.fury.io/py/syft-event.svg)](https://badge.fury.io/py/syft-event)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A distributed event-driven RPC framework for SyftBox that enables file-based communication, request handling, and real-time file system monitoring across datasites.

## Features

- 🔄 **Event-Driven Architecture**: React to file system changes in real-time
- 🌐 **Distributed RPC**: File-based communication between datasites
- 📁 **File System Monitoring**: Watch for changes across multiple directories with glob patterns
- 🔒 **Secure Communication**: Built-in permission management for datasite access
- ⚡ **Async Support**: Handle both synchronous and asynchronous request handlers
- 📊 **Schema Generation**: Automatic API schema generation and publishing
- 🔌 **Router Support**: Organize endpoints with modular routers

## Installation

```bash
pip install syft-event
```

## Quick Start

### Basic RPC Server

```python
from syft_event import SyftEvents

# Create a SyftEvents instance
box = SyftEvents("my_app")

# Define an RPC endpoint
@box.on_request("/hello")
def hello_handler(name: str) -> str:
    return f"Hello, {name}!"

# Define another endpoint
@box.on_request("/calculate")
def calculate_handler(a: int, b: int, operation: str = "add") -> int:
    if operation == "add":
        return a + b
    elif operation == "multiply":
        return a * b
    else:
        raise ValueError("Unsupported operation")

# Start the server
box.run_forever()
```

### File System Monitoring

```python
from syft_event import SyftEvents
from watchdog.events import FileCreatedEvent, FileModifiedEvent

box = SyftEvents("file_monitor")

# Watch for JSON files in your datasite
@box.watch("{datasite}/**/*.json")
def on_json_change(event):
    print(f"JSON file changed: {event.src_path}")

# Watch for specific file patterns
@box.watch(["**/*.txt", "**/*.md"], event_filter=[FileCreatedEvent])
def on_text_files_created(event):
    print(f"Text file created: {event.src_path}")

box.run_forever()
```

### Using Routers

```python
from syft_event import SyftEvents, EventRouter

# Create a router for user-related endpoints
user_router = EventRouter()

@user_router.on_request("/profile")
def get_profile(user_id: str):
    return {"user_id": user_id, "name": "John Doe"}

@user_router.on_request("/settings")
def get_settings(user_id: str):
    return {"theme": "dark", "notifications": True}

# Main application
box = SyftEvents("user_service")

# Include the router with a prefix
box.include_router(user_router, prefix="/api/v1/users")

box.run_forever()
```

### Async Request Handlers

```python
import asyncio
from syft_event import SyftEvents

box = SyftEvents("async_app")

@box.on_request("/async-task")
async def async_handler(task_id: str) -> dict:
    # Simulate async work
    await asyncio.sleep(1)
    return {"task_id": task_id, "status": "completed"}

box.run_forever()
```

## API Reference

### SyftEvents

The main class for creating event-driven applications.

#### Constructor

```python
SyftEvents(app_name: str, publish_schema: bool = True, client: Optional[Client] = None)
```

- `app_name`: Name of your application
- `publish_schema`: Whether to automatically generate and publish API schemas
- `client`: Optional SyftBox client instance

#### Methods

##### `on_request(endpoint: str)`

Decorator to register RPC request handlers.

```python
@box.on_request("/my-endpoint")
def handler(param1: str, param2: int = 10) -> dict:
    return {"result": param1 * param2}
```

##### `watch(glob_path, event_filter=None)`

Decorator to register file system watchers.

```python
@box.watch("**/*.json")
def on_json_change(event):
    print(f"File changed: {event.src_path}")
```

##### `include_router(router: EventRouter, prefix: str = "")`

Include routes from an EventRouter instance.

##### `run_forever()`

Start the event loop and run until interrupted.

##### `start()` / `stop()`

Start or stop the service programmatically.

### EventRouter

Helper class for organizing related endpoints.

```python
from syft_event import EventRouter

router = EventRouter()

@router.on_request("/endpoint")
def handler():
    return "response"
```

## File Structure

When you create a SyftEvents app, it sets up the following directory structure:

```
~/SyftBox/datasites/{your-email}/app_data/{app_name}/
├── rpc/
│   ├── syft.pub.yaml          # Permission configuration
│   ├── rpc.schema.json        # Generated API schema
│   └── {endpoint}/            # Endpoint directories
│       ├── .syftkeep         # Directory marker
│       ├── *.request         # Incoming requests
│       └── *.response        # Generated responses
```

## Configuration

### Permissions

SyftEvent automatically creates a `syft.pub.yaml` file with appropriate permissions:

```yaml
rules:
- pattern: rpc.schema.json
  access:
    read: ['*']
- pattern: '**/*.request'
  access:
    read: ['*']
    write: ['*']
- pattern: '**/*.response'
  access:
    read: ['*']
    write: ['*']
```

## Advanced Usage

### Custom Response Objects

```python
from syft_event import SyftEvents, Response
from syft_rpc.protocol import SyftStatus

box = SyftEvents("advanced_app")

@box.on_request("/custom-response")
def custom_handler() -> Response:
    return Response(
        body={"message": "Custom response"},
        status_code=SyftStatus.SYFT_201_CREATED,
        headers={"X-Custom-Header": "value"}
    )
```

### State Management

```python
box = SyftEvents("stateful_app")

# Access shared state
box.state["counter"] = 0

@box.on_request("/increment")
def increment():
    box.state["counter"] += 1
    return {"counter": box.state["counter"]}
```

## Requirements

- Python 3.9+
- syft-rpc >= 0.2.4
- pathspec >= 0.12.1
- pydantic >= 2.10.4
- watchdog >= 6.0.0
- loguru >= 0.7.3
