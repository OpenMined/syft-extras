from __future__ import annotations

import argparse as arg_parser
import threading
import time
import json
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Set

from loguru import logger
from pydantic import BaseModel, Field
from syft_core import Client
from syft_rpc import rpc
from syft_event import SyftEvents
from syft_event.types import Request

# Check for flask dependencies
try:
    from flask import Flask, render_template, request, jsonify, redirect, url_for, session
    try:
        from flask_cors import CORS
    except ImportError:
        print("flask_cors not found. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask-cors"])
        from flask_cors import CORS
except ImportError:
    print("Flask not found. Installing Flask and flask-cors...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "flask-cors"])
    from flask import Flask, render_template, request, jsonify, redirect, url_for, session
    from flask_cors import CORS


# Define message models
@dataclass
class ChatMessage:
    content: str
    sender: str
    conversation_id: str
    conversation_name: str = None
    all_participants: List[str] = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            "content": self.content,
            "sender": self.sender,
            "conversation_id": self.conversation_id,
            "conversation_name": self.conversation_name,
            "all_participants": self.all_participants,
            "ts": self.ts.isoformat()
        }


class ChatResponse(BaseModel):
    status: str
    ts: datetime


class Conversation:
    def __init__(self, id: str, name: str, recipients: List[str], created_by: str):
        self.id = id  # Unique identifier
        self.name = name
        self.recipients = recipients
        self.created_by = created_by
        self.created_at = datetime.now(timezone.utc)
        self.messages = []
        self.message_lock = threading.Lock()
        
    def add_message(self, message: dict):
        """Add a message to the conversation"""
        with self.message_lock:
            self.messages.append(message)
            
    def get_messages(self):
        """Get all messages in the conversation"""
        with self.message_lock:
            return self.messages.copy()
    
    def to_dict(self):
        """Convert conversation metadata to dict for API"""
        return {
            "id": self.id,
            "name": self.name,
            "recipients": self.recipients,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "message_count": len(self.messages)
        }


