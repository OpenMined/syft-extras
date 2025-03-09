# Syft Chat Library

A library for facilitating asynchronous conversations between Syft users through a simple Python API.

## Overview

Syft Chat provides a robust framework for messaging between Syft datasites. It serves as:

1. **A communication tool**: Enable direct messaging between Syft users
2. **An integration framework**: Easily embed secure messaging in your Syft applications
3. **A learning resource**: Understand how to build communication systems on Syft

The library handles the complexities of:
- Setting up background servers to receive messages
- Sending messages to other datasites
- Managing message history and threading
- Discovering available chat users
- Custom message event handling

## Features

- **Asynchronous Messaging**: Send and receive messages between Syft users
- **Message Threading**: Group related messages with thread IDs
- **Message History**: Store and retrieve past conversations
- **Message Listeners**: Register callbacks for real-time message processing
- **User Discovery**: Identify which users have chat enabled
- **Resource Management**: Clean shutdown of background server threads
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

### Step 2: Basic Chat Example

```python
import syft_chat

# Create a chat client
client = syft_chat.client("~/.syft_alice_config.json")

# List available chat users
chat_users = client.list_available_users()
print(f"Available chat users: {len(chat_users)}")

# Send a message to another user
if chat_users:
    other_user = chat_users[0]
    response = client.send_message(other_user, "Hello from Alice!")
    print(f"Message sent with ID: {response.message_id}")

# Get chat history
messages = client.get_chat_history()
for msg in messages:
    print(f"[{msg.timestamp}] {msg.sender}: {msg.content}")

# Clean up when done
client.close()
```

### Step 3: Real-time Message Processing

```python
import syft_chat

# Create a chat client
client = syft_chat.client("~/.syft_config.json")

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

## API Reference

### `SyftChatClient`

The main client class for sending and receiving chat messages.

#### Constructor

```python
SyftChatClient(config_path: Optional[str] = None, app_name: str = "syft_chat")
```

**Arguments:**
- `config_path`: Path to a custom Syft config.json file
- `app_name`: Name of your application (determines RPC directory)

#### Key Methods

```python
send_message(to_email: str, content: str, thread_id: Optional[str] = None, reply_to: Optional[str] = None) -> ChatResponse
```
Send a message to another user.

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
Get chat history, optionally filtered by user.

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
Shut down the client.

### Factory Function

```python
client(config_path: Optional[str] = None) -> SyftChatClient
```
Create and return a new Syft Chat client.

**Arguments:**
- `config_path`: Optional path to a custom config.json file

**Returns:**
- A `SyftChatClient` instance

## Design Philosophy

The library is designed around several key principles:

1. **Simplicity**: Easy to use API with sensible defaults
2. **Asynchronous operation**: Non-blocking message handling with background server
3. **Extensibility**: Custom message listeners for integration with other systems
4. **Reliability**: Robust error handling and message delivery confirmation
5. **Discoverability**: Easy to find other users with chat enabled

This approach makes it easy to add chat functionality to your Syft applications.

## Troubleshooting

### Connection Issues
- Ensure SyftBox clients are running and connected
- Check network connectivity between clients
- Verify access tokens are valid

### Message Delivery Problems
- Verify the recipient has chat enabled using `list_available_users()`
- Check that both sender and recipient have the chat server running
- Ensure messages are being properly formatted

### History Retrieval Issues
- Confirm that messages are being stored properly
- Check that the filter parameters are correctly specified
- Verify that the client has permission to access the messages

## Extending the Library

The library can be extended in many ways:

1. **Custom message processing**: Add specialized message listeners for different use cases
2. **Message encryption**: Add additional security layers for sensitive communications
3. **File attachments**: Extend the message model to include file references
4. **Read receipts**: Add acknowledgment of message reading
5. **User status**: Implement online/offline status tracking

## Examples of Possible Applications

1. **Collaborative Data Science**: Communicate about shared datasets
2. **Notifications**: Send alerts when long-running computations complete
3. **Command & Control**: Send instructions to remote systems
4. **Support Systems**: Enable direct communication with users who need assistance
5. **Automated Assistants**: Create chatbots that respond to specific queries
6. **Team Collaboration**: Facilitate team discussions about sensitive data

The library provides a solid foundation for all these use cases and more.
