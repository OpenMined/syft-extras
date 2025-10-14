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
- 🧹 **Automatic Cleanup**: Periodic cleanup of old request/response files with configurable retention
- 📂 **Organized File Structure**: User-specific directory organization for better request management

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

> **Note**: RPC endpoints automatically monitor both `FileCreatedEvent` and `FileMovedEvent` for request files. This is because request files can arrive via two different mechanisms: files delivered through websockets are initially stored as temporary files and then renamed to the target request file (triggering a move event), while files downloaded directly from the blob store are created directly (triggering a create event).

### File System Monitoring

```python
from syft_event import SyftEvents
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent

box = SyftEvents("file_monitor")

# Watch for JSON files in your datasite (responds to create, modify, and move events by default)
@box.watch("{datasite}/**/*.json")
def on_json_change(event):
    if hasattr(event, 'dest_path') and event.dest_path:
        print(f"JSON file moved: {event.src_path} -> {event.dest_path}")
    else:
        print(f"JSON file changed: {event.src_path}")

# Watch for specific file patterns with custom event filtering
@box.watch(["**/*.txt", "**/*.md"], event_filter=[FileCreatedEvent])
def on_text_files_created(event):
    print(f"Text file created: {event.src_path}")

# Watch for file moves specifically
@box.watch("**/*.log", event_filter=[FileMovedEvent])
def on_log_files_moved(event):
    print(f"Log file moved: {event.src_path} -> {event.dest_path}")

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

### Automatic Cleanup Configuration

SyftEvent now includes automatic cleanup of old request and response files to prevent disk space issues:

```python
from syft_event import SyftEvents

# Create with custom cleanup settings
box = SyftEvents(
    "my_app",
    cleanup_expiry="7d",    # Keep files for 7 days (default: 30d)
    cleanup_interval="1h"   # Run cleanup every hour (default: 1d)
)

# Check if cleanup is running
if box.is_cleanup_running():
    print("Cleanup service is active")

# Get cleanup statistics
stats = box.get_cleanup_stats()
print(f"Deleted {stats.requests_deleted} requests and {stats.responses_deleted} responses")
```

### Standalone Cleanup Utility

You can also run the cleanup utility independently:

```python
from syft_event.cleanup import PeriodicCleanup

# Create a standalone cleanup instance
cleanup = PeriodicCleanup(
    app_name="my_app",
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

## API Reference

### SyftEvents

The main class for creating event-driven applications.

#### Constructor

```python
SyftEvents(
    app_name: str, 
    publish_schema: bool = True, 
    client: Optional[Client] = None,
    cleanup_expiry: str = "30d",
    cleanup_interval: str = "1d"
)
```

- `app_name`: Name of your application
- `publish_schema`: Whether to automatically generate and publish API schemas
- `client`: Optional SyftBox client instance
- `cleanup_expiry`: How long to keep request/response files (e.g., "30d", "7d", "2h")
- `cleanup_interval`: How often to run cleanup (e.g., "1d", "1h", "30m")

#### Methods

##### `on_request(endpoint: str)`

Decorator to register RPC request handlers.

```python
@box.on_request("/my-endpoint")
def handler(param1: str, param2: int = 10) -> dict:
    return {"result": param1 * param2}
```

##### `watch(glob_path, event_filter=None)`

Decorator to register file system watchers. By default, watches for `FileCreatedEvent`, `FileModifiedEvent`, and `FileMovedEvent`.

```python
@box.watch("**/*.json")
def on_json_change(event):
    if hasattr(event, 'dest_path') and event.dest_path:
        print(f"File moved: {event.src_path} -> {event.dest_path}")
    else:
        print(f"File changed: {event.src_path}")
```

##### `include_router(router: EventRouter, prefix: str = "")`

Include routes from an EventRouter instance.

##### `run_forever()`

Start the event loop and run until interrupted.

##### `start()` / `stop()`

Start or stop the service programmatically.

##### `is_cleanup_running()`

Check if the automatic cleanup service is currently running.

##### `get_cleanup_stats()`

Get statistics about the cleanup operations.

```python
stats = box.get_cleanup_stats()
print(f"Requests deleted: {stats.requests_deleted}")
print(f"Responses deleted: {stats.responses_deleted}")
print(f"Errors: {stats.errors}")
print(f"Last cleanup: {stats.last_cleanup}")
```

### EventRouter

Helper class for organizing related endpoints.

```python
from syft_event import EventRouter

router = EventRouter()

@router.on_request("/endpoint")
def handler():
    return "response"
```

### PeriodicCleanup

Utility class for managing automatic cleanup of old request and response files.

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

#### Methods

##### `start()` / `stop()`

Start or stop the periodic cleanup service.

##### `cleanup_now()`

Perform cleanup immediately without waiting for the next interval.

##### `get_stats()`

Get current cleanup statistics.

##### `is_running()`

Check if the cleanup service is currently running.

## File Structure

When you create a SyftEvents app, it sets up the following directory structure:

```
~/SyftBox/datasites/{your-email}/app_data/{app_name}/
├── rpc/
│   ├── syft.pub.yaml          # Permission configuration
│   ├── rpc.schema.json        # Generated API schema
│   └── {endpoint}/            # Endpoint directories
│       ├── .syftkeep         # Directory marker
│       └── {sender-email}/    # User-specific subdirectories
│           ├── *.request     # Incoming requests from this user
│           └── *.response    # Generated responses for this user
```

### Directory Organization

- **User-Specific Structure**: Requests are now organized by sender email address, providing better isolation and organization
- **Legacy Support**: The system automatically migrates old request files to the new structure
- **Automatic Cleanup**: Old request/response files are automatically cleaned up based on configurable retention policies

## Configuration

### Permissions

SyftEvent automatically creates a `syft.pub.yaml` file with appropriate permissions:

```yaml
rules:
- pattern: rpc.schema.json
  access:
    read:
    - '*'
- pattern: '**/{{.UserEmail}}/*.request'
  access:
    read:
    - 'USER'
    write: 
    - 'USER'
- pattern: '**/{{.UserEmail}}/*.response'
  access:
    read: 
    - 'USER'
    write: 
    - 'USER'
```

### Time Interval Format

The cleanup utility supports human-readable time intervals:

- **Single units**: `"1d"`, `"2h"`, `"30m"`, `"45s"`
- **Combined units**: `"1d2h30m"`, `"2h15m30s"`, `"1d12h30m45s"`
- **Case insensitive**: `"1D"` is equivalent to `"1d"`

Examples:
- `"1d"` = 1 day (86400 seconds)
- `"2h"` = 2 hours (7200 seconds)
- `"30m"` = 30 minutes (1800 seconds)
- `"1d2h30m"` = 1 day, 2 hours, 30 minutes (95400 seconds)

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

## Changelog

### Version 0.2.7+

- **🧹 Automatic Cleanup**: Added periodic cleanup utility for old request/response files
- **📂 User-Specific Organization**: Requests are now organized by sender email address
- **🔄 Legacy Migration**: Automatic migration of old request files to new structure
- **⚙️ Configurable Retention**: Customizable cleanup intervals and file retention periods
- **📊 Cleanup Statistics**: Track cleanup operations with detailed statistics