# Class to handle chat functionality
class ChatClient:
    def __init__(self, config_path=None):
        self.client = Client.load(config_path)
        self.running = True
        self.conversations = {}  # Dictionary of conversation_id -> Conversation
        self.conversation_lock = threading.Lock()
        
        # Set up event handler for receiving messages
        self.box = SyftEvents("chat", client=self.client)
        
        @self.box.on_request("/message")
        def handle_message(message: ChatMessage, ctx: Request) -> ChatResponse:
            """Handle incoming chat messages"""
            # Fix timestamp handling - check if ts is a string and convert if needed
            timestamp = message.ts
            if isinstance(timestamp, str):
                try:
                    # Try to parse the string to datetime
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except ValueError:
                    # Fallback to current time if parsing fails
                    timestamp = datetime.now(timezone.utc)
            
            # Format message
            formatted_message = {
                "content": message.content,
                "sender": message.sender,
                "timestamp": timestamp.isoformat(),
                "is_self": False,
                "conversation_id": message.conversation_id
            }
            
            # Find or create conversation
            conversation_id = message.conversation_id
            with self.conversation_lock:
                if conversation_id not in self.conversations:
                    # Use the conversation name from the message if provided, otherwise use default
                    conversation_name = message.conversation_name or f"Chat with {message.sender}"
                    
                    # Get participants list
                    participants = []
                    if message.all_participants:
                        # Use participants list from message
                        participants = message.all_participants
                        # Make sure sender is included if somehow missing
                        if message.sender not in participants:
                            participants.append(message.sender)
                        # Make sure self is included
                        if self.client.email not in participants:
                            participants.append(self.client.email)
                    else:
                        # Fallback to just the sender
                        participants = [message.sender]
                    
                    # Filter out self from recipients (we don't send messages to ourselves)
                    recipients = [p for p in participants if p != self.client.email]
                    
                    # This is a new conversation initiated by someone else
                    self.conversations[conversation_id] = Conversation(
                        id=conversation_id,
                        name=conversation_name,
                        recipients=recipients,
                        created_by=message.sender
                    )
                
                # Add message to conversation
                self.conversations[conversation_id].add_message(formatted_message)
            
            logger.info(f"Received message from {message.sender} in conversation {conversation_id}: {message.content}")
            
            return ChatResponse(
                status="delivered",
                ts=datetime.now(timezone.utc)
            )
    
    def create_conversation(self, name: str, recipients: List[str]) -> str:
        """Create a new conversation with one or more recipients"""
        conversation_id = str(uuid.uuid4())
        
        # Make sure current user is not in recipients (we don't send to ourselves)
        clean_recipients = [r for r in recipients if r != self.client.email]
        
        # Create a list of all participants (including self)
        all_participants = clean_recipients.copy()
        all_participants.append(self.client.email)
        
        # Update the name to include participants list if user didn't provide a custom name
        display_name = name
        if not name or name.strip() == "":
            # Create a default name based on participants (limit to 3 for brevity)
            if len(clean_recipients) <= 3:
                display_name = f"Chat with {', '.join(clean_recipients)}"
            else:
                display_name = f"Chat with {', '.join(clean_recipients[:3])} and {len(clean_recipients) - 3} others"
        
        with self.conversation_lock:
            self.conversations[conversation_id] = Conversation(
                id=conversation_id,
                name=display_name,
                recipients=clean_recipients,
                created_by=self.client.email
            )
            
            # Add system message about conversation creation
            timestamp = datetime.now(timezone.utc)
            system_message = {
                "content": f"Conversation created with: {', '.join(clean_recipients)}",
                "sender": "System",
                "timestamp": timestamp.isoformat(),
                "is_self": False,
                "conversation_id": conversation_id
            }
            self.conversations[conversation_id].add_message(system_message)
        
        # Send system notification to all recipients about this new conversation
        creation_message = f"New conversation '{display_name}' created by {self.client.email}"
        
        # Send to each recipient
        for recipient in clean_recipients:
            try:
                future = rpc.send(
                    url=f"syft://{recipient}/api_data/chat/rpc/message",
                    body=ChatMessage(
                        content=creation_message,
                        sender="System",  # Marking as system message
                        conversation_id=conversation_id,
                        conversation_name=display_name,
                        all_participants=all_participants
                    ),
                    expiry="5m",
                    cache=True,
                    client=self.client
                )
                
                # Wait for response but don't block UI
                def wait_for_response(recipient_email):
                    try:
                        response = future.wait(timeout=30)
                        if response.status_code != 200:
                            logger.error(f"Failed to deliver system notification to {recipient_email}: {response.status_code}")
                    except Exception as e:
                        logger.error(f"Error sending system notification to {recipient_email}: {e}")
                        
                threading.Thread(target=wait_for_response, args=(recipient,), daemon=True).start()
                
            except Exception as e:
                logger.error(f"Error preparing system notification to {recipient}: {e}")
            
        return conversation_id
    
    def get_conversation(self, conversation_id: str) -> Conversation:
        """Get a conversation by ID"""
        with self.conversation_lock:
            return self.conversations.get(conversation_id)
    
    def get_all_conversations(self) -> List[dict]:
        """Get all conversations metadata"""
        with self.conversation_lock:
            return [conv.to_dict() for conv in self.conversations.values()]
    
    def send_message(self, conversation_id: str, content: str):
        """Send a message to all recipients in a conversation"""
        if not content or not conversation_id:
            return False
        
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return False
        
        # Store message in conversation history first
        timestamp = datetime.now(timezone.utc)
        formatted_message = {
            "content": content,
            "sender": self.client.email,
            "timestamp": timestamp.isoformat(),
            "is_self": True,
            "conversation_id": conversation_id
        }
        
        conversation.add_message(formatted_message)
            
        # Create a full list of all participants (including self)
        all_participants = conversation.recipients.copy()
        all_participants.append(self.client.email)
        
        # Send message to each recipient
        for recipient in conversation.recipients:
            try:
                future = rpc.send(
                    url=f"syft://{recipient}/api_data/chat/rpc/message",
                    body=ChatMessage(
                        content=content,
                        sender=self.client.email,
                        conversation_id=conversation_id,
                        conversation_name=conversation.name,
                        all_participants=all_participants  # Include all participants in the message
                    ),
                    expiry="5m",
                    cache=True,
                    client=self.client
                )
                
                # Wait for response but don't block UI
                def wait_for_response(recipient_email):
                    try:
                        response = future.wait(timeout=30)
                        if response.status_code != 200:
                            logger.error(f"Failed to deliver message to {recipient_email}: {response.status_code}")
                    except Exception as e:
                        logger.error(f"Error sending message to {recipient_email}: {e}")
                        
                threading.Thread(target=wait_for_response, args=(recipient,), daemon=True).start()
                
            except Exception as e:
                logger.error(f"Error preparing message to {recipient}: {e}")
        
        return True
    
    def run_server(self):
        """Run the server to receive messages"""
        try:
            logger.info(f"Listening for messages as {self.client.email}")
            self.box.run_forever()
        except Exception as e:
            logger.error(f"Server error: {e}")
            self.running = False


