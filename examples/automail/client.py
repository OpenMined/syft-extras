from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import json
from pathlib import Path
import random

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from loguru import logger
from pydantic import BaseModel, Field
from syft_core import Client
from syft_event import SyftEvents
from syft_event.types import Request
from syft_rpc import rpc


# Message models
@dataclass
class ChatMessage:
    content: str
    sender: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChatResponse(BaseModel):
    status: str = Field(description="Status of message delivery")
    ts: datetime = Field(description="Timestamp of the response")
    message_id: str = Field(default="", description="ID of the message being acknowledged")


# Set up the event listener
box = SyftEvents("automail")
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Store client and recipient information with conversation ID
client_info = {
    "client": None, 
    "recipient": None,
    "conversation_id": None
}

# Update the global conversations dict structure
# Now it will be: conversations[contact][conversation_id] = {"messages": [...], "title": "...", "created_at": "..."}
conversations = {}

# Add this class for persistent storage
class ChatStorage:
    """Handles persistent storage of conversations and contacts."""
    
    def __init__(self):
        # Create storage directory in user's home folder
        self.storage_dir = Path.home() / ".syft" / "automail"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Path to the conversations file
        self.conversations_file = self.storage_dir / "conversations.json"
    
    def load_conversations(self):
        """Load conversations from disk."""
        if not self.conversations_file.exists():
            return {}
        
        try:
            with open(self.conversations_file, 'r') as f:
                data = json.load(f)
                
                # Convert the old format if needed (backward compatibility)
                converted_data = self._convert_old_format(data)
                
                # Convert timestamp strings back to datetime objects
                for contact, conversations in converted_data.items():
                    for conv_id, messages in conversations.items():
                        for msg in messages:
                            if "timestamp" in msg:
                                try:
                                    msg["ts_obj"] = datetime.fromisoformat(msg["timestamp"].replace('Z', '+00:00'))
                                except (ValueError, TypeError):
                                    # If parsing fails, use a default timestamp
                                    msg["ts_obj"] = datetime.now(timezone.utc)
                
                return converted_data
        except Exception as e:
            logger.error(f"Error loading conversations: {e}")
            return {}
    
    def _convert_old_format(self, data):
        """Convert old single-conversation format to multi-conversation format."""
        converted = {}
        
        # Check if we're dealing with the old format
        old_format = False
        for contact, value in data.items():
            if isinstance(value, list):
                old_format = True
                break
        
        if old_format:
            logger.info("Converting from old single-conversation format to multi-conversation format")
            for contact, messages in data.items():
                # Create a default conversation ID for existing messages
                default_conv_id = "default"
                converted[contact] = {default_conv_id: {
                    "messages": messages,
                    "title": "Default Conversation",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }}
            return converted
        else:
            return data
    
    def save_conversations(self, conversations):
        """Save conversations to disk."""
        try:
            # Create a serializable copy of the conversations
            serializable_data = {}
            
            for contact, convs in conversations.items():
                serializable_data[contact] = {}
                for conv_id, conv_data in convs.items():
                    serializable_data[contact][conv_id] = {
                        "messages": [],
                        "title": conv_data.get("title", "Untitled Conversation"),
                        "created_at": conv_data.get("created_at", datetime.now(timezone.utc).isoformat())
                    }
                    
                    for msg in conv_data.get("messages", []):
                        # Create a copy to avoid modifying the original
                        serializable_msg = msg.copy()
                        # Remove the datetime object that can't be JSON serialized
                        if "ts_obj" in serializable_msg:
                            del serializable_msg["ts_obj"]
                        serializable_data[contact][conv_id]["messages"].append(serializable_msg)
            
            # Write to file
            with open(self.conversations_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)
                
            logger.debug("Conversations saved to disk")
            return True
        except Exception as e:
            logger.error(f"Error saving conversations: {e}")
            return False


# Initialize the storage
chat_storage = ChatStorage()

# Generate a unique conversation ID
def generate_conversation_id():
    """Generate a unique conversation ID."""
    return f"conv-{int(time.time())}-{hash(str(random.random())) % 10000}"


