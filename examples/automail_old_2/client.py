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
import requests
from functools import lru_cache

# Try to import tkinter but don't fail if it's not available
has_tkinter = False
try:
    from tkinter import filedialog
    import tkinter as tk
    has_tkinter = True
except ImportError:
    # Tkinter is not available
    pass

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


input_path = input("Enter the path to the client config file: ")
client = Client.load(filepath=input_path)

# Set up the event listener
box = SyftEvents("automail", client=client)
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Store client and recipient information
client_info = {"client": None, "recipient": None}

# Store current config file path
client_config = {"path": None}

# Add global variable to track server thread
server_thread = None

# Update the ChatStorage class to be config-aware
class ChatStorage:
    """Handles persistent storage of conversations and contacts."""
    
    def __init__(self, client=None):
        """Initialize with optional client."""
        self.storage_dir = None
        self.conversations_file = None
        if client:
            self.update_storage_from_client(client)
        else:
            self.update_storage_location(None)
    
    def update_storage_from_client(self, client):
        """Update storage location based on the client's data directory."""
        if client and hasattr(client, 'config') and hasattr(client.config, 'data_dir'):
            # Get the data directory from the client's config
            data_dir = Path(client.config.data_dir)
            self.storage_dir = data_dir / "automail"
            logger.info(f"Using client's data directory for storage: {self.storage_dir}")
            
            # Create the directory if it doesn't exist
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            
            # Path to the conversations file
            self.conversations_file = self.storage_dir / "conversations.json"
            logger.info(f"Conversations will be stored at: {self.conversations_file}")
            return True
        else:
            # Fall back to using the config path method if client doesn't have proper config
            logger.warning("Client doesn't have proper config with data_dir, using config path instead")
            return False
    
    def update_storage_location(self, config_path=None):
        """Update the storage location based on the config path."""
        prev_storage_dir = self.storage_dir
        
        if config_path and Path(config_path).exists():
            try:
                # Try to load the config file to get the data directory
                with open(config_path, 'r') as f:
                    config_data = json.load(f)
                
                if 'data_dir' in config_data:
                    # Use the data directory from the config
                    data_dir = Path(config_data['data_dir'])
                    self.storage_dir = data_dir / "automail"
                    logger.info(f"Using data directory from config: {self.storage_dir}")
                else:
                    # No data directory in config, use a hash of the config path
                    path_hash = str(hash(str(Path(config_path).absolute())) % 10000)
                    self.storage_dir = Path.home() / ".syft" / f"automail_{path_hash}"
                    logger.info(f"No data directory in config, using hash: {self.storage_dir}")
            except (json.JSONDecodeError, IOError):
                # Can't read or parse the config, use a hash of the config path
                path_hash = str(hash(str(Path(config_path).absolute())) % 10000)
                self.storage_dir = Path.home() / ".syft" / f"automail_{path_hash}"
                logger.info(f"Error reading config, using hash: {self.storage_dir}")
        else:
            # Fallback to default location
            self.storage_dir = Path.home() / ".syft" / "automail"
            if prev_storage_dir != self.storage_dir:
                logger.info(f"Using default storage at: {self.storage_dir}")
        
        # Create the directory if it doesn't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Path to the conversations file
        self.conversations_file = self.storage_dir / "conversations.json"
        
        # Log the file path if it changed
        if prev_storage_dir != self.storage_dir:
            logger.info(f"Conversations will be stored at: {self.conversations_file}")
    
    def load_conversations(self):
        """Load conversations from disk."""
        if not self.conversations_file.exists():
            return {}
        
        try:
            with open(self.conversations_file, 'r') as f:
                data = json.load(f)
                
                # Convert timestamp strings back to datetime objects
                for recipient, messages in data.items():
                    for msg in messages:
                        if "timestamp" in msg:
                            try:
                                msg["ts_obj"] = datetime.fromisoformat(msg["timestamp"].replace('Z', '+00:00'))
                            except (ValueError, TypeError):
                                # If parsing fails, use a default timestamp
                                msg["ts_obj"] = datetime.now(timezone.utc)
                
                return data
        except Exception as e:
            logger.error(f"Error loading conversations: {e}")
            return {}
    
    def save_conversations(self, conversations):
        """Save conversations to disk."""
        try:
            # Create a serializable copy of the conversations
            serializable_data = {}
            
            for recipient, messages in conversations.items():
                serializable_data[recipient] = []
                for msg in messages:
                    # Create a copy to avoid modifying the original
                    serializable_msg = msg.copy()
                    # Remove the datetime object that can't be JSON serialized
                    if "ts_obj" in serializable_msg:
                        del serializable_msg["ts_obj"]
                    serializable_data[recipient].append(serializable_msg)
            
            # Write to file
            with open(self.conversations_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)
                
            logger.debug(f"Conversations saved to disk at {self.conversations_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving conversations: {e}")
            return False


# Initialize the storage with a dummy location - will be updated later
chat_storage = ChatStorage()

