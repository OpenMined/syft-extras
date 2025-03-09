# Syft CRUD Application Example

A simple CRUD (Create, Read, Update, Delete) application built on Syft, demonstrating how to build data management applications with Syft RPC.

## Overview

This application provides a complete example of a basic CRUD service on Syft. It serves as:

1. **A working example**: Demonstrates how to build a data persistence application on Syft
2. **A template for data-centric apps**: Shows patterns for managing structured data
3. **A learning resource**: Understand how to implement basic data operations in a distributed environment

The example demonstrates:
- Creating and persisting data objects
- Retrieving stored objects
- Listing collections of objects
- Managing data with unique identifiers

## Features

- **Complete CRUD Operations**: Create, Read, Update, and Delete functionality
- **Data Persistence**: Store and retrieve data across sessions
- **Pydantic Models**: Type-safe data structures with validation
- **Client-Server Architecture**: Separate client and server components
- **Configurable Deployment**: Support for custom configuration files
- **Simple Interface**: Clean API for data operations

## Quick Start Guide

### Step 1: Set up SyftBox Clients (Development Environment)

For testing, you'll need one or more SyftBox clients:

```bash
# Create a config
cat > ~/.syft_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBox",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8082/",
    "email": "youremail@example.org",
    "token": "0",
    "access_token": "YOUR_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL

# Start SyftBox client
rm -rf ~/Desktop/SyftBox
syftbox client --server https://syftboxstage.openmined.org \
              --email youremail@example.org \
              --sync_folder ~/Desktop/SyftBox \
              --port 8082 \
              --config ~/.syft_config.json
```

### Step 2: Start the CRUD Server

```bash
# Start the server with default config
just run-crud-server

# Or with a custom config
just run-crud-server config=~/.syft_custom_config.json
```

### Step 3: Run the CRUD Client

```bash
# Run the client with default config
just run-crud-client

# Or with a custom config
just run-crud-client config=~/.syft_custom_config.json
```

## Example Usage

The example client performs a series of operations to demonstrate the CRUD functionality:

1. **Creates** three users (Alice, Bob, and Charlie)
2. **Lists** all users in the system

You can modify the client to test other operations:

```python
from examples.crud.crud_client import User, client_example
from syft_core import Client

# Load a client with custom config
client = Client.load("~/.syft_config.json")

# Run the example
client_example(client)

# Create a custom user
from uuid import uuid4
new_user = User(name="Dave")
# ... send request to create the user ...

# Get a specific user by UID
user_uid = uuid4()  # Replace with an actual UUID
# ... send request to get the user ...

# Delete a user
# ... send request to delete the user ...
```

## Architecture

### Server Component

The server implements:

- An in-memory store for User objects
- REST-like endpoints for CRUD operations
- Request handlers for each operation type

```python
# Key endpoints
@user_router.on_request("/create")
def create_user(user: User, app: SyftEvents) -> User:
    # Store a new user

@user_router.on_request("/get")
def get_user(uid: UUID, app: SyftEvents) -> User:
    # Retrieve a specific user

@user_router.on_request("/delete")
def delete_user(uid: UUID, app: SyftEvents) -> User:
    # Remove a user

@user_router.on_request("/list")
def list_users(app: SyftEvents) -> UserList:
    # Get all users
```

### Client Component

The client provides:

- Methods to call server endpoints
- Data models matching the server
- Request/response handling

## Extending This Example

You can extend this example in several ways:

1. **Add more entity types**: Create models and endpoints for other data types
2. **Implement relationships**: Add references between entities
3. **Add search functionality**: Create endpoints to query data by different criteria
4. **Add validation**: Extend the models with more validation rules
5. **Implement persistence**: Replace the in-memory store with a database

## Use Cases

This pattern can be adapted for various applications:

1. **User Management**: Manage user accounts and profiles
2. **Content Management**: Store and retrieve documents or media
3. **Inventory Systems**: Track products or assets
4. **Task Management**: Create and manage tasks or tickets
5. **Configuration Storage**: Maintain application settings

## Troubleshooting

### Connection Issues
- Ensure your SyftBox client is running and connected
- Check that server and client are using the same configuration
- Verify the server is running before making client requests

### Data Issues
- If data is not persisted, remember this example uses in-memory storage
- Check UUIDs when retrieving specific items
- Ensure data models match between client and server

### Performance
- Large data sets may cause slowdowns in the in-memory implementation
- Consider paging for large collections
- Add indexes or more efficient data structures for bigger applications