@box.on_request("/message")
def handle_message(message: ChatMessage, ctx: Request) -> ChatResponse:
    """Handle incoming chat messages."""
    sender = message.sender if message.sender else "Unknown"
    
    # Skip processing if message is from ourselves
    if sender == client_info["client"].email:
        return ChatResponse(
            status="received (self)",
            ts=datetime.now(timezone.utc),
        )
    
    # Generate a message ID to use in response
    message_id = f"{int(time.time())}-{hash(message.content) % 10000}"
    
    # Handle timestamp formatting - ensure we have a datetime object
    if isinstance(message.ts, datetime):
        timestamp = message.ts
        time_str = message.ts.strftime('%H:%M:%S')
    else:
        # If ts is a string, try to parse it
        try:
            timestamp = datetime.fromisoformat(str(message.ts).replace('Z', '+00:00'))
            time_str = timestamp.strftime('%H:%M:%S')
        except ValueError:
            # If parsing fails, use current time
            timestamp = datetime.now(timezone.utc)
            time_str = str(message.ts)
    
    # Check if the message contains conversation metadata
    conversation_id = "default"
    conversation_title = "New Conversation"
    
    # Check if message content has conversation info (prefixed with special marker)
    if message.content.startswith("__CONV_INFO__:"):
        try:
            # Extract conversation info
            parts = message.content.split(":", 2)
            if len(parts) >= 3:
                conversation_id = parts[1]
                # The actual message is after the second colon
                actual_content = parts[2]
                
                # Create or update the conversation
                if sender not in conversations:
                    conversations[sender] = {}
                
                if conversation_id not in conversations[sender]:
                    conversations[sender][conversation_id] = {
                        "messages": [],
                        "title": f"Conversation from {sender}",
                        "created_at": timestamp.isoformat()
                    }
                
                message.content = actual_content
        except Exception as e:
            logger.error(f"Error extracting conversation info: {e}")
    
    # Format the message for the UI
    msg_data = {
        "id": message_id,
        "sender": sender,
        "time": time_str,
        "content": message.content,
        "is_self": False,
        "timestamp": timestamp.isoformat(),  # Store ISO format for sorting
        "ts_obj": timestamp,  # Store the actual datetime for sorting
        "status": "received",  # Mark as received immediately
        "conversation_id": conversation_id  # Include conversation ID
    }
    
    # Add to the conversation with this sender
    add_message_to_conversation(sender, msg_data, conversation_id)
    
    # Update the UI if we're currently chatting with this sender in this conversation
    if client_info["recipient"] == sender and client_info["conversation_id"] == conversation_id:
        socketio.emit('message_history', get_serializable_messages(sender, conversation_id))
    else:
        # Notify about unread message from another contact/conversation
        socketio.emit('unread_message', {
            "sender": sender,
            "conversation_id": conversation_id
        })
    
    # Send a response with the message ID for tracking
    return ChatResponse(
        status="received",
        ts=datetime.now(timezone.utc),
        message_id=message_id
    )