# Update the global conversations dict
conversations = {}


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
    
    # Format the message for the UI
    msg_data = {
        "id": message_id,
        "sender": sender,
        "time": time_str,
        "content": message.content,
        "is_self": False,
        "timestamp": timestamp.isoformat(),  # Store ISO format for sorting
        "ts_obj": timestamp,  # Store the actual datetime for sorting
        "status": "received"  # Mark as received immediately
    }
    
    # Add to the conversation with this sender
    add_message_to_conversation(sender, msg_data)
    
    # Update the UI if we're currently chatting with this sender
    if client_info["recipient"] == sender:
        socketio.emit('message_history', get_serializable_messages(sender))
    else:
        # Notify about unread message from another contact
        socketio.emit('unread_message', {
            "sender": sender
        })
    
    # Check if AI responses are enabled
    if ai_response_settings.get("enabled", False):
        # Generate and send an AI response
        threading.Thread(
            target=send_ai_response,
            args=(sender, message.content, message_id)
        ).start()
    
    # Send a response with the message ID for tracking
    return ChatResponse(
        status="received",
        ts=datetime.now(timezone.utc),
        message_id=message_id
    )


def add_message_to_conversation(recipient, msg_data):
    """Add a message to a specific conversation and save to disk."""
    # Initialize the conversation if it doesn't exist
    if recipient not in conversations:
        conversations[recipient] = []
    
    # Add the message to the conversation
    conversations[recipient].append(msg_data)
    
    # Sort messages by timestamp
    conversations[recipient].sort(key=lambda x: x.get("ts_obj", datetime.fromtimestamp(0, tz=timezone.utc)))
    
    # Save conversations to disk
    chat_storage.save_conversations(conversations)
    
    # Update UI only if this is the current recipient
    if recipient == client_info["recipient"]:
        socketio.emit('message_history', get_serializable_messages(recipient))


def get_serializable_messages(recipient=None):
    """Create a JSON-serializable copy of the message history for a recipient."""
    # Use the current recipient if none specified
    if recipient is None:
        recipient = client_info["recipient"]
    
    if not recipient or recipient not in conversations:
        return []
    
    # Create a serializable copy of the conversation
    serializable_history = []
    for msg in conversations[recipient]:
        # Create a copy to avoid modifying the original
        serializable_msg = msg.copy()
        # Remove the datetime object that can't be JSON serialized
        if "ts_obj" in serializable_msg:
            del serializable_msg["ts_obj"]
        serializable_history.append(serializable_msg)
    
    return serializable_history


@socketio.on('send_message')
def handle_send_message(data):
    content = data.get('message')
    recipient = client_info["recipient"]
    
    if not content or not recipient:
        socketio.emit('status', {"message": "Message or recipient missing"})
        return
    
    # Generate a message ID here for consistent optimistic updates
    client = client_info["client"]
    message_id = f"{int(time.time())}-{hash(content) % 10000}"
    timestamp = datetime.now(timezone.utc)
    
    # Send optimistic UI update immediately to sender
    msg_data = {
        "id": message_id,
        "sender": client.email,
        "time": timestamp.strftime('%H:%M:%S'),
        "content": content,
        "is_self": True,
        "status": "sending",  # Initial status
        "timestamp": timestamp.isoformat(),  # Store ISO format for sorting
        "ts_obj": timestamp  # Store the actual datetime for sorting
    }
    
    # Add to the conversation with this recipient
    add_message_to_conversation(recipient, msg_data)
    
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
            logger.debug(f"Sending message to {recipient} using client {client.email}")
            logger.debug(f"Using RPC path: {box.app_rpc_dir}")
            
            # Using the RPC framework directly, but with the current client's context
            future = rpc.send(
                url=f"syft://{recipient}/api_data/automail/rpc/message",
                body=message,
                expiry="10m",  # Increase timeout for slow networks
                cache=False,
                client=client
            )
            
            # Use a longer timeout for messages on slow networks
            response = future.wait(timeout=180)  # 3 minutes timeout
            
            response.raise_for_status()
            chat_response = response.model(ChatResponse)
            
            # Update message as delivered (server received)
            for msg in conversations[recipient]:
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
            for msg in conversations[recipient]:
                if msg.get("id") == message_id:
                    msg["status"] = "failed"
                    break
                    
            # Save the failure status to disk
            chat_storage.save_conversations(conversations)
            
            # Update status to failed in UI
            socketio.emit('message_status_update', {
                "id": message_id,
                "status": "failed",
                "error": str(e)
            })
            
            socketio.emit('status', {"message": f"Error sending message: {e}"})
            logger.error(f"Error sending message: {e}")
    
    # Start the sending thread
    threading.Thread(target=send_and_confirm).start()


