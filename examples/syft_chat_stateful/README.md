# Syft Chat Stateful Library

A library for facilitating persistent, asynchronous conversations between Syft users through a simple Python API with SQLite database storage.

## Overview

Syft Chat Stateful provides a robust framework for messaging between Syft datasites with persistent storage. It serves as:

1. **A persistent communication tool**: Enable direct messaging between Syft users with message history saved to a database
2. **An integration framework**: Easily embed secure messaging with data persistence in your Syft applications
3. **A learning resource**: Understand how to build stateful communication systems on Syft

The library handles the complexities of:
- Setting up background servers to receive messages
- Sending messages to other datasites
- Storing messages in a SQLite database
- Managing message history and threading across application restarts
- Discovering available chat users
- Custom message event handling

## Features

- **Persistent Storage**: All messages are stored in a SQLite database
- **Session Independence**: Message history is preserved between application restarts
- **Asynchronous Messaging**: Send and receive messages between Syft users
- **Message Threading**: Group related messages with thread IDs
- **SQL-Powered Filtering**: Advanced querying capabilities for message history
- **Message Listeners**: Register callbacks for real-time message processing
- **User Discovery**: Identify which users have chat enabled
- **Resource Management**: Clean shutdown of background server threads and database connections
- **Error Handling**: Robust error handling with clear feedback

## Quick Start Guide

### Step 1: Set up SyftBox Clients (Development Environment)

For testing, you'll need one or more SyftBox clients:

```bash
# Create Alice's config
cat > ~/.syft_alice_config.json << EOL
{
    "data_dir": "${HOME}/Desktop/SyftBoxAlice",
    "server_url": "https://syftboxstage.openmined.org/",
    "client_url": "http://127.0.0.1:8082/",
    "email": "alice@openmined.org",
    "token": "0",
    "access_token": "YOUR_ALICE_ACCESS_TOKEN",
    "client_timeout": 5.0
}
EOL

# Start Alice's SyftBox client
rm -rf ~/Desktop/SyftBoxAlice
syftbox client --server https://syftboxstage.openmined.org \
              --email alice@openmined.org \
              --sync_folder ~/Desktop/SyftBoxAlice \
              --port 8082 \
              --config ~/.syft_alice_config.json
```

### Step 2: Basic Chat Example with Database

```python
import syft_chat_stateful as syft_chat

# Create a chat client with a specific database file
client = syft_chat.client("~/.syft_alice_config.json", db_path="alice_chat_messages.db")

# List available chat users
chat_users = client.list_available_users()
print(f"Available chat users: {len(chat_users)}")

# Send a message to another user
if chat_users:
    other_user = chat_users[0]
    response = client.send_message(other_user, "Hello from Alice!")
    print(f"Message sent with ID: {response.message_id}")

# Get chat history from the database
messages = client.get_chat_history()
for msg in messages:
    print(f"[{msg.timestamp}] {msg.sender}: {msg.content}")

# Clean up when done
client.close()
```

### Step 3: Real-time Message Processing

```python
import syft_chat_stateful as syft_chat

# Create a chat client
client = syft_chat.client("~/.syft_config.json", db_path="chat_messages.db")

# Define a message listener
def message_handler(message):
    print(f"\n🔔 NEW MESSAGE from {message.sender}: {message.content}")
    
    # You could process messages differently based on content/sender
    if "urgent" in message.content.lower():
        print("⚠️ URGENT MESSAGE DETECTED!")

# Register the listener
client.add_message_listener(message_handler)

print("Chat client ready. Waiting for messages...")

# Keep the program running to receive messages
try:
    # In a real application, you might have your own event loop
    # or integrate with other systems
    input("Press Enter to exit...")
finally:
    client.close()
```

### Step 4: Advanced Database Querying

```python
import syft_chat_stateful as syft_chat
import sqlite3
from datetime import datetime, timedelta

# Create a chat client
client = syft_chat.client("~/.syft_config.json", db_path="chat_messages.db")

# Get chat history using the API
recent_messages = client.get_chat_history(since=datetime.now() - timedelta(days=1))
print(f"Recent messages: {len(recent_messages)}")

# For more advanced queries, you can access the database directly
conn = sqlite3.connect("chat_messages.db")
cursor = conn.cursor()

# Example: Find all messages in a specific thread
thread_id = "your_thread_id"
cursor.execute("SELECT msg_id, sender, content, thread_id, reply_to FROM messages WHERE thread_id = ?", (thread_id,))
thread_messages = cursor.fetchall()
print(f"Messages in thread: {len(thread_messages)}")

# Don't forget to close the connection
conn.close()

# Clean up when done
client.close()
```

## API Reference

### `SyftChatClient`