def add_message_to_conversation(recipient, msg_data, conversation_id=None):
    """Add a message to a specific conversation and save to disk."""
    # Use the current conversation ID if none specified
    if conversation_id is None:
        conversation_id = client_info["conversation_id"]
    
    # If there's still no conversation ID, use or create the default one
    if conversation_id is None:
        conversation_id = "default"
    
    # Initialize the contact if it doesn't exist
    if recipient not in conversations:
        conversations[recipient] = {}
    
    # Initialize the conversation if it doesn't exist
    if conversation_id not in conversations[recipient]:
        conversations[recipient][conversation_id] = {
            "messages": [],
            "title": "New Conversation",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    
    # Add the message to the conversation
    conversations[recipient][conversation_id]["messages"].append(msg_data)
    
    # Sort messages by timestamp
    conversations[recipient][conversation_id]["messages"].sort(
        key=lambda x: x.get("ts_obj", datetime.fromtimestamp(0, tz=timezone.utc))
    )
    
    # Save conversations to disk
    chat_storage.save_conversations(conversations)
    
    # Update UI only if this is the current recipient and conversation
    if recipient == client_info["recipient"] and conversation_id == client_info["conversation_id"]:
        socketio.emit('message_history', get_serializable_messages(recipient, conversation_id))


def get_serializable_messages(recipient=None, conversation_id=None):
    """Create a JSON-serializable copy of the message history for a conversation."""
    # Use the current recipient and conversation if none specified
    if recipient is None:
        recipient = client_info["recipient"]
    
    if conversation_id is None:
        conversation_id = client_info["conversation_id"]
    
    if not recipient or not conversation_id or recipient not in conversations or conversation_id not in conversations[recipient]:
        return []
    
    # Create a serializable copy of the conversation
    serializable_messages = []
    for msg in conversations[recipient][conversation_id]["messages"]:
        # Create a copy to avoid modifying the original
        serializable_msg = msg.copy()
        # Remove the datetime object that can't be JSON serialized
        if "ts_obj" in serializable_msg:
            del serializable_msg["ts_obj"]
        serializable_messages.append(serializable_msg)
    
    return serializable_messages


@socketio.on('send_message')
def handle_send_message(data):
    content = data.get('message')
    recipient = client_info["recipient"]
    conversation_id = client_info["conversation_id"]
    
    if not content or not recipient or not conversation_id:
        socketio.emit('status', {"message": "Message, recipient, or conversation missing"})
        return
    
    # Generate a message ID here for consistent optimistic updates
    client = client_info["client"]
    message_id = f"{int(time.time())}-{hash(content) % 10000}"
    timestamp = datetime.now(timezone.utc)
    
    # Prefix message with conversation info for new conversations
    actual_content = content
    content = f"__CONV_INFO__:{conversation_id}:{content}"
    
    # Send optimistic UI update immediately to sender
    msg_data = {
        "id": message_id,
        "sender": client.email,
        "time": timestamp.strftime('%H:%M:%S'),
        "content": actual_content,  # Use the actual content without the prefix
        "is_self": True,
        "status": "sending",  # Initial status
        "timestamp": timestamp.isoformat(),  # Store ISO format for sorting
        "ts_obj": timestamp,  # Store the actual datetime for sorting
        "conversation_id": conversation_id  # Include conversation ID
    }
    
    # Add to the conversation with this recipient
    add_message_to_conversation(recipient, msg_data, conversation_id)
    
    # Then start the background sending process
    threading.Thread(target=send_message, args=(recipient, content, message_id, timestamp)).start()


def send_message(recipient: str, content: str, message_id: str = None, timestamp: datetime = None) -> None:
    """Send a chat message to another user."""
    client = client_info["client"]
    if not client:
        socketio.emit('status', {"message": "Not logged in"})
        return
    
    # Create the message with the correct timestamp
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
        
    message = ChatMessage(content=content, sender=client.email, ts=timestamp)
    
    # Generate a unique message ID if not provided
    if message_id is None:
        message_id = f"{int(time.time())}-{hash(content) % 10000}"
    
    # Update the UI to show "sending" status (one checkmark)
    socketio.emit('message_status_update', {
        "id": message_id,
        "status": "sending"
    })
    
    # Send in background thread to keep UI responsive
    def send_and_confirm():
        try:
            future = rpc.send(
                url=f"syft://{recipient}/api_data/automail/rpc/message",
                body=message,
                expiry="10m",  # Increase from 5m to 10m
                cache=False,
            )
            
            # Use a longer timeout for messages on slow networks
            response = future.wait(timeout=180)  # Increase from 120 to 180 seconds for extra margin
            
            response.raise_for_status()
            chat_response = response.model(ChatResponse)
            
            # Update message as delivered (server received)
            for msg in conversations[recipient]["default"]["messages"]:
                if msg.get("id") == message_id:
                    msg["status"] = "delivered"
                    break
            
            # Save the updated status to disk
            chat_storage.save_conversations(conversations)
            
            # Send confirmation to UI (two checkmarks)
            socketio.emit('message_status_update', {
                "id": message_id,
                "status": "delivered",
                "remote_id": chat_response.message_id  # Store ID assigned by recipient
            })
            
            socketio.emit('status', {"message": "Message delivered"})
            logger.debug(f"Message delivered: {chat_response.status}")
        except Exception as e:
            # Update status to failed in memory
            for msg in conversations[recipient]["default"]["messages"]:
                if msg.get("id") == message_id:
                    msg["status"] = "failed"
                    break
                    
            # Save the failure status to disk
            chat_storage.save_conversations(conversations)
            
            # Update status to failed in UI
            socketio.emit('message_status_update', {
                "id": message_id,
                "status": "failed"
            })
            socketio.emit('status', {"message": f"Delivery status unknown: {str(e)}"})
            logger.error(f"Error sending message: {e}")
    
    send_and_confirm()


def start_server():
    """Start the message server in a background thread."""
    def run_server():
        try:
            logger.info(f"Starting chat server at {box.app_rpc_dir}")
            box.run_forever()
        except Exception as e:
            logger.error(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    return server_thread


# Flask routes
@app.route('/')
def index():
    return render_template('chat.html')


@socketio.on('connect')
def handle_connect(auth=None):
    """Handle client connection - with proper argument handling."""
    # Send list of contacts to the client
    contacts = list(conversations.keys())
    socketio.emit('contact_list', contacts)
    
    # Send current user info
    if client_info["client"]:
        socketio.emit('user_info', {
            "client": client_info["client"].email,
            "recipient": client_info["recipient"],
            "conversation_id": client_info["conversation_id"]
        })
    
    # Send conversation history if there is a current recipient and conversation
    if client_info["recipient"] and client_info["conversation_id"]:
        socketio.emit('message_history', get_serializable_messages())


@socketio.on('set_recipient')
def handle_set_recipient(data):
    """Set the current recipient and list their conversations."""
    recipient = data.get('recipient')
    if recipient:
        client_info["recipient"] = recipient
        
        # Get all conversations for this recipient
        recipient_conversations = []
        if recipient in conversations:
            for conv_id, conv_data in conversations[recipient].items():
                # Get the first non-empty message to use as the preview
                preview = ""
                if conv_data["messages"]:
                    preview = conv_data["messages"][-1]["content"]
                    if len(preview) > 30:
                        preview = preview[:30] + "..."
                
                recipient_conversations.append({
                    "id": conv_id,
                    "title": conv_data.get("title", "Untitled Conversation"),
                    "created_at": conv_data.get("created_at", ""),
                    "preview": preview,
                    "message_count": len(conv_data["messages"])
                })
        
        # Sort conversations by creation date (newest first)
        recipient_conversations.sort(key=lambda x: x["created_at"], reverse=True)
        
        # Send the conversations list
        socketio.emit('conversation_list', recipient_conversations)
        socketio.emit('status', {"message": f"Selected contact: {recipient}"})
        
        # Don't set a specific conversation yet - let the user choose


@socketio.on('set_conversation')
def handle_set_conversation(data):
    """Set the current conversation."""
    conversation_id = data.get('conversation_id')
    recipient = client_info["recipient"]
    
    if recipient and conversation_id:
        client_info["conversation_id"] = conversation_id
        
        # If the conversation doesn't exist yet, create it
        if recipient not in conversations:
            conversations[recipient] = {}
        
        if conversation_id not in conversations[recipient]:
            conversations[recipient][conversation_id] = {
                "messages": [],
                "title": data.get('title', 'New Conversation'),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            # Save to disk
            chat_storage.save_conversations(conversations)
            
        socketio.emit('status', {"message": f"Conversation selected"})
        socketio.emit('message_history', get_serializable_messages(recipient, conversation_id))


@socketio.on('create_conversation')
def handle_create_conversation(data):
    """Create a new conversation with the current recipient."""
    recipient = client_info["recipient"]
    title = data.get('title', 'New Conversation')
    
    if recipient:
        # Generate a new conversation ID
        conversation_id = generate_conversation_id()
        
        # Initialize the conversation
        if recipient not in conversations:
            conversations[recipient] = {}
        
        conversations[recipient][conversation_id] = {
            "messages": [],
            "title": title,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Save to disk
        chat_storage.save_conversations(conversations)
        
        # Set as the current conversation
        client_info["conversation_id"] = conversation_id
        
        # Send updated conversations list
        recipient_conversations = []
        for conv_id, conv_data in conversations[recipient].items():
            recipient_conversations.append({
                "id": conv_id,
                "title": conv_data.get("title", "Untitled Conversation"),
                "created_at": conv_data.get("created_at", ""),
                "preview": "",
                "message_count": len(conv_data["messages"])
            })
        
        # Sort conversations by creation date (newest first)
        recipient_conversations.sort(key=lambda x: x["created_at"], reverse=True)
        
        socketio.emit('conversation_list', recipient_conversations)
        socketio.emit('status', {"message": f"New conversation created: {title}"})
        socketio.emit('message_history', get_serializable_messages(recipient, conversation_id))
        
        return {'status': 'success', 'conversation_id': conversation_id}
    
    return {'status': 'error', 'message': 'No recipient selected'}


@socketio.on('add_contact')
def handle_add_contact(data):
    """Add a new contact."""
    new_contact = data.get('contact')
    if new_contact and '@' in new_contact:
        # Initialize an empty contact if it doesn't exist
        if new_contact not in conversations:
            conversations[new_contact] = {}
            # Save the updated conversations to disk
            chat_storage.save_conversations(conversations)
        
        # Send updated contacts list
        socketio.emit('contact_list', list(conversations.keys()))
        
        # Switch to this contact
        client_info["recipient"] = new_contact
        client_info["conversation_id"] = None  # Reset conversation ID
        
        # Send list of conversations for this contact (likely empty)
        recipient_conversations = []
        for conv_id, conv_data in conversations[new_contact].items():
            recipient_conversations.append({
                "id": conv_id,
                "title": conv_data.get("title", "Untitled Conversation"),
                "created_at": conv_data.get("created_at", ""),
                "preview": "",
                "message_count": len(conv_data["messages"])
            })
        
        socketio.emit('conversation_list', recipient_conversations)
        socketio.emit('status', {"message": f"Added contact: {new_contact}"})


def ensure_template_dir():
    """Create templates directory if it doesn't exist."""
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
    return template_dir


def create_html_template():
    """Create the HTML template for the chat interface."""
    template_dir = ensure_template_dir()
    template_path = os.path.join(template_dir, 'chat.html')
    
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syft Chat</title>
    <script src="https://cdn.socket.io/4.4.1/socket.io.min.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1000px;
            margin: 20px auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 90vh;
        }
        .header {
            background: #4a69bd;
            color: white;
            padding: 15px;
            text-align: center;
            flex: 0 0 auto;
        }
        .main-area {
            display: flex;
            flex: 1;
            overflow: hidden;
        }
        .contacts-panel {
            width: 250px;
            background-color: #f0f0f0;
            overflow-y: auto;
            border-right: 1px solid #ddd;
            flex: 0 0 auto;
            display: flex;
            flex-direction: column;
        }
        .contacts-header {
            padding: 10px;
            background-color: #e6e6e6;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .contacts-header h3 {
            margin: 0;
            font-size: 16px;
        }
        .add-contact-btn {
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            cursor: pointer;
            font-size: 14px;
        }
        .contact-list {
            list-style: none;
            padding: 0;
            margin: 0;
            overflow-y: auto;
            flex: 1;
        }
        .contact-item {
            padding: 10px 15px;
            border-bottom: 1px solid #ddd;
            cursor: pointer;
        }
        .contact-item:hover {
            background-color: #e9e9e9;
        }
        .contact-item.active {
            background-color: #d4e4fc;
            font-weight: bold;
        }
        .contact-item .unread-badge {
            background-color: #4a69bd;
            color: white;
            border-radius: 50%;
            padding: 2px 6px;
            font-size: 0.7em;
            margin-left: 5px;
            display: none;
        }
        .chat-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .chat-box {
            flex: 1;
            overflow-y: auto;
            padding: 15px;
            background-color: #f9f9f9;
        }
        .message {
            margin-bottom: 10px;
            padding: 10px;
            border-radius: 5px;
            max-width: 70%;
            clear: both;
        }
        .self {
            background-color: #dcf8c6;
            float: right;
        }
        .other {
            background-color: #fff;
            float: left;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .message-time {
            font-size: 0.7em;
            color: #999;
            margin-top: 5px;
            text-align: right;
        }
        .message-sender {
            font-weight: bold;
            margin-bottom: 3px;
        }
        .input-area {
            padding: 15px;
            display: flex;
            background-color: #f9f9f9;
            border-top: 1px solid #ddd;
        }
        .message-input {
            flex: 1;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        .send-button {
            padding: 10px 15px;
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            margin-left: 10px;
            cursor: pointer;
        }
        .status {
            text-align: center;
            padding: 10px;
            color: #666;
            border-top: 1px solid #ddd;
        }
        .controls {
            display: flex;
            justify-content: space-between;
            padding: 5px 15px;
            background-color: #f3f3f3;
            border-bottom: 1px solid #ddd;
        }
        .connection-status {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 5px;
        }
        .connected {
            background-color: #4CAF50;
        }
        .disconnected {
            background-color: #F44336;
        }
        .reconnecting {
            background-color: #FFC107;
        }
        .refresh-button {
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            cursor: pointer;
            font-size: 12px;
        }
        .message-status {
            display: inline-block;
            margin-left: 5px;
            font-size: 1em;
        }
        
        .modal {
            display: none;
            position: fixed;
            z-index: 1;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0,0,0,0.4);
        }
        
        .modal-content {
            background-color: #fefefe;
            margin: 15% auto;
            padding: 20px;
            border: 1px solid #888;
            width: 300px;
            border-radius: 5px;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .modal-header h3 {
            margin: 0;
            color: #4a69bd;
        }
        
        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        
        .close:hover {
            color: #555;
        }
        
        .modal-body {
            margin-bottom: 15px;
        }
        
        .modal-footer {
            text-align: right;
        }
        
        .modal-input {
            width: 100%;
            padding: 8px;
            box-sizing: border-box;
            margin-bottom: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        
        .modal-button {
            padding: 8px 15px;
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        
        .no-recipient-message {
            text-align: center;
            color: #666;
            margin-top: 30px;
            padding: 20px;
        }
        
        .no-contacts-message {
            text-align: center;
            color: #666;
            padding: 20px;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Syft Chat</h2>
            <div id="user-info"></div>
        </div>
        
        <div class="main-area">
            <!-- Contacts Panel -->
            <div class="contacts-panel">
                <div class="contacts-header">
                    <h3>Contacts</h3>
                    <button class="add-contact-btn" id="add-contact-btn">+ Add</button>
                </div>
                <ul class="contact-list" id="contact-list">
                    <!-- Contacts will be added here -->
                </ul>
                <div class="no-contacts-message" id="no-contacts-message">
                    No contacts yet.<br>Click "Add" to start a conversation.
                </div>
            </div>
            
            <!-- Conversations Panel (new) -->
            <div class="conversations-panel" id="conversations-panel">
                <div class="conversations-header">
                    <h3>Conversations</h3>
                    <button class="new-conversation-btn" id="new-conversation-btn">+ New</button>
                </div>
                <ul class="conversation-list" id="conversation-list">
                    <!-- Conversations will be added here -->
                </ul>
                <div class="no-conversations-message" id="no-conversations-message">
                    No conversations yet.<br>Click "New" to start a conversation.
                </div>
            </div>
            
            <!-- Chat Panel -->
            <div class="chat-panel">
                <div class="controls">
                    <div>
                        <span class="connection-status" id="connection-status"></span>
                        <span id="connection-text">Connecting...</span>
                    </div>
                    <div class="conversation-title" id="conversation-title"></div>
                    <button class="refresh-button" id="refresh-button">Refresh</button>
                </div>
                
                <div class="chat-box" id="chat-box">
                    <!-- Messages will be added here -->
                </div>
                
                <div class="no-conversation-message" id="no-conversation-message">
                    Select or create a conversation to start chatting.
                </div>
                
                <div class="input-area">
                    <input type="text" class="message-input" id="message-input" placeholder="Type a message...">
                    <button class="send-button" id="send-button">Send</button>
                </div>
                
                <div class="status" id="status"></div>
            </div>
        </div>
    </div>
    
    <!-- Add Contact Modal -->
    <div id="add-contact-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Add New Contact</h3>
                <span class="close" id="close-contact-modal">&times;</span>
            </div>
            <div class="modal-body">
                <input type="text" id="new-contact-input" class="modal-input" placeholder="Enter email address">
            </div>
            <div class="modal-footer">
                <button id="confirm-add-contact" class="modal-button">Add</button>
            </div>
        </div>
    </div>
    
    <!-- New Conversation Modal -->
    <div id="new-conversation-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>New Conversation</h3>
                <span class="close" id="close-conversation-modal">&times;</span>
            </div>
            <div class="modal-body">
                <input type="text" id="conversation-title-input" class="modal-input" placeholder="Conversation title (optional)">
            </div>
            <div class="modal-footer">
                <button id="confirm-new-conversation" class="modal-button">Create</button>
            </div>
        </div>
    </div>
    
    <script>
        // DOM Elements
        const chatBox = document.getElementById('chat-box');
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        const statusDiv = document.getElementById('status');
        const connectionStatus = document.getElementById('connection-status');
        const connectionText = document.getElementById('connection-text');
        const refreshButton = document.getElementById('refresh-button');
        const userInfoDiv = document.getElementById('user-info');
        const contactList = document.getElementById('contact-list');
        const conversationList = document.getElementById('conversation-list');
        const noContactsMessage = document.getElementById('no-contacts-message');
        const noConversationsMessage = document.getElementById('no-conversations-message');
        const conversationsPanel = document.getElementById('conversations-panel');
        const noConversationMessage = document.getElementById('no-conversation-message');
        const conversationTitle = document.getElementById('conversation-title');
        
        // New conversation elements
        const newConversationBtn = document.getElementById('new-conversation-btn');
        const newConversationModal = document.getElementById('new-conversation-modal');
        const closeConversationModal = document.getElementById('close-conversation-modal');
        const confirmNewConversation = document.getElementById('confirm-new-conversation');
        const conversationTitleInput = document.getElementById('conversation-title-input');
        
        // Track current selections
        let currentRecipient = null;
        let currentConversationId = null;
        
        // Hide panels initially
        conversationsPanel.style.display = 'none';
        
        // Socket.io connection
        const socket = io();
        let isConnected = false;
        
        // Connect to server
        socket.on('connect', () => {
            isConnected = true;
            connectionStatus.classList.add('connected');
            connectionStatus.classList.remove('disconnected', 'reconnecting');
            connectionText.textContent = 'Connected';
            
            // Request info on connection
            requestMessages();
        });
        
        // Handle disconnection
        socket.on('disconnect', () => {
            isConnected = false;
            connectionStatus.classList.add('disconnected');
            connectionStatus.classList.remove('connected', 'reconnecting');
            connectionText.textContent = 'Disconnected';
        });
        
        // Handle reconnecting
        socket.on('reconnecting', () => {
            connectionStatus.classList.add('reconnecting');
            connectionStatus.classList.remove('connected', 'disconnected');
            connectionText.textContent = 'Reconnecting...';
        });
        
        function requestMessages() {
            if (isConnected) {
                console.log('Requesting message history');
                socket.emit('get_messages');
                socket.emit('get_contacts');
            }
        }
        
        // Display user info
        socket.on('user_info', (data) => {
            userInfoDiv.textContent = `Logged in as: ${data.client}`;
            if (data.recipient) {
                currentRecipient = data.recipient;
                updateSelectedContact();
            }
        });
        
        // Handle contact list
        socket.on('contact_list', (contacts) => {
            console.log('Received contacts:', contacts);
            
            // Clear the contact list
            contactList.innerHTML = '';
            
            // Check if we have any contacts
            if (contacts.length === 0) {
                noContactsMessage.style.display = 'block';
            } else {
                noContactsMessage.style.display = 'none';
                
                // Add each contact to the list
                contacts.forEach(contact => {
                    const li = document.createElement('li');
                    li.className = 'contact-item';
                    li.textContent = contact;
                    li.setAttribute('data-email', contact);
                    
                    // Add click handler to set as current recipient
                    li.addEventListener('click', () => {
                        setCurrentRecipient(contact);
                    });
                    
                    // Add a badge for unread messages (initially hidden)
                    const badge = document.createElement('span');
                    badge.className = 'unread-badge';
                    badge.style.display = 'none';
                    li.appendChild(badge);
                    
                    contactList.appendChild(li);
                });
            }
            
            // Update selected contact
            updateSelectedContact();
            
            // Show/hide no recipient message
            if (!currentRecipient && contacts.length > 0) {
                // Auto-select first contact if none is selected
                setCurrentRecipient(contacts[0]);
            } else if (!currentRecipient) {
                noConversationMessage.style.display = 'block';
            } else {
                noConversationMessage.style.display = 'none';
            }
        });
        
        // Function to set the current recipient
        function setCurrentRecipient(recipient) {
            if (recipient === currentRecipient) return;
            
            currentRecipient = recipient;
            currentConversationId = null; // Reset conversation when changing recipient
            console.log('Set current recipient:', currentRecipient);
            
            // Reset UI elements
            conversationTitle.textContent = '';
            chatBox.innerHTML = '';
            
            // Tell the server about the change
            socket.emit('set_recipient', { recipient });
            
            // Update the UI to show the correct contact as selected
            updateSelectedContact();
            
            // Show the conversation selector
            noConversationMessage.style.display = 'block';
            
            // Hide the input area until a conversation is selected
            document.querySelector('.input-area').style.display = 'none';
        }
        
        // Update which contact is highlighted in the list
        function updateSelectedContact() {
            // Remove active class from all contacts
            document.querySelectorAll('.contact-item').forEach(item => {
                item.classList.remove('active');
            });
            
            // Add active class to current recipient
            if (currentRecipient) {
                const contactItem = document.querySelector(`.contact-item[data-email="${currentRecipient}"]`);
                if (contactItem) {
                    contactItem.classList.add('active');
                }
            }
        }
        
        // Socket.IO events for conversations
        socket.on('conversation_list', (conversations) => {
            // Show the conversations panel
            conversationsPanel.style.display = 'flex';
            
            // Clear the list
            conversationList.innerHTML = '';
            
            // Check if we have any conversations
            if (conversations.length === 0) {
                noConversationsMessage.style.display = 'block';
            } else {
                noConversationsMessage.style.display = 'none';
                
                // Add each conversation to the list
                conversations.forEach(conv => {
                    const li = document.createElement('li');
                    li.className = 'conversation-item';
                    li.setAttribute('data-id', conv.id);
                    
                    const titleElement = document.createElement('div');
                    titleElement.className = 'conversation-item-title';
                    titleElement.textContent = conv.title;
                    
                    const previewElement = document.createElement('div');
                    previewElement.className = 'conversation-item-preview';
                    previewElement.textContent = conv.preview || 'No messages yet';
                    
                    const detailsElement = document.createElement('div');
                    detailsElement.className = 'conversation-item-details';
                    const dateStr = new Date(conv.created_at).toLocaleDateString();
                    detailsElement.textContent = `${dateStr} · ${conv.message_count} messages`;
                    
                    li.appendChild(titleElement);
                    li.appendChild(previewElement);
                    li.appendChild(detailsElement);
                    
                    // Add click handler to set as current conversation
                    li.addEventListener('click', () => {
                        setCurrentConversation(conv.id);
                    });
                    
                    conversationList.appendChild(li);
                });
            }
            
            // Hide the no conversation message if we have selected a contact
            if (currentRecipient) {
                noConversationMessage.style.display = 'block';
            }
        });
        
        // Function to set the current conversation
        function setCurrentConversation(conversationId) {
            if (conversationId === currentConversationId && currentRecipient) return;
            
            currentConversationId = conversationId;
            console.log('Set current conversation:', currentConversationId);
            
            // Tell the server about the change
            socket.emit('set_conversation', { conversation_id: conversationId });
            
            // Update the UI to show the correct conversation as selected
            updateSelectedConversation();
            
            // Hide the no-conversation message
            noConversationMessage.style.display = 'none';
            
            // Show the input area
            document.querySelector('.input-area').style.display = 'flex';
        }
        
        // Update which conversation is highlighted in the list
        function updateSelectedConversation() {
            // Remove active class from all conversations
            document.querySelectorAll('.conversation-item').forEach(item => {
                item.classList.remove('active');
            });
            
            // Add active class to current conversation
            if (currentConversationId) {
                const conversationItem = document.querySelector(`.conversation-item[data-id="${currentConversationId}"]`);
                if (conversationItem) {
                    conversationItem.classList.add('active');
                    
                    // Update the conversation title in the header
                    const titleElement = conversationItem.querySelector('.conversation-item-title');
                    if (titleElement) {
                        conversationTitle.textContent = titleElement.textContent;
                    }
                }
            }
        }
        
        // New conversation button
        newConversationBtn.addEventListener('click', () => {
            if (!currentRecipient) {
                statusDiv.textContent = 'Select a contact first';
                return;
            }
            
            newConversationModal.style.display = 'block';
            conversationTitleInput.focus();
        });
        
        closeConversationModal.addEventListener('click', () => {
            newConversationModal.style.display = 'none';
        });
        
        window.addEventListener('click', (e) => {
            if (e.target === newConversationModal) {
                newConversationModal.style.display = 'none';
            }
        });
        
        confirmNewConversation.addEventListener('click', createNewConversation);
        
        conversationTitleInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                createNewConversation();
            }
        });
        
        function createNewConversation() {
            const title = conversationTitleInput.value.trim() || 'New Conversation';
            
            if (currentRecipient) {
                socket.emit('create_conversation', { title: title });
                newConversationModal.style.display = 'none';
                conversationTitleInput.value = '';
            } else {
                statusDiv.textContent = 'Select a contact first';
            }
        }
        
        // Send message (update to check for current conversation)
        function sendMessage() {
            const message = messageInput.value.trim();
            if (message && isConnected && currentRecipient && currentConversationId) {
                socket.emit('send_message', { message });
                messageInput.value = '';
                statusDiv.textContent = 'Sending...';
            } else if (!isConnected) {
                statusDiv.textContent = 'Cannot send: disconnected';
            } else if (!currentRecipient) {
                statusDiv.textContent = 'Select a contact first';
            } else if (!currentConversationId) {
                statusDiv.textContent = 'Select or create a conversation first';
            }
        }
        
        sendButton.addEventListener('click', sendMessage);
        
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
        
        // Manual refresh button
        refreshButton.addEventListener('click', () => {
            if (currentRecipient) {
                socket.emit('get_messages');
                statusDiv.textContent = 'Refreshing messages...';
            } else {
                statusDiv.textContent = 'No conversation selected';
            }
        });
        
        // Add Contact functionality
        const addContactBtn = document.getElementById('add-contact-btn');
        addContactBtn.addEventListener('click', () => {
            newConversationModal.style.display = 'block';
            conversationTitleInput.focus();
        });
        
        // ...existing event handlers...
    </script>
</body>
</html>
    """
    
    with open(template_path, 'w') as f:
        f.write(html_content)
    
    return template_path


def check_pending_messages():
    """Check and update the status of any pending messages after a restart."""
    logger.info("Checking pending messages after restart...")
    
    # Get the logged-in client
    client = client_info["client"]
    if not client:
        logger.error("Cannot check pending messages: not logged in")
        return
    
    pending_count = 0
    
    # Iterate through all conversations
    for recipient, convs in conversations.items():
        for conv_id, conv_data in convs.items():
            # Make sure we're accessing the messages list correctly
            messages = conv_data.get("messages", [])
            if not isinstance(messages, list):
                logger.error(f"Invalid messages format for {recipient}/{conv_id}: {type(messages)}")
                continue
                
            for msg in messages:
                if not isinstance(msg, dict):
                    logger.error(f"Invalid message format: {type(msg)}")
                    continue
                    
                if msg.get("is_self", False) and msg.get("status") in ["sending", "unknown"]:
                    pending_count += 1
                    
                    # Check if this message was actually delivered
                    msg_content = msg.get("content", "")
                    msg_id = msg.get("id", "")
                    timestamp_str = msg.get("timestamp", "")
                    
                    try:
                        # Try to parse the timestamp
                        if timestamp_str:
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        else:
                            timestamp = None
                        
                        logger.info(f"Verifying message to {recipient}: {msg_id}")
                        
                        # Only verify delivery - never resend to avoid duplicates
                        threading.Thread(
                            target=verify_message_delivery,
                            args=(recipient, msg.get("content"), msg_id, timestamp, conv_id)
                        ).start()
                    except Exception as e:
                        logger.error(f"Error checking message {msg_id}: {e}")
                        
                        # Keep the unknown status
                        if msg.get("status") != "unknown":
                            msg["status"] = "unknown"
                            
                            # Update UI if this is the current recipient and conversation
                            if recipient == client_info["recipient"] and conv_id == client_info["conversation_id"]:
                                socketio.emit('message_status_update', {
                                    "id": msg_id,
                                    "status": "unknown"
                                })
    
    if pending_count > 0:
        logger.info(f"Found {pending_count} pending messages to verify")
    else:
        logger.info("No pending messages found")
    
    # Save any status changes to disk
    chat_storage.save_conversations(conversations)


def verify_message_delivery(recipient, content, message_id, timestamp=None, conversation_id="default"):
    """Attempt to verify if a message was delivered after restart."""
    client = client_info["client"]
    if not client:
        return
    
    # Create a verification message
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    verification_msg = ChatMessage(
        content=f"__verify__{message_id}__",  # Special format for verification
        sender=client.email,
        ts=timestamp
    )
    
    try:
        # Send verification request to the recipient
        future = rpc.send(
            url=f"syft://{recipient}/api_data/automail/rpc/verify",
            body=verification_msg,
            expiry="10m",
            cache=False,
        )
        
        # Use a longer timeout for messages on slow networks
        response = future.wait(timeout=120)
        
        if response.status_code == 200:
            # Message was delivered - update status
            if recipient in conversations and conversation_id in conversations[recipient]:
                for msg in conversations[recipient][conversation_id].get("messages", []):
                    if isinstance(msg, dict) and msg.get("id") == message_id:
                        msg["status"] = "delivered"
                        break
            
            # Save to disk
            chat_storage.save_conversations(conversations)
            
            # Update UI if this is the current recipient and conversation
            if recipient == client_info["recipient"] and conversation_id == client_info["conversation_id"]:
                socketio.emit('message_status_update', {
                    "id": message_id,
                    "status": "delivered"
                })
                
            logger.debug(f"Verified message delivery for {message_id}")
        else:
            # Message delivery couldn't be verified - mark as unknown
            if recipient in conversations and conversation_id in conversations[recipient]:
                for msg in conversations[recipient][conversation_id].get("messages", []):
                    if isinstance(msg, dict) and msg.get("id") == message_id:
                        msg["status"] = "unknown"
                        break
            
            # Save to disk
            chat_storage.save_conversations(conversations)
            
            # Update UI
            if recipient == client_info["recipient"] and conversation_id == client_info["conversation_id"]:
                socketio.emit('message_status_update', {
                    "id": message_id,
                    "status": "unknown"
                })
    except Exception as e:
        logger.error(f"Error verifying message {message_id}: {e}")
        
        # Mark as unknown instead of failed since we can't be sure
        if recipient in conversations and conversation_id in conversations[recipient]:
            for msg in conversations[recipient][conversation_id].get("messages", []):
                if isinstance(msg, dict) and msg.get("id") == message_id:
                    msg["status"] = "unknown"
                    break
        
        # Save to disk
        chat_storage.save_conversations(conversations)
        
        # Update UI
        if recipient == client_info["recipient"] and conversation_id == client_info["conversation_id"]:
            socketio.emit('message_status_update', {
                "id": message_id,
                "status": "unknown"
            })


# Add a verification endpoint to check if messages were received
@box.on_request("/verify")
def handle_verification(message: ChatMessage, ctx: Request) -> ChatResponse:
    """Handle verification requests for message delivery."""
    # Extract the message ID from the verification message
    content = message.content
    if content.startswith("__verify__") and content.endswith("__"):
        message_id = content.replace("__verify__", "").replace("__", "")
        
        # Check if we have this message in any conversation
        sender = message.sender
        for recipient, convs in conversations.items():
            if recipient == sender:  # Check recipient matches sender
                for conv_id, conv_data in convs.items():
                    messages = conv_data.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, dict) and not msg.get("is_self", True) and msg.get("id") == message_id:
                            # We found the message - it was delivered
                            return ChatResponse(
                                status="verified",
                                ts=datetime.now(timezone.utc),
                                message_id=message_id
                            )
    
    # Message not found or invalid verification request
    return ChatResponse(
        status="not_found",
        ts=datetime.now(timezone.utc)
    )


def main():
    parser = argparse.ArgumentParser(description="Peer-to-peer chat client")
    parser.add_argument("recipient", help="Recipient's email address", nargs='?')
    parser.add_argument("--port", type=int, default=5000, help="Port for the web server")
    args = parser.parse_args()
    
    # Load the client
    client_info["client"] = Client.load()
    if args.recipient:
        client_info["recipient"] = args.recipient
    
    print(f"Logged in as: {client_info['client'].email}")
    
    # Load conversations from disk
    global conversations
    conversations = chat_storage.load_conversations()
    
    # Create the HTML template
    create_html_template()
    
    # Start the RPC server in the background
    start_server()
    time.sleep(1)  # Give the server a moment to start
    
    # Check for pending messages from previous sessions
    check_pending_messages()
    
    # Start the Flask server
    print(f"Starting web server on http://localhost:{args.port}")
    print("Open this URL in your browser to use the chat interface")
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False)


if __name__ == "__main__":
    main()