def start_server(client=None):
    """Start the message server in a background thread with the right client config."""
    global box, server_thread
    
    # If there's an existing server thread, stop it
    if server_thread and server_thread.is_alive():
        logger.info("Stopping existing RPC server")
        try:
            box.stop()
            server_thread.join(timeout=2.0)  # Wait for it to stop
        except Exception as e:
            logger.error(f"Error stopping existing server: {e}")
    
    # Get the client if not provided
    if client is None and client_info.get("client") is not None:
        client = client_info["client"]
    
    # Log client info for debugging
    if client:
        logger.info(f"Starting server with client email: {client.email}")
        if hasattr(client, 'config') and hasattr(client.config, 'data_dir'):
            logger.info(f"Using data directory: {client.config.data_dir}")
    
    # Initialize the SyftEvents instance
    box = SyftEvents("automail")
    logger.info(f"Server RPC directory: {box.app_rpc_dir}")
    
    # Register the message handler - using the proper request handling
    @box.on_request("/message")
    def handle_message(req):
        """Receive and process incoming chat messages."""
        try:
            # Parse the message from the request body
            if hasattr(req, 'body'):
                # Extract the raw body data
                body_data = req.body
                
                # Create a ChatMessage directly with the body data
                if isinstance(body_data, dict):
                    message = ChatMessage(
                        content=body_data.get('content', ''),
                        sender=body_data.get('sender', ''),
                        ts=datetime.fromisoformat(body_data.get('ts')) if 'ts' in body_data else datetime.now(timezone.utc)
                    )
                elif isinstance(body_data, ChatMessage):
                    # If it's already a ChatMessage object, use it directly
                    message = body_data
                else:
                    raise ValueError(f"Unexpected message format: {type(body_data)}")
                
                # Process the received message
                logger.info(f"Received message from {message.sender}")
                
                # Store the message in the conversation history
                add_message_to_conversation(message.sender, {
                    "id": f"recv-{int(time.time())}-{hash(message.content) % 10000}",
                    "sender": message.sender,
                    "content": message.content,
                    "is_self": False,
                    "timestamp": message.ts.isoformat(),
                    "ts_obj": message.ts
                })
                
                # Notify the UI if this sender is the current recipient
                if message.sender == client_info["recipient"]:
                    socketio.emit('message_history', get_serializable_messages())
                else:
                    # Otherwise, notify that there's a new message
                    socketio.emit('new_message', {
                        "sender": message.sender,
                        "preview": message.content[:30] + "..." if len(message.content) > 30 else message.content
                    })
                
                # Play notification sound
                socketio.emit('play_notification')
                
                # Send desktop notification
                socketio.emit('desktop_notification', {
                    "title": f"Message from {message.sender}",
                    "body": message.content[:100] + "..." if len(message.content) > 100 else message.content
                })
                
                # Create a response
                response = ChatResponse(
                    status="received",
                    ts=datetime.now(timezone.utc),
                    message_id=f"recv-{int(time.time())}-{hash(message.content) % 10000}"
                )
                
                # Send back an automated AI response if enabled
                if ai_auto_respond and message.sender == client_info["recipient"]:
                    # Send the AI response in a separate thread
                    threading.Thread(
                        target=send_ai_response,
                        args=(message.sender, message.content)
                    ).start()
                
                return response
            else:
                # If the request doesn't have a body attribute, return an error
                logger.error("Request has no body")
                return ChatResponse(status="error", ts=datetime.now(timezone.utc))
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return ChatResponse(status="error", ts=datetime.now(timezone.utc))
    
    def run_server():
        try:
            logger.info(f"Starting chat server at {box.app_rpc_dir}")
            box.run_forever()
        except Exception as e:
            logger.error(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info("RPC server thread started")
    
    return True


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
            "config_path": client_config["path"] or "Default"  # Add config path info
        })
    
    # Send conversation history if there is a current recipient
    if client_info["recipient"]:
        socketio.emit('message_history', get_serializable_messages())


@socketio.on('set_recipient')
def handle_set_recipient(data):
    recipient = data.get('recipient')
    if recipient:
        client_info["recipient"] = recipient
        socketio.emit('status', {"message": f"Now chatting with {recipient}"})
        socketio.emit('message_history', get_serializable_messages(recipient))


@socketio.on('heartbeat')
def handle_heartbeat():
    """Handle heartbeat messages to keep the connection alive."""
    return {'status': 'ok'}


@socketio.on('get_messages')
def handle_get_messages():
    """Send message history to the client on request."""
    socketio.emit('message_history', get_serializable_messages())
    return {'status': 'sent'}


@socketio.on('get_contacts')
def handle_get_contacts():
    """Send the list of contacts to the client."""
    contacts = list(conversations.keys())
    socketio.emit('contact_list', contacts)