The main client class for sending and receiving chat messages with database storage.

#### Constructor

```python
SyftChatClient(config_path: Optional[str] = None, app_name: str = "syft_chat", db_path: str = "chat_messages.db")
```

**Arguments:**
- `config_path`: Path to a custom Syft config.json file
- `app_name`: Name of your application (determines RPC directory)
- `db_path`: Path to SQLite database file for message storage

#### Key Methods

```python
send_message(to_email: str, content: str, thread_id: Optional[str] = None, reply_to: Optional[str] = None) -> ChatResponse
```

Send a message to another user and store it in the database.

**Arguments:**
- `to_email`: Email/datasite to send message to
- `content`: Message content
- `thread_id`: Optional thread ID for conversation grouping
- `reply_to`: Optional ID of message being replied to

**Returns:**
- `ChatResponse` with status and message ID

```python
get_chat_history(with_user: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[ChatMessage]
```

Get chat history from the database, optionally filtered by user.

**Arguments:**
- `with_user`: Optional email to filter messages by sender
- `limit`: Maximum number of messages to retrieve
- `since`: Retrieve messages since this time

**Returns:**
- List of `ChatMessage` objects

```python
add_message_listener(listener: Callable[[ChatMessage], None])
```

Add a listener function that will be called for each new message.

**Arguments:**
- `listener`: Function that takes a `ChatMessage` parameter

```python
list_available_users() -> List[str]
```

Get a list of users with chat enabled.

**Returns:**
- List of user emails

```python
close()
```

Shut down the client and close database connections.

### Factory Function

```python
client(config_path: Optional[str] = None, db_path: str = "chat_messages.db") -> SyftChatClient
```

Create and return a new Syft Chat client with database storage.

**Arguments:**
- `config_path`: Optional path to a custom config.json file
- `db_path`: Path to SQLite database file for message storage

**Returns:**
- A `SyftChatClient` instance

## Database Management

The Stateful Syft Chat library uses SQLite to store messages. Key points about database management:

1. **Database Location**: By default, messages are stored in "chat_messages.db" in the current directory.
2. **Schema**: Messages are stored in a "messages" table with columns for message ID, sender, content, timestamp, thread ID, reply ID, and metadata.
3. **Persistence**: The database persists across application restarts, allowing message history to be maintained.
4. **Direct Access**: You can directly access the database using SQLite tools or libraries for advanced querying.
5. **Maintenance**: For large deployments, consider implementing database maintenance procedures like archiving old messages.

## Design Philosophy

The library is designed around several key principles:

1. **Persistence**: Message history is preserved across sessions
2. **Simplicity**: Easy to use API with sensible defaults
3. **Asynchronous operation**: Non-blocking message handling with background server
4. **Extensibility**: Custom message listeners for integration with other systems
5. **Reliability**: Robust error handling and message delivery confirmation
6. **Discoverability**: Easy to find other users with chat enabled

This approach makes it easy to add persistent chat functionality to your Syft applications.

## Troubleshooting

### Connection Issues
- Ensure SyftBox clients are running and connected
- Check network connectivity between clients
- Verify access tokens are valid

### Message Delivery Problems
- Verify the recipient has chat enabled using `list_available_users()`
- Check that both sender and recipient have the chat server running
- Ensure messages are being properly formatted

### Database Issues
- Check that the database file is writable and accessible
- Verify SQLite is properly installed and accessible
- For database corruption, create a backup and restore from a clean database
- Ensure you have sufficient disk space for message storage

### History Retrieval Issues
- Confirm that messages are being stored properly in the database
- Check that the filter parameters are correctly specified
- Verify that the client has permission to access the database

## Extending the Library

The library can be extended in many ways:

1. **Database migrations**: Add schema versioning for future upgrades
2. **Message archiving**: Implement procedures for archiving old messages
3. **Custom message processing**: Add specialized message listeners for different use cases
4. **Message encryption**: Add additional security layers for sensitive communications
5. **File attachments**: Extend the message model to include file references
6. **Read receipts**: Add acknowledgment of message reading
7. **User status**: Implement online/offline status tracking

## Examples of Possible Applications

1. **Collaborative Data Science**: Communicate about shared datasets with persistent message records
2. **Notifications**: Send alerts when long-running computations complete
3. **Command & Control**: Send instructions to remote systems with reliable message history
4. **Support Systems**: Enable direct communication with users who need assistance
5. **Automated Assistants**: Create chatbots that respond to specific queries
6. **Team Collaboration**: Facilitate team discussions about sensitive data
7. **Audit Trails**: Maintain records of communications for compliance purposes
8. **Knowledge Management**: Create persistent chat archives for institutional knowledge

The library provides a solid foundation for all these use cases and more.