# Flask web application
def create_flask_app(chat_client):
    app = Flask(__name__)
    app.secret_key = os.urandom(24)  # For session management
    CORS(app)  # Enable CORS for all routes
    
    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create HTML templates
    create_html_templates(templates_dir)
    
    @app.route('/')
    def index():
        return render_template('index.html', user_email=chat_client.client.email)
    
    # Direct conversation route now just serves the same index page
    # Client-side JavaScript will handle showing the right conversation
    @app.route('/conversation/<conversation_id>')
    def view_conversation(conversation_id):
        return render_template('index.html', user_email=chat_client.client.email)
    
    @app.route('/conversations')
    def get_conversations():
        conversations = chat_client.get_all_conversations()
        return jsonify({"conversations": conversations})
    
    @app.route('/conversation/<conversation_id>/messages')
    def get_messages(conversation_id):
        conversation = chat_client.get_conversation(conversation_id)
        if not conversation:
            return jsonify({"messages": []})
            
        messages = conversation.get_messages()
        return jsonify({"messages": messages})
    
    @app.route('/conversation/<conversation_id>/send', methods=['POST'])
    def send_message(conversation_id):
        data = request.json
        message = data.get('message', '')
        
        if message and chat_client.send_message(conversation_id, message):
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Failed to send message"})
    
    @app.route('/create_conversation', methods=['POST'])
    def create_conversation():
        data = request.json
        name = data.get('name', '')
        recipients = data.get('recipients', [])
        
        if not name or not recipients:
            return jsonify({"status": "error", "message": "Name and recipients are required"})
        
        # Split recipients by comma if provided as a single string
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.split(',') if r.strip()]
        
        try:
            conversation_id = chat_client.create_conversation(name, recipients)
            return jsonify({
                "status": "success", 
                "conversation_id": conversation_id
            })
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return jsonify({"status": "error", "message": str(e)})
    
    return app