@socketio.on('add_contact')
def handle_add_contact(data):
    """Add a new contact and save to disk."""
    new_contact = data.get('contact')
    if new_contact and '@' in new_contact:
        # Initialize an empty conversation if it doesn't exist
        if new_contact not in conversations:
            conversations[new_contact] = []
            # Save the updated conversations to disk
            chat_storage.save_conversations(conversations)
        
        # Send updated contacts list
        socketio.emit('contact_list', list(conversations.keys()))
        
        # Switch to this contact
        client_info["recipient"] = new_contact
        socketio.emit('status', {"message": f"Added contact: {new_contact}"})
        socketio.emit('message_history', get_serializable_messages(new_contact))


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
            flex-direction: column; /* Make it a column layout */
        }
        .contacts-header {
            padding: 10px;
            background-color: #e6e6e6;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex: 0 0 auto; /* Don't grow or shrink */
        }
        .contact-list-container {
            flex: 1;
            overflow-y: auto; /* Allow this to scroll */
        }
        .add-contact-container {
            padding: 10px;
            border-top: 1px solid #ddd;
            background-color: #e6e6e6;
            flex: 0 0 auto; /* Don't grow or shrink */
        }
        .add-contact-btn {
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 8px 10px;
            cursor: pointer;
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .add-contact-btn:hover {
            background: #3a59ad;
        }
        .contact-list {
            list-style: none;
            padding: 0;
            margin: 0;
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
        .no-recipient {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #888;
            text-align: center;
            padding: 20px;
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
        
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        
        .close:hover,
        .close:focus {
            color: black;
            text-decoration: none;
        }
        
        .modal-input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        
        .modal-button {
            background-color: #4a69bd;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
            margin-top: 10px;
        }
        
        .modal-button:hover {
            background-color: #3a59ad;
        }
        
        /* Add toggle switch styles */
        .toggle-container {
            display: flex;
            align-items: center;
            margin-left: 15px;
        }
        
        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 40px;
            height: 20px;
            margin-right: 8px;
        }
        
        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        
        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 34px;
        }
        
        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 2px;
            bottom: 2px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        input:checked + .toggle-slider {
            background-color: #4CAF50;
        }
        
        input:checked + .toggle-slider:before {
            transform: translateX(20px);
        }
        
        .ai-toggle-label {
            font-size: 14px;
            color: white;
        }
        
        /* For the AI response messages */
        .ai-response {
            font-style: italic;
        }
        .ai-prefix {
            font-weight: bold;
            color: #4a69bd;
        }
        
        /* Add styles for the select config button */
        .config-button {
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            cursor: pointer;
            font-size: 12px;
            margin-left: 10px;
        }
        
        .config-button:hover {
            background: #3a59ad;
        }
        
        .config-info {
            font-size: 12px;
            color: #888;
            margin-left: 10px;
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h2>Syft Chat</h2>
                <div class="toggle-container">
                    <label class="toggle-switch">
                        <input type="checkbox" id="aiToggle">
                        <span class="toggle-slider"></span>
                    </label>
                    <span class="ai-toggle-label">Respond with AI</span>
                </div>
            </div>
        </div>
        <div class="main-area">
            <div class="contacts-panel">
                <div class="contacts-header">
                    <h3>Contacts</h3>
                </div>
                <div class="contact-list-container">
                    <ul class="contact-list" id="contactList">
                        <!-- Contacts will be added here dynamically -->
                    </ul>
                </div>
                <div class="add-contact-container">
                    <button class="add-contact-btn" id="addContactBtn">+ Add Contact</button>
                </div>
            </div>
            <div class="chat-panel">
                <div class="controls">
                    <div>
                        <span class="connection-status" id="connectionStatus"></span>
                        <span id="userInfo">Not connected</span>
                        <span class="config-info" id="configInfo"></span>
                    </div>
                    <div>
                        <button class="config-button" id="configButton">Change Account</button>
                        <button class="refresh-button" id="refreshButton">Refresh</button>
                    </div>
                </div>
                <div class="chat-box" id="chatBox">
                    <div class="no-recipient" id="noRecipientMessage">
                        <h3>Select a contact to start chatting</h3>
                        <p>Or add a new contact using the button on the left</p>
                    </div>
                    <!-- Messages will be added here dynamically -->
                </div>
                <div class="input-area">
                    <input type="text" class="message-input" id="messageInput" placeholder="Type a message...">
                    <button class="send-button" id="sendButton">Send</button>
                </div>
                <div class="status" id="status"></div>
            </div>
        </div>
    </div>
    
    <!-- Add Contact Modal -->
    <div id="addContactModal" class="modal">
        <div class="modal-content">
            <span class="close" id="closeModal">&times;</span>
            <h3>Add New Contact</h3>
            <input type="text" id="newContactInput" class="modal-input" placeholder="Enter email address">
            <button id="confirmAddContact" class="modal-button">Add</button>
        </div>
    </div>
    
    <!-- Config Path Modal -->
    <div id="configPathModal" class="modal">
        <div class="modal-content">
            <span class="close" id="closeConfigModal">&times;</span>
            <h3>Enter Config File Path</h3>
            <input type="text" id="configPathInput" class="modal-input" placeholder="Full path to config.json file">
            <button id="confirmConfigPath" class="modal-button">Load Config</button>
        </div>
    </div>

    <script>
        // DOM Elements
        const chatBox = document.getElementById('chatBox');
        const messageInput = document.getElementById('messageInput');
        const sendButton = document.getElementById('sendButton');
        const statusDiv = document.getElementById('status');
        const connectionStatus = document.getElementById('connectionStatus');
        const userInfoDiv = document.getElementById('userInfo');
        const contactList = document.getElementById('contactList');
        const addContactBtn = document.getElementById('addContactBtn');
        const addContactModal = document.getElementById('addContactModal');
        const newContactInput = document.getElementById('newContactInput');
        const closeModal = document.getElementById('closeModal');
        const confirmAddContact = document.getElementById('confirmAddContact');
        const refreshButton = document.getElementById('refreshButton');
        const noRecipientMessage = document.getElementById('noRecipientMessage');
        const configButton = document.getElementById('configButton');
        const configInfo = document.getElementById('configInfo');
        const configPathModal = document.getElementById('configPathModal');
        const configPathInput = document.getElementById('configPathInput');
        const closeConfigModal = document.getElementById('closeConfigModal');
        const confirmConfigPath = document.getElementById('confirmConfigPath');
        
        // Variables to track state
        let isConnected = false;
        let currentRecipient = null;
        let unreadCounts = {};
        
        // Connect to the Socket.IO server
        const socket = io();
        
        // Connection status
        socket.on('connect', () => {
            isConnected = true;
            connectionStatus.classList.add('connected');
            connectionStatus.classList.remove('disconnected', 'reconnecting');
            statusDiv.textContent = 'Connected';
        });
        
        socket.on('disconnect', () => {
            isConnected = false;
            connectionStatus.classList.add('disconnected');
            connectionStatus.classList.remove('connected', 'reconnecting');
            statusDiv.textContent = 'Disconnected';
        });
        
        socket.on('reconnecting', () => {
            connectionStatus.classList.add('reconnecting');
            connectionStatus.classList.remove('connected', 'disconnected');
            statusDiv.textContent = 'Reconnecting...';
        });
        
        // Receive user info
        socket.on('user_info', (data) => {
            console.log('User info:', data);
            userInfoDiv.textContent = `Logged in as: ${data.client}`;
            
            // Display config path if available
            if (data.config_path) {
                configInfo.textContent = `Config: ${data.config_path.split('/').pop()}`;
            } else {
                configInfo.textContent = 'Config: Default';
            }
            
            if (data.recipient) {
                currentRecipient = data.recipient;
                noRecipientMessage.style.display = 'none';
            } else {
                noRecipientMessage.style.display = 'flex';
            }
        });
        
        // Load contact list
        socket.on('contact_list', (contacts) => {
            console.log('Contacts:', contacts);
            contactList.innerHTML = '';
            
            contacts.forEach(contact => {
                const li = document.createElement('li');
                li.className = 'contact-item';
                li.textContent = contact;
                li.setAttribute('data-email', contact);
                
                if (contact === currentRecipient) {
                    li.classList.add('active');
                }
                
                li.addEventListener('click', () => {
                    setCurrentRecipient(contact);
                });
                
                contactList.appendChild(li);
            });
            
            if (contacts.length === 0) {
                const li = document.createElement('li');
                li.className = 'contact-item no-contacts';
                li.textContent = 'No contacts yet';
                li.style.cursor = 'default';
                li.style.fontStyle = 'italic';
                li.style.color = '#888';
                contactList.appendChild(li);
            }
        });
        
        // Load message history
        socket.on('message_history', (messages) => {
            console.log(`Received message history: ${messages.length} messages`);
            
            // Clear the chat box
            chatBox.innerHTML = '';
            
            // Add all messages in the order they were sorted on the server
            messages.forEach(message => {
                addMessageToChat(message);
            });
            
            scrollToBottom();
            statusDiv.textContent = `${messages.length} messages loaded`;
            
            // Hide the no-recipient message when we have a conversation
            if (currentRecipient) {
                noRecipientMessage.style.display = 'none';
            } else {
                noRecipientMessage.style.display = 'flex';
            }
        });
        
        // Handle message status updates
        socket.on('message_status_update', (data) => {
            console.log('Message status update:', data);
            const messageElements = document.querySelectorAll(`.message[data-id="${data.id}"]`);
            messageElements.forEach(el => {
                // Remove all status classes first
                el.classList.remove('status-sending', 'status-delivered', 'status-failed', 'status-unknown');
                // Add the new status class
                el.classList.add(`status-${data.status}`);
                
                // Update the status indicator element
                let statusElement = el.querySelector('.message-status');
                if (statusElement) {
                    updateStatusIndicator(statusElement, data.status);
                }
            });
        });
        
        // Handle notification of unread message
        socket.on('unread_message', (data) => {
            console.log('Unread message from:', data.sender);
            
            // Highlight the contact in the list or add it if not present
            const contactItem = document.querySelector(`.contact-item[data-email="${data.sender}"]`);
            if (contactItem) {
                contactItem.style.fontWeight = 'bold';
            } else {
                // Request updated contact list
                socket.emit('get_contacts');
            }
            
            // Notify the user if not the current conversation
            if (data.sender !== currentRecipient) {
                notifyNewMessage(data.sender);
            }
        });
        
        // Update status
        socket.on('status', (data) => {
            statusDiv.textContent = data.message;
            setTimeout(() => {
                statusDiv.textContent = '';
            }, 3000);
        });
        
        // Function to set the current recipient
        function setCurrentRecipient(recipient) {
            if (recipient === currentRecipient) return;
            
            currentRecipient = recipient;
            console.log('Set current recipient:', currentRecipient);
            
            // Tell the server about the change
            socket.emit('set_recipient', { recipient });
            
            // Update the UI to show the correct contact as selected
            document.querySelectorAll('.contact-item').forEach(item => {
                item.classList.remove('active');
                item.style.fontWeight = 'normal'; // Reset any unread styling
            });
            
            const contactItem = document.querySelector(`.contact-item[data-email="${recipient}"]`);
            if (contactItem) {
                contactItem.classList.add('active');
            }
            
            // Hide the no-recipient message
            noRecipientMessage.style.display = 'none';
            
            // Request the message history for this recipient
            socket.emit('get_messages');
        }
        
        // Send message
        function sendMessage() {
            const message = messageInput.value.trim();
            if (message && isConnected && currentRecipient) {
                socket.emit('send_message', { message });
                messageInput.value = '';
                statusDiv.textContent = 'Sending...';
            } else if (!isConnected) {
                statusDiv.textContent = 'Cannot send: disconnected';
            } else if (!currentRecipient) {
                statusDiv.textContent = 'Select a recipient first';
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
            socket.emit('get_contacts');
            if (currentRecipient) {
                socket.emit('get_messages');
                statusDiv.textContent = 'Refreshing...';
            } else {
                statusDiv.textContent = 'No conversation selected';
            }
        });
        
        // Add Contact Modal functionality
        addContactBtn.addEventListener('click', () => {
            addContactModal.style.display = 'block';
            newContactInput.focus();
        });
        
        closeModal.addEventListener('click', () => {
            addContactModal.style.display = 'none';
        });
        
        window.addEventListener('click', (e) => {
            if (e.target === addContactModal) {
                addContactModal.style.display = 'none';
            }
        });
        
        confirmAddContact.addEventListener('click', addNewContact);
        
        newContactInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                addNewContact();
            }
        });
        
        function addNewContact() {
            const contact = newContactInput.value.trim();
            if (contact) {
                socket.emit('add_contact', { contact });
                addContactModal.style.display = 'none';
                newContactInput.value = '';
            }
        }
        
        // Handle adding messages to the chat
        function updateStatusIndicator(element, status) {
            if (status === "sending") {
                element.textContent = "•";  // Gray dot instead of checkmark
                element.style.color = "#999";
                element.title = "Sending...";
            } else if (status === "delivered") {
                element.textContent = "✓";  // Single checkmark (easier to understand)
                element.style.color = "#4CAF50";
                element.title = "Delivered";
            } else if (status === "failed") {
                element.textContent = "⚠️";
                element.style.color = "#F44336";
                element.title = "Failed to send";
            } else if (status === "unknown") {
                element.textContent = "?";
                element.style.color = "#FFA500";  // Orange for unknown status
                element.title = "Delivery status unknown";
            } else {
                // Default/unknown status
                element.textContent = "";
            }
        }
        
        function addMessageToChat(message) {
            // Check if this message already exists in the chat
            const existingMsg = document.querySelector(`.message[data-id="${message.id}"]`);
            if (existingMsg) {
                // If it's a status update, just update the existing message
                if (message.status) {
                    existingMsg.classList.remove('status-sending', 'status-delivered', 'status-failed', 'status-unknown');
                    existingMsg.classList.add(`status-${message.status}`);
                    
                    // Update the status indicator
                    const statusElement = existingMsg.querySelector('.message-status');
                    if (statusElement) {
                        updateStatusIndicator(statusElement, message.status);
                    }
                }
                return;
            }
            
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${message.is_self ? 'self' : 'other'}`;
            if (message.id) {
                messageDiv.setAttribute('data-id', message.id);
                if (message.status) {
                    messageDiv.classList.add(`status-${message.status}`);
                }
            }
            
            const senderDiv = document.createElement('div');
            senderDiv.className = 'message-sender';
            senderDiv.textContent = message.sender;
            
            const contentDiv = document.createElement('div');
            
            // Check if this is an AI response (starts with [AI])
            if (message.content.startsWith('[AI]')) {
                contentDiv.classList.add('ai-response');
                
                // Create a span for the [AI] prefix
                const aiPrefix = document.createElement('span');
                aiPrefix.classList.add('ai-prefix');
                aiPrefix.textContent = '[AI] ';
                
                // Add the prefix
                contentDiv.appendChild(aiPrefix);
                
                // Add the rest of the message
                const textNode = document.createTextNode(message.content.substring(5));
                contentDiv.appendChild(textNode);
            } else {
                contentDiv.textContent = message.content;
            }
            
            const timeDiv = document.createElement('div');
            timeDiv.className = 'message-time';
            timeDiv.textContent = message.time;
            
            // Add status indicator for self messages
            if (message.is_self) {
                const statusElement = document.createElement('span');
                statusElement.className = 'message-status';
                
                // Set status indicator using the utility function
                updateStatusIndicator(statusElement, message.status);
                
                timeDiv.appendChild(statusElement);
            }
            
            messageDiv.appendChild(senderDiv);
            messageDiv.appendChild(contentDiv);
            messageDiv.appendChild(timeDiv);
            
            chatBox.appendChild(messageDiv);
            
            // Also add a div to clear the float
            const clearDiv = document.createElement('div');
            clearDiv.style.clear = 'both';
            chatBox.appendChild(clearDiv);
        }
        
        function scrollToBottom() {
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        
        function notifyNewMessage(sender) {
            // You could add sound or browser notifications here
            // For now, just flash the title
            let originalTitle = document.title;
            let interval = setInterval(() => {
                document.title = document.title === "New Message!" ? originalTitle : "New Message!";
            }, 1000);
            
            // Stop flashing after 5 seconds
            setTimeout(() => {
                clearInterval(interval);
                document.title = originalTitle;
            }, 5000);
        }
        
        // Implement heartbeat to keep connection alive
        setInterval(() => {
            if (isConnected) {
                socket.emit('heartbeat');
            }
        }, 30000); // Send heartbeat every 30 seconds
        
        // Add AI toggle handling
        const aiToggle = document.getElementById('aiToggle');
        
        // Load toggle state from localStorage if available
        if (localStorage.getItem('aiResponseEnabled') === 'true') {
            aiToggle.checked = true;
            // Notify the server about the initial state
            socket.emit('toggle_ai_response', { enabled: true });
        }
        
        // Handle toggle changes
        aiToggle.addEventListener('change', function() {
            const enabled = this.checked;
            
            // Save to localStorage
            localStorage.setItem('aiResponseEnabled', enabled);
            
            // Notify the server
            socket.emit('toggle_ai_response', { enabled });
            
            // Show status message
            statusDiv.textContent = `AI responses ${enabled ? 'enabled' : 'disabled'}`;
            setTimeout(() => {
                statusDiv.textContent = '';
            }, 3000);
        });
        
        // Config button functionality
        configButton.addEventListener('click', () => {
            if (isConnected) {
                // Show the config path input modal
                configPathModal.style.display = 'block';
                configPathInput.focus();
            } else {
                statusDiv.textContent = 'Cannot change config: disconnected';
            }
        });
        
        // Config modal event handlers
        closeConfigModal.addEventListener('click', () => {
            configPathModal.style.display = 'none';
        });
        
        window.addEventListener('click', (e) => {
            if (e.target === configPathModal) {
                configPathModal.style.display = 'none';
            }
        });
        
        confirmConfigPath.addEventListener('click', submitConfigPath);
        
        configPathInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                submitConfigPath();
            }
        });
        
        function submitConfigPath() {
            const path = configPathInput.value.trim();
            if (path) {
                socket.emit('config_path_input', { path });
                configPathModal.style.display = 'none';
                configPathInput.value = '';
                statusDiv.textContent = 'Loading config...';
            }
        }
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
    for recipient, messages in conversations.items():
        # Make sure messages is a list
        if not isinstance(messages, list):
            logger.error(f"Invalid message format for {recipient}: expected list, got {type(messages)}")
            continue
            
        # Find messages in "sending" or "unknown" state
        for msg in messages:
            # Check that msg is a dictionary before trying to access attributes
            if not isinstance(msg, dict):
                logger.error(f"Invalid message format for {recipient}: expected dict, got {type(msg)}")
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
                        args=(recipient, msg.get("content"), msg_id, timestamp)
                    ).start()
                except Exception as e:
                    logger.error(f"Error checking message {msg_id}: {e}")
                    
                    # Keep the unknown status
                    if msg.get("status") != "unknown":
                        msg["status"] = "unknown"
                        
                        # Update UI if this is the current recipient
                        if recipient == client_info["recipient"]:
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


def verify_message_delivery(recipient, content, message_id, timestamp=None):
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
            expiry="10m",  # Increase from 5m to 10m
            cache=False,
            client=client
        )
        
        # Use a longer timeout for messages on slow networks
        response = future.wait(timeout=120)  # Increase from 30 to 120 seconds for extra margin
        
        if response.status_code == 200:
            # Message was delivered - update status
            for msg in conversations[recipient]:
                if msg.get("id") == message_id:
                    msg["status"] = "delivered"
                    break
            
            # Save to disk
            chat_storage.save_conversations(conversations)
            
            # Update UI if this is the current recipient
            if recipient == client_info["recipient"]:
                socketio.emit('message_status_update', {
                    "id": message_id,
                    "status": "delivered"
                })
                
            logger.debug(f"Verified message delivery for {message_id}")
        else:
            # Message delivery couldn't be verified - mark as unknown
            for msg in conversations[recipient]:
                if msg.get("id") == message_id:
                    msg["status"] = "unknown"
                    break
            
            # Save to disk
            chat_storage.save_conversations(conversations)
            
            # Update UI
            if recipient == client_info["recipient"]:
                socketio.emit('message_status_update', {
                    "id": message_id,
                    "status": "unknown"
                })
    except Exception as e:
        logger.error(f"Error verifying message {message_id}: {e}")
        
        # Mark as unknown instead of failed since we can't be sure
        for msg in conversations[recipient]:
            if msg.get("id") == message_id:
                msg["status"] = "unknown"
                break
        
        # Save to disk
        chat_storage.save_conversations(conversations)
        
        # Update UI
        if recipient == client_info["recipient"]:
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
        for recipient, messages in conversations.items():
            if recipient == sender:
                for msg in messages:
                    if not msg.get("is_self", True) and msg.get("id") == message_id:
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


# Add this function to interact with Ollama
def generate_ai_response(prompt, sender=None):
    """Generate a response using Ollama with Llama 3.2."""
    try:
        # Call Ollama API (assuming it's running locally)
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.2:latest",  # Use llama3 model
                "prompt": f"You are a helpful assistant responding to an email from {sender}. Be concise but helpful.\n\nHere's the message: {prompt}\n\nYour response:",
                "stream": False
            },
            timeout=30  # 30 second timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "Sorry, I couldn't generate a response.")
        else:
            logger.error(f"Ollama API error: {response.status_code} - {response.text}")
            return "Sorry, there was an error generating a response."
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Ollama API. Make sure Ollama is running with 'llama3' model.")
        return "AI response unavailable. Make sure Ollama is running with the llama3 model."
    except Exception as e:
        logger.error(f"Error generating AI response: {e}")
        return "Sorry, an error occurred while generating a response."


# Store AI response settings
ai_response_settings = {"enabled": False}


@socketio.on('toggle_ai_response')
def handle_toggle_ai_response(data):
    """Handle toggling the AI response feature."""
    enabled = data.get('enabled', False)
    ai_response_settings["enabled"] = enabled
    logger.info(f"AI Response feature {'enabled' if enabled else 'disabled'}")
    return {"status": "success", "enabled": enabled}


def send_ai_response(recipient, prompt, in_reply_to=None):
    """Generate and send an AI response to a message."""
    try:
        # Generate AI response
        logger.info(f"Generating AI response to message from {recipient}")
        ai_response = generate_ai_response(prompt, recipient)
        
        # Send the response
        if ai_response:
            # Add a small delay to make the interaction feel more natural
            time.sleep(1.5)
            
            # Log that we're sending an AI response
            logger.info(f"Sending AI response to {recipient}")
            
            # Format the AI response
            content = f"[AI] {ai_response}"
            
            # Create message data for UI update - this mirrors what happens in handle_send_message
            client = client_info["client"]
            message_id = f"{int(time.time())}-{hash(content) % 10000}"
            timestamp = datetime.now(timezone.utc)
            
            # Create message data structure
            msg_data = {
                "id": message_id,
                "sender": client.email,
                "time": timestamp.strftime('%H:%M:%S'),
                "content": content,
                "is_self": True,
                "status": "sending",  # Initial status
                "timestamp": timestamp.isoformat(),
                "ts_obj": timestamp
            }
            
            # Add to the conversation history first so it appears in our UI
            add_message_to_conversation(recipient, msg_data)
            
            # Then send the message in background
            threading.Thread(target=send_message, args=(recipient, content, message_id, timestamp)).start()
    except Exception as e:
        logger.error(f"Error sending AI response: {e}")


# Function to load client from a config file
def load_client_from_config(config_path=None):
    """Load a client from the specified config file or use default location."""
    try:
        global client_info, client_config, conversations, chat_storage, box
        
        # If no path provided, use default
        if config_path is None:
            client = Client.load()
            client_config["path"] = None  # Mark as default
            logger.info("Loading client from default config")
        else:
            # Make sure we have a proper Path object
            if isinstance(config_path, str):
                # Expand tilde if present
                if config_path.startswith('~'):
                    config_path = os.path.expanduser(config_path)
                config_path = Path(config_path)
            
            # Check if file exists
            if not config_path.exists():
                error_msg = f"Config file not found: {config_path}"
                logger.error(error_msg)
                socketio.emit('status', {"message": error_msg})
                return None
                
            # Load from specific path
            logger.info(f"Loading client from config: {config_path}")
            client = Client.load(filepath=config_path)
            client_config["path"] = str(config_path)
        
        # Update the client info
        client_info["client"] = client
        logger.info(f"Loaded client: {client.email}")
        
        # Try to update storage from the client first
        if not chat_storage.update_storage_from_client(client):
            # If that fails, fall back to config path
            chat_storage.update_storage_location(client_config["path"])
        
        # Load conversations for this client
        conversations.clear()  # Clear old conversations first
        new_conversations = chat_storage.load_conversations()
        conversations.update(new_conversations)
        logger.info(f"Loaded {len(conversations)} conversations for {client.email}")
        
        # Restart the RPC server with the new client configuration
        logger.info("Restarting RPC server with new client configuration")
        start_server(client_info["client"])
        time.sleep(1)  # Give the server a moment to start
        
        # Notify UI of user change
        socketio.emit('user_info', {
            "client": client.email,
            "recipient": client_info["recipient"],
            "config_path": client_config["path"] or "Default"
        })
        
        return client
    except Exception as e:
        logger.error(f"Error loading client: {e}")
        socketio.emit('status', {"message": f"Error loading client: {e}"})
        return None


@socketio.on('config_path_input')
def handle_config_path_input(data):
    """Handle direct config path input from the UI."""
    try:
        file_path = data.get('path', '')
        logger.info(f"Received config path input: {file_path}")
        
        if file_path:
            # Expand the tilde in the path if it exists
            if file_path.startswith('~'):
                expanded_path = os.path.expanduser(file_path)
                logger.info(f"Expanded ~ to home directory: {expanded_path}")
                file_path = expanded_path
            
            # Convert to Path object and resolve it (get absolute path)
            config_path = Path(file_path).resolve()
            logger.info(f"Resolved path: {config_path}")
            
            # Check if file exists
            if not config_path.exists():
                error_msg = f"Config file not found: {config_path}"
                logger.error(error_msg)
                socketio.emit('status', {"message": error_msg})
                return
            
            # Attempt to load the client (this will also update conversation storage)
            old_client_email = client_info["client"].email if client_info["client"] else "None"
            logger.info(f"Attempting to switch from {old_client_email} to new client using config: {config_path}")
            
            client = load_client_from_config(config_path)
            if client:
                # Show success message with storage location
                success_msg = f"Switched to client: {client.email} (using storage: {chat_storage.storage_dir})"
                logger.info(success_msg)
                
                # Update the UI with new contacts
                socketio.emit('contact_list', list(conversations.keys()))
                
                # Clear current recipient
                client_info["recipient"] = None
                
                # Clear the chat box
                socketio.emit('message_history', [])
                socketio.emit('status', {"message": success_msg})
            else:
                error_msg = "Failed to load client from config"
                logger.error(error_msg)
                socketio.emit('status', {"message": error_msg})
        else:
            # Empty path
            logger.warning("No config path provided")
            socketio.emit('status', {"message": "No config path provided"})
    except Exception as e:
        error_msg = f"Error loading config from path: {e}"
        logger.error(error_msg)
        socketio.emit('status', {"message": error_msg})


def main():
    parser = argparse.ArgumentParser(description="Peer-to-peer chat client")
    parser.add_argument("recipient", help="Recipient's email address", nargs='?')
    parser.add_argument("--port", type=int, default=5000, help="Port for the web server")
    parser.add_argument("--config", help="Path to client config file", default=None)
    args = parser.parse_args()
    
    # Use globals explicitly
    global chat_storage, conversations, client_info
    
    # Initialize conversations dictionary
    conversations = {}
    
    # Initialize the config path
    config_path = args.config
    
    # Create chat storage - will be updated when client is loaded
    chat_storage = ChatStorage()
    
    # Load the client (this will also update the storage location)
    client = load_client_from_config(config_path)
    if not client:
        print("Failed to load client. Exiting.")
        sys.exit(1)
    
    # Set up client info        
    client_info["client"] = client
    
    if args.recipient:
        client_info["recipient"] = args.recipient
    
    print(f"Logged in as: {client_info['client'].email}")
    print(f"Using storage location: {chat_storage.storage_dir}")
    
    # Create the HTML template
    create_html_template()
    
    # Start the RPC server in the background with the loaded client
    start_server(client_info["client"])
    time.sleep(1)  # Give the server a moment to start
    
    # Check for pending messages from previous sessions
    check_pending_messages()
    
    # Start the Flask server
    print(f"Starting web server on http://localhost:{args.port}")
    print("Open this URL in your browser to use the chat interface")
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False)


if __name__ == "__main__":
    main()
