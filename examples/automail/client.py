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

# Store client and recipient information
client_info = {"client": None, "recipient": None}

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
                
            logger.debug("Conversations saved to disk")
            return True
        except Exception as e:
            logger.error(f"Error saving conversations: {e}")
            return False


# Initialize the storage
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
            future = rpc.send(
                url=f"syft://{recipient}/api_data/automail/rpc/message",
                body=message,
                expiry="5m",
                cache=False,
            )
            
            # Use a shorter timeout for immediate feedback
            response = future.wait(timeout=120)
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
            # Update status to failed
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
            "recipient": client_info["recipient"]
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
        }
        .contacts-header {
            padding: 10px;
            background-color: #e6e6e6;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .add-contact-btn {
            background: #4a69bd;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 10px;
            cursor: pointer;
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
            font-size: 0.8em;
        }
        
        .status-sending::after {
            content: "✓";
            color: #999;
        }
        
        .status-delivered::after {
            content: "✓✓";
            color: #4CAF50;
        }
        
        .status-failed::after {
            content: "⚠️";
            color: #F44336;
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
        
        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
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
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Syft Chat</h2>
            <div id="user-info"></div>
        </div>
        
        <div class="controls">
            <div>
                <span class="connection-status" id="connection-indicator"></span>
                <span id="connection-text">Connecting...</span>
            </div>
            <button class="refresh-button" id="refresh-button">Refresh Messages</button>
        </div>
        
        <div class="main-area">
            <div class="contacts-panel">
                <div class="contacts-header">
                    <h3>Contacts</h3>
                    <button class="add-contact-btn" id="add-contact-btn">+</button>
                </div>
                <ul class="contact-list" id="contact-list">
                    <!-- Contacts will be populated here -->
                </ul>
            </div>
            
            <div class="chat-panel">
                <div class="chat-box" id="chat-box"></div>
                
                <div class="no-recipient-message" id="no-recipient-message">
                    <p>Select a contact to start chatting</p>
                    <p>or add a new contact with the + button</p>
                </div>
                
                <div class="status" id="status"></div>
                
                <div class="input-area">
                    <input type="text" class="message-input" id="message-input" placeholder="Type your message...">
                    <button class="send-button" id="send-button">Send</button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Add Contact Modal -->
    <div id="add-contact-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Add Contact</h3>
                <span class="close" id="close-modal">&times;</span>
            </div>
            <div class="modal-body">
                <input type="text" id="new-contact-input" class="modal-input" placeholder="Contact's email">
            </div>
            <div class="modal-footer">
                <button id="confirm-add-contact" class="modal-button">Add</button>
            </div>
        </div>
    </div>

    <script>
        const socket = io({
            reconnection: true,
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 20000
        });
        const chatBox = document.getElementById('chat-box');
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        const statusDiv = document.getElementById('status');
        const userInfoDiv = document.getElementById('user-info');
        const refreshButton = document.getElementById('refresh-button');
        const connectionIndicator = document.getElementById('connection-indicator');
        const connectionText = document.getElementById('connection-text');
        const contactList = document.getElementById('contact-list');
        const addContactBtn = document.getElementById('add-contact-btn');
        const addContactModal = document.getElementById('add-contact-modal');
        const closeModal = document.getElementById('close-modal');
        const newContactInput = document.getElementById('new-contact-input');
        const confirmAddContact = document.getElementById('confirm-add-contact');
        const noRecipientMessage = document.getElementById('no-recipient-message');
        
        // Track the current recipient
        let currentRecipient = null;
        
        // Connection status tracking
        let isConnected = false;
        
        // Connection event handlers
        socket.on('connect', () => {
            console.log('Socket connected');
            isConnected = true;
            connectionIndicator.className = 'connection-status connected';
            connectionText.textContent = 'Connected';
            statusDiv.textContent = 'Connected to server';
            
            // Request the contacts list
            socket.emit('get_contacts');
        });
        
        socket.on('disconnect', () => {
            console.log('Socket disconnected');
            isConnected = false;
            connectionIndicator.className = 'connection-status disconnected';
            connectionText.textContent = 'Disconnected';
            statusDiv.textContent = 'Disconnected from server';
        });
        
        socket.on('reconnecting', (attemptNumber) => {
            console.log(`Reconnection attempt: ${attemptNumber}`);
            connectionIndicator.className = 'connection-status reconnecting';
            connectionText.textContent = `Reconnecting (${attemptNumber})...`;
            statusDiv.textContent = 'Attempting to reconnect...';
        });
        
        // Display user info
        socket.on('user_info', (data) => {
            userInfoDiv.textContent = `Logged in as: ${data.client}`;
            if (data.recipient) {
                setCurrentRecipient(data.recipient);
            }
        });
        
        // Handle contact list
        socket.on('contact_list', (contacts) => {
            console.log('Received contacts:', contacts);
            
            // Clear the contact list
            contactList.innerHTML = '';
            
            // Add contacts to the list
            contacts.forEach(contact => {
                const li = document.createElement('li');
                li.className = 'contact-item';
                li.setAttribute('data-email', contact);
                li.textContent = contact;
                
                li.addEventListener('click', () => {
                    setCurrentRecipient(contact);
                });
                
                contactList.appendChild(li);
            });
            
            // Highlight current recipient if set
            if (currentRecipient) {
                updateSelectedContact();
            } else if (contacts.length === 0) {
                // Show message if no contacts
                noRecipientMessage.style.display = 'block';
            }
        });
        
        // Function to set the current recipient
        function setCurrentRecipient(recipient) {
            if (!recipient || recipient === currentRecipient) return;
            
            currentRecipient = recipient;
            console.log('Set current recipient:', currentRecipient);
            
            // Tell the server about the change
            socket.emit('set_recipient', { recipient });
            
            // Update the UI to show the correct contact as selected
            updateSelectedContact();
            
            // Hide the no-recipient message
            noRecipientMessage.style.display = 'none';
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
                noRecipientMessage.style.display = 'block';
            }
        });
        
        // Handle message status updates
        socket.on('message_status_update', (data) => {
            console.log('Message status update:', data);
            const messageElements = document.querySelectorAll(`.message[data-id="${data.id}"]`);
            messageElements.forEach(el => {
                // Remove all status classes first
                el.classList.remove('status-sending', 'status-delivered', 'status-failed');
                // Add the new status class
                el.classList.add(`status-${data.status}`);
                
                // Update the status indicator element
                let statusElement = el.querySelector('.message-status');
                if (!statusElement) {
                    statusElement = document.createElement('span');
                    statusElement.className = 'message-status';
                    el.querySelector('.message-time').appendChild(statusElement);
                }
                
                // Update text for status
                let statusText = "";
                if (data.status === "sending") statusText = "✓";
                else if (data.status === "delivered") statusText = "✓✓";
                else if (data.status === "failed") statusText = "⚠️";
                
                statusElement.textContent = statusText;
            });
        });
        
        // Update status
        socket.on('status', (data) => {
            statusDiv.textContent = data.message;
            setTimeout(() => {
                statusDiv.textContent = '';
            }, 3000);
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
            if (currentRecipient) {
                socket.emit('get_messages', { recipient: currentRecipient });
                statusDiv.textContent = 'Refreshing messages...';
            } else {
                statusDiv.textContent = 'No conversation selected';
            }
        });
        
        // Add Contact functionality
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
        
        function addMessageToChat(message) {
            // Check if this message already exists in the chat
            const existingMsg = document.querySelector(`.message[data-id="${message.id}"]`);
            if (existingMsg) {
                // If it's a status update, just update the existing message
                if (message.status) {
                    existingMsg.classList.remove('status-sending', 'status-delivered', 'status-failed');
                    existingMsg.classList.add(`status-${message.status}`);
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
            contentDiv.textContent = message.content;
            
            const timeDiv = document.createElement('div');
            timeDiv.className = 'message-time';
            timeDiv.textContent = message.time;
            
            // Add status indicator for self messages
            if (message.is_self) {
                const statusElement = document.createElement('span');
                statusElement.className = 'message-status';
                
                // Set initial status indicator
                let statusText = "";
                if (message.status === "sending") statusText = "✓";
                else if (message.status === "delivered") statusText = "✓✓";
                else if (message.status === "failed") statusText = "⚠️";
                
                statusElement.textContent = statusText;
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
    </script>
</body>
</html>
    """
    
    with open(template_path, 'w') as f:
        f.write(html_content)
    
    return template_path


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
    
    # Start the Flask server
    print(f"Starting web server on http://localhost:{args.port}")
    print("Open this URL in your browser to use the chat interface")
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False)


if __name__ == "__main__":
    main()