def create_html_templates(templates_dir):
    """Create HTML templates for the web interface with modern dark mode design"""
    
    # Create index.html (main application view with sidebar)
    index_path = os.path.join(templates_dir, 'index.html')
    if not os.path.exists(index_path):
        with open(index_path, 'w') as f:
            f.write("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syft Chat</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-primary: #121212;
            --bg-secondary: #1e1e1e;
            --bg-tertiary: #252525;
            --bg-accent: #2d2d2d;
            --text-primary: #e0e0e0;
            --text-secondary: #a0a0a0;
            --text-muted: #6e6e6e;
            --accent-color: #7289da;
            --accent-hover: #5f73bc;
            --danger-color: #f04747;
            --success-color: #43b581;
            --border-color: #333333;
            --message-self: #3b4b8a;
            --message-other: #2f3136;
            --message-system: rgba(255, 255, 255, 0.05);
            --sidebar-width: 280px;
            --header-height: 60px;
            --input-height: 70px;
            --transition-speed: 0.2s;
            --border-radius: 8px;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            margin: 0;
            padding: 0;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        
        .app-container {
            display: flex;
            flex: 1;
            overflow: hidden;
            height: 100vh;
        }
        
        /* Sidebar Styles */
        .sidebar {
            width: var(--sidebar-width);
            background-color: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            border-right: 1px solid var(--border-color);
            transition: width var(--transition-speed);
        }
        
        .sidebar-header {
            height: var(--header-height);
            padding: 0 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
        }
        
        .sidebar-header h2 {
            font-size: 18px;
            font-weight: 600;
            color: var(--text-primary);
        }
        
        .new-chat-btn {
            background-color: var(--accent-color);
            color: white;
            border: none;
            padding: 8px 14px;
            border-radius: var(--border-radius);
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: background-color var(--transition-speed);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .new-chat-btn:hover {
            background-color: var(--accent-hover);
        }
        
        .new-chat-btn i {
            font-size: 12px;
        }
        
        .user-info {
            font-size: 12px;
            color: var(--text-secondary);
            padding: 12px 16px;
            background-color: var(--bg-tertiary);
            border-top: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .user-info i {
            color: var(--accent-color);
            font-size: 14px;
        }
        
        .conversation-list {
            flex: 1;
            overflow-y: auto;
            padding: 12px 0;
        }
        
        .conversation-list::-webkit-scrollbar {
            width: 6px;
        }
        
        .conversation-list::-webkit-scrollbar-thumb {
            background-color: var(--bg-accent);
            border-radius: 3px;
        }
        
        .conversation-list::-webkit-scrollbar-track {
            background-color: var(--bg-secondary);
        }
        
        .conversation-item {
            padding: 12px 16px;
            cursor: pointer;
            transition: background-color var(--transition-speed);
            border-radius: 4px;
            margin: 2px 8px;
        }
        
        .conversation-item:hover {
            background-color: var(--bg-accent);
        }
        
        .conversation-item.active {
            background-color: rgba(114, 137, 218, 0.15);
            border-left: 3px solid var(--accent-color);
        }
        
        .conversation-title {
            font-weight: 600;
            font-size: 15px;
            margin-bottom: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--text-primary);
        }
        
        .conversation-details {
            font-size: 12px;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .no-conversations {
            padding: 20px 16px;
            text-align: center;
            color: var(--text-muted);
            font-style: italic;
            font-size: 14px;
        }
        
        /* Main Content Styles */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            background-color: var(--bg-primary);
            position: relative;
        }
        
        .chat-header {
            height: var(--header-height);
            background-color: var(--bg-secondary);
            color: var(--text-primary);
            padding: 0 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            z-index: 10;
        }
        
        .chat-header h2 {
            font-size: 18px;
            font-weight: 600;
            margin: 0;
        }
        
        .chat-recipients {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }
        
        .chat-messages {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            background-color: var(--bg-primary);
            scroll-behavior: smooth;
        }
        
        .chat-messages::-webkit-scrollbar {
            width: 6px;
        }
        
        .chat-messages::-webkit-scrollbar-thumb {
            background-color: var(--bg-accent);
            border-radius: 3px;
        }
        
        .chat-messages::-webkit-scrollbar-track {
            background-color: var(--bg-primary);
        }
        
        .message {
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            max-width: 80%;
        }
        
        .message.self {
            align-items: flex-end;
            margin-left: auto;
        }
        
        .message.other {
            align-items: flex-start;
            margin-right: auto;
        }
        
        .message.system {
            align-items: center;
            max-width: 90%;
            margin: 10px auto;
        }
        
        .message-content {
            padding: 10px 15px;
            border-radius: 18px;
            position: relative;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
            word-break: break-word;
        }
        
        .message.self .message-content {
            background-color: var(--message-self);
            color: white;
            border-bottom-right-radius: 4px;
        }
        
        .message.other .message-content {
            background-color: var(--message-other);
            color: var(--text-primary);
            border-bottom-left-radius: 4px;
        }
        
        .message.system .message-content {
            background-color: var(--message-system);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 8px;
            font-style: italic;
            font-size: 13px;
            text-align: center;
        }
        
        .message-meta {
            font-size: 11px;
            margin-top: 4px;
            color: var(--text-secondary);
        }
        
        .system-timestamp {
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 3px;
        }
        
        .message-form {
            height: var(--input-height);
            display: flex;
            align-items: center;
            padding: 12px 16px;
            background-color: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
        }
        
        .message-input {
            flex: 1;
            padding: 12px 15px;
            background-color: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            outline: none;
            color: var(--text-primary);
            font-size: 14px;
            margin-right: 10px;
            transition: border-color var(--transition-speed);
        }
        
        .message-input:focus {
            border-color: var(--accent-color);
        }
        
        .send-button {
            background-color: var(--accent-color);
            color: white;
            border: none;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            transition: background-color var(--transition-speed);
        }
        
        .send-button:hover {
            background-color: var(--accent-hover);
        }
        
        .send-button i {
            font-size: 16px;
        }
        
        /* Welcome Screen */
        .welcome-screen {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            padding: 40px;
            background-color: var(--bg-primary);
            text-align: center;
        }
        
        .welcome-screen h2 {
            margin-top: 0;
            color: var(--text-primary);
            font-size: 24px;
            margin-bottom: 16px;
        }
        
        .welcome-screen p {
            color: var(--text-secondary);
            max-width: 600px;
            margin-bottom: 24px;
            line-height: 1.5;
        }
        
        .welcome-screen .new-chat-btn {
            padding: 10px 20px;
        }
        
        .welcome-icon {
            font-size: 64px;
            color: var(--accent-color);
            margin-bottom: 20px;
            opacity: 0.8;
        }
        
        /* Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        
        .modal-content {
            background-color: var(--bg-secondary);
            padding: 24px;
            border-radius: var(--border-radius);
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
            width: 100%;
            max-width: 500px;
            border: 1px solid var(--border-color);
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .modal-header h3 {
            margin: 0;
            color: var(--text-primary);
            font-size: 18px;
        }
        
        .close-modal {
            background: none;
            border: none;
            font-size: 18px;
            cursor: pointer;
            color: var(--text-secondary);
            transition: color var(--transition-speed);
        }
        
        .close-modal:hover {
            color: var(--text-primary);
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--text-primary);
        }
        
        .form-group input {
            width: 100%;
            padding: 12px;
            background-color: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: var(--border-radius);
            color: var(--text-primary);
            font-size: 14px;
            transition: border-color var(--transition-speed);
        }
        
        .form-group input:focus {
            outline: none;
            border-color: var(--accent-color);
        }
        
        .form-error {
            color: var(--danger-color);
            font-size: 12px;
            margin-top: 6px;
            display: none;
        }
        
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            margin-top: 24px;
            gap: 12px;
        }
        
        .modal-actions button {
            padding: 10px 16px;
            border-radius: var(--border-radius);
            cursor: pointer;
            font-weight: 500;
            transition: background-color var(--transition-speed);
        }
        
        .cancel-btn {
            background-color: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
        }
        
        .cancel-btn:hover {
            background-color: var(--bg-accent);
            color: var(--text-primary);
        }
        
        .create-btn {
            background-color: var(--accent-color);
            border: none;
            color: white;
        }
        
        .create-btn:hover {
            background-color: var(--accent-hover);
        }
        
        /* Responsive adjustments */
        @media screen and (max-width: 768px) {
            .sidebar {
                width: 240px;
            }
            
            .message {
                max-width: 90%;
            }
        }
        
        @media screen and (max-width: 576px) {
            .sidebar {
                width: 200px;
            }
            
            .new-chat-btn span {
                display: none;
            }
            
            .sidebar-header h2 {
                font-size: 16px;
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="sidebar">
            <div class="sidebar-header">
                <h2>Conversations</h2>
                <button id="new-chat-btn" class="new-chat-btn">
                    <i class="fas fa-plus"></i>
                    <span>New Chat</span>
                </button>
            </div>
            <div id="conversation-list" class="conversation-list">
                <!-- Conversations will be populated here -->
                <div class="no-conversations">No conversations yet</div>
            </div>
            <div class="user-info">
                <i class="fas fa-user-circle"></i>
                <span>{{ user_email }}</span>
            </div>
        </div>
        
        <div class="main-content">
            <div id="welcome-screen" class="welcome-screen">
                <div class="welcome-icon">
                    <i class="fas fa-comments"></i>
                </div>
                <h2>Welcome to Syft Chat</h2>
                <p>Select a conversation from the sidebar or create a new one to get started.</p>
                <button id="welcome-new-chat-btn" class="new-chat-btn">
                    <i class="fas fa-plus"></i>
                    <span>Create New Conversation</span>
                </button>
            </div>
            
            <div id="chat-interface" style="display: none; flex: 1; display: flex; flex-direction: column;">
                <div class="chat-header">
                    <div>
                        <h2 id="conversation-title">Conversation Title</h2>
                        <div id="conversation-recipients" class="chat-recipients">Recipients</div>
                    </div>
                </div>
                <div id="chat-messages" class="chat-messages">
                    <!-- Messages will be populated here -->
                </div>
                <div class="message-form">
                    <input type="text" id="message-input" class="message-input" placeholder="Type a message..." autocomplete="off">
                    <button id="send-button" class="send-button">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </div>
            </div>
        </div>
    </div>
    
    <div id="new-chat-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Create New Conversation</h3>
                <button class="close-modal" onclick="closeNewChatModal()">&times;</button>
            </div>
            <div class="form-group">
                <label for="conversation-name">Conversation Name</label>
                <input type="text" id="conversation-name" placeholder="Enter a name for this conversation">
            </div>
            <div class="form-group">
                <label for="recipients">Recipients</label>
                <input type="text" id="recipients" placeholder="Enter email addresses (comma separated)">
                <div id="recipients-error" class="form-error"></div>
            </div>
            <div class="modal-actions">
                <button class="cancel-btn" onclick="closeNewChatModal()">Cancel</button>
                <button id="create-conversation-btn" class="create-btn">Create Conversation</button>
            </div>
        </div>
    </div>

    <script>
        // Current active conversation
        let currentConversationId = null;
        let conversations = [];
        
        // DOM elements
        const conversationList = document.getElementById('conversation-list');
        const chatInterface = document.getElementById('chat-interface');
        const welcomeScreen = document.getElementById('welcome-screen');
        const chatMessages = document.getElementById('chat-messages');
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        const conversationTitle = document.getElementById('conversation-title');
        const conversationRecipients = document.getElementById('conversation-recipients');
        
        // Load all conversations
        function loadConversations() {
            fetch('/conversations')
                .then(response => response.json())
                .then(data => {
                    conversations = data.conversations;
                    
                    if (conversations.length === 0) {
                        conversationList.innerHTML = '<div class="no-conversations">No conversations yet</div>';
                        return;
                    }
                    
                    // Sort conversations by creation date (newest first)
                    conversations.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
                    
                    let html = '';
                    conversations.forEach(conv => {
                        const isActive = currentConversationId === conv.id ? 'active' : '';
                        html += `
                            <div class="conversation-item ${isActive}" data-id="${conv.id}" onclick="selectConversation('${conv.id}')">
                                <div class="conversation-title">${conv.name}</div>
                                <div class="conversation-details">
                                    ${conv.recipients.join(', ')}
                                </div>
                            </div>
                        `;
                    });
                    
                    conversationList.innerHTML = html;
                    
                    // If we have conversations but none is selected, select the first one
                    if (conversations.length > 0 && !currentConversationId) {
                        selectConversation(conversations[0].id);
                    }
                })
                .catch(error => {
                    console.error('Error loading conversations:', error);
                    conversationList.innerHTML = '<div class="no-conversations">Error loading conversations</div>';
                });
        }
        
        // Select and display a conversation
        function selectConversation(conversationId) {
            // Update UI to show active conversation
            document.querySelectorAll('.conversation-item').forEach(item => {
                item.classList.remove('active');
            });
            
            const selectedItem = document.querySelector(`.conversation-item[data-id="${conversationId}"]`);
            if (selectedItem) {
                selectedItem.classList.add('active');
            }
            
            currentConversationId = conversationId;
            
            // Find the conversation details
            const conversation = conversations.find(c => c.id === conversationId);
            if (conversation) {
                conversationTitle.textContent = conversation.name;
                conversationRecipients.textContent = 'With: ' + conversation.recipients.join(', ');
                
                // Update the page URL without navigating (for browser history)
                const newUrl = '/conversation/' + conversationId;
                history.pushState({conversationId}, '', newUrl);
            }
            
            // Show chat interface, hide welcome screen
            welcomeScreen.style.display = 'none';
            chatInterface.style.display = 'flex';
            
            // Load messages for this conversation
            refreshMessages();
            
            // Focus on input field
            messageInput.focus();
        }
        
        // Refresh messages for current conversation
        function refreshMessages() {
            if (!currentConversationId) return;
            
            fetch(`/conversation/${currentConversationId}/messages`)
                .then(response => response.json())
                .then(data => {
                    chatMessages.innerHTML = '';
                    
                    data.messages.forEach(msg => {
                        const messageEl = document.createElement('div');
                        if (msg.sender === 'System') {
                            messageEl.className = 'message system';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="system-timestamp">${formatTimestamp(msg.timestamp)}</div>
                            `;
                        } else if (msg.is_self) {
                            messageEl.className = 'message self';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="message-meta">${formatTimestamp(msg.timestamp)}</div>
                            `;
                        } else {
                            messageEl.className = 'message other';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="message-meta">${msg.sender} • ${formatTimestamp(msg.timestamp)}</div>
                            `;
                        }
                        chatMessages.appendChild(messageEl);
                    });
                    
                    // Scroll to bottom
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                })
                .catch(error => {
                    console.error('Error fetching messages:', error);
                });
        }
        
        // Send a message in the current conversation
        function sendMessage() {
            if (!currentConversationId) return;
            
            const message = messageInput.value.trim();
            if (!message) return;
            
            fetch(`/conversation/${currentConversationId}/send`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    messageInput.value = '';
                    refreshMessages();
                } else {
                    alert(data.message || 'Failed to send message');
                }
            })
            .catch(error => {
                console.error('Error sending message:', error);
                alert('Error sending message. Please try again.');
            });
        }
        
        // Modal functions
        function openNewChatModal() {
            document.getElementById('new-chat-modal').style.display = 'flex';
            document.getElementById('conversation-name').focus();
        }
        
        function closeNewChatModal() {
            document.getElementById('new-chat-modal').style.display = 'none';
            document.getElementById('conversation-name').value = '';
            document.getElementById('recipients').value = '';
            document.getElementById('recipients-error').style.display = 'none';
        }
        
        // Format timestamp
        function formatTimestamp(isoString) {
            const date = new Date(isoString);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        
        // Email validation helper
        function validateEmail(email) {
            const re = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
            return re.test(email);
        }
        
        // Handle browser back/forward navigation
        window.addEventListener('popstate', function(event) {
            if (event.state && event.state.conversationId) {
                selectConversation(event.state.conversationId);
            } else {
                // No state, probably at the root URL - show welcome screen
                welcomeScreen.style.display = 'flex';
                chatInterface.style.display = 'none';
                currentConversationId = null;
                
                // Clear active states in the sidebar
                document.querySelectorAll('.conversation-item').forEach(item => {
                    item.classList.remove('active');
                });
            }
        });
        
        // Event listeners
        document.getElementById('new-chat-btn').addEventListener('click', openNewChatModal);
        document.getElementById('welcome-new-chat-btn').addEventListener('click', openNewChatModal);
        
        sendButton.addEventListener('click', sendMessage);
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
        
        document.getElementById('create-conversation-btn').addEventListener('click', () => {
            const name = document.getElementById('conversation-name').value.trim();
            const recipientsText = document.getElementById('recipients').value.trim();
            const errorElement = document.getElementById('recipients-error');
            
            if (!name) {
                alert('Please enter a conversation name');
                return;
            }
            
            if (!recipientsText) {
                errorElement.textContent = 'Please enter at least one recipient';
                errorElement.style.display = 'block';
                return;
            }
            
            // Validate email format
            const recipients = recipientsText.split(',').map(email => email.trim());
            const invalidEmails = recipients.filter(email => !validateEmail(email));
            
            if (invalidEmails.length > 0) {
                errorElement.textContent = `Invalid email format: ${invalidEmails.join(', ')}`;
                errorElement.style.display = 'block';
                return;
            }
            
            errorElement.style.display = 'none';
            
            fetch('/create_conversation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    name: name,
                    recipients: recipients
                }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    closeNewChatModal();
                    // Update this whole section to avoid navigation
                    // Just reload the conversations and select the right one
                    loadConversations();
                    
                    // Set a small delay to ensure conversations are loaded before selecting
                    setTimeout(() => {
                        selectConversation(data.conversation_id);
                    }, 500);
                } else {
                    alert(data.message || 'Error creating conversation');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Failed to create conversation. Please try again.');
            });
        });
        
        // Check for conversation ID in URL on page load
        document.addEventListener('DOMContentLoaded', function() {
            const urlParts = window.location.pathname.split('/');
            if (urlParts.length >= 3 && urlParts[1] === 'conversation') {
                const conversationId = urlParts[2];
                // Load conversations first, then select the specific one
                loadConversations();
                
                // Set slight delay to ensure conversations are loaded
                setTimeout(() => {
                    selectConversation(conversationId);
                }, 300);
            } else {
                // Just load all conversations
                loadConversations();
            }
        });
        
        // Set up periodic refreshes
        setInterval(loadConversations, 10000);  // Refresh conversation list every 10 seconds
        setInterval(refreshMessages, 2000);     // Refresh messages every 2 seconds
    </script>
</body>
</html>
            """)
    
    # We no longer need the conversation.html template
    # Remove it if it exists to avoid confusion
    conversation_path = os.path.join(templates_dir, 'conversation.html')
    if os.path.exists(conversation_path):
        os.remove(conversation_path)


def run_flask(app, host='127.0.0.1', port=5000):
    """Run Flask in a separate thread"""
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Parse command line arguments
    parser = arg_parser.ArgumentParser(description="Multi-Conversation Chat Client")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=5000,
        help="Port for the web interface (default: 5000)"
    )
    args = parser.parse_args()
    
    print(f"Using config: {args.config if args.config else 'default'}")
    
    # Create and start the chat client
    chat_client = ChatClient(config_path=args.config)
    
    # Start the message receiver in a separate thread
    server_thread = threading.Thread(target=chat_client.run_server, daemon=True)
    server_thread.start()
    
    # Create and run the Flask app
    app = create_flask_app(chat_client)
    
    print(f"Starting web interface at http://127.0.0.1:{args.port}")
    print(f"Connected as {chat_client.client.email}")
    
    # Run Flask app (this will block until the server is stopped)
    run_flask(app, port=args.port)
