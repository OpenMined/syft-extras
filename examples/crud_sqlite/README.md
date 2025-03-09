# Syft SQLite CRUD Application Example

A CRUD (Create, Read, Update, Delete) application built on Syft with SQLite persistence, demonstrating how to build data management applications with durable storage using Syft RPC.

## Overview

This application extends the basic CRUD example by implementing persistent storage with SQLite and SQLAlchemy. It serves as:

1. **A working example**: Demonstrates how to build a data persistence application on Syft with a real database
2. **A template for data-centric apps**: Shows patterns for managing structured data with SQL
3. **A learning resource**: Understand how to implement persistent data operations in a distributed environment

The example demonstrates:
- Creating and persisting data objects to SQLite
- Retrieving stored objects from the database
- Listing collections of objects
- Managing data with unique identifiers
- Using SQLAlchemy ORM for database operations

## Key Differences from In-Memory CRUD Example

- **Persistent Storage**: Data is stored in a SQLite database file rather than in-memory
- **SQLAlchemy ORM**: Uses Object-Relational Mapping for cleaner, safer database interactions
- **Database Schema Management**: Automatically creates tables and schema
- **Proper Session Management**: Includes database connection handling and cleanup
- **Database Configuration**: Supports custom database file paths

## Features

- **Complete CRUD Operations**: Create, Read, Update, and Delete functionality
- **Data Persistence**: Store and retrieve data across application restarts
- **SQLAlchemy ORM**: Avoid SQL string manipulation with an object-oriented approach
- **Pydantic Models**: Type-safe data structures with validation
- **Client-Server Architecture**: Separate client and server components
- **Configurable Deployment**: Support for custom configuration and database files
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

### Step 2: Start the SQLite CRUD Server

```bash
# Start the server with default config and database
just run-crud-sqlite-server

# Or with a custom config
just run-crud-sqlite-server config=~/.syft_custom_config.json

# Or with a custom database file
just run-crud-sqlite-server db=~/my_users.db

# Or with both custom config and database file
just run-crud-sqlite-server config=~/.syft_custom_config.json db=~/my_users.db
```

### Step 3: Run the CRUD Client

```bash
# Run the client with default config
just run-crud-sqlite-client

# Or with a custom config
just run-crud-sqlite-client config=~/.syft_custom_config.json
```

## Example Usage

The example client performs a series of operations to demonstrate the CRUD functionality:

1. **Creates** three users (Alice, Bob, and Charlie)
2. **Lists** all users in the system
3. **Retrieves** a specific user by ID
4. **Deletes** a user
5. **Lists** users again to show the deletion

You can modify the client to test other operations:

```python
from examples.crud_sqlite.crud_sql_client import User, client_example
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

- SQLite database storage via SQLAlchemy
- REST-like endpoints for CRUD operations
- Request handlers for each operation type
- Proper database connection management

```python
# Key components
class UserModel(Base):
    # SQLAlchemy model for database mapping
    __tablename__ = "users"
    
    uid = Column(String, primary_key=True)
    name = Column(String, nullable=False)

# Key endpoints
@user_router.on_request("/create")
def create_user(user: User, app: SyftEvents) -> User:
    # Store a new user in the database

@user_router.on_request("/get")
def get_user(uid: UUID, app: SyftEvents) -> User:
    # Retrieve a specific user from the database

@user_router.on_request("/delete")
def delete_user(uid: UUID, app: SyftEvents) -> User:
    # Remove a user from the database

@user_router.on_request("/list")
def list_users(app: SyftEvents) -> UserList:
    # Get all users from the database
```

### Client Component

The client provides:

- Methods to call server endpoints
- Data models matching the server
- Request/response handling

## Extending This Example

You can extend this example in several ways:

1. **Use a different database**: Replace SQLite with PostgreSQL, MySQL, or other SQL databases
2. **Add more entity types**: Create new models and tables for other data types
3. **Implement relationships**: Add foreign keys and relationship mappings between entities
4. **Add search functionality**: Create endpoints with advanced SQL queries
5. **Implement migrations**: Add schema migration support for database changes
6. **Add transactions**: Implement transaction management for multi-step operations

## Database Schema Management

The application automatically creates the required database schema on startup. If you need to make schema changes:

1. Modify the SQLAlchemy model classes to reflect your desired schema
2. For production applications, consider adding proper migration support with tools like Alembic

## Advantages of SQLAlchemy

This example uses SQLAlchemy to provide several advantages:

1. **Object-Oriented Approach**: Work with Python objects rather than raw SQL
2. **SQL Injection Prevention**: Automatic parameter escaping and safe query building
3. **Database Agnostic**: Switch database backends with minimal code changes
4. **Type Safety**: Enhanced type checking through model definitions
5. **Relationship Handling**: Easy management of related entities (for more complex applications)

## Troubleshooting

### Database Issues
- Check file permissions if the database cannot be created or accessed
- Use the `--db` parameter to specify an alternative database path
- For database corruption, delete the database file to start fresh

### Connection Issues
- Ensure your SyftBox client is running and connected
- Check that server and client are using the same configuration
- Verify the server is running before making client requests

### Performance
- Add indexes for frequently queried columns
- Use database query optimization techniques for larger datasets
- Consider connection pooling for high-concurrency applications
