from __future__ import annotations

import argparse as arg_parser
import threading
import time
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List

from loguru import logger
from pydantic import BaseModel, Field
from syft_core import Client
from syft_rpc import rpc
from syft_event import SyftEvents
from syft_event.types import Request

# Check for flask dependencies
try:
    from flask import Flask, render_template, request, jsonify, redirect, url_for
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
    from flask import Flask, render_template, request, jsonify, redirect, url_for
    from flask_cors import CORS


# Define message models
@dataclass
class ChatMessage:
    content: str
    sender: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            "content": self.content,
            "sender": self.sender,
            "ts": self.ts.isoformat()
        }


class ChatResponse(BaseModel):
    status: str
    ts: datetime


# Class to handle chat functionality
class ChatClient:
    def __init__(self, config_path=None, recipient=None):
        self.client = Client.load(config_path)
        self.recipient = recipient
        self.running = True
        self.message_history = []
        self.message_lock = threading.Lock()
        
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
            
            # Format and store the message
            formatted_message = {
                "content": message.content,
                "sender": message.sender,
                "timestamp": timestamp.isoformat(),
                "is_self": False
            }
            
            with self.message_lock:
                self.message_history.append(formatted_message)
            
            logger.info(f"Received message from {message.sender}: {message.content}")
            
            return ChatResponse(
                status="delivered",
                ts=datetime.now(timezone.utc)
            )
    
    def send_message(self, content):
        """Send a message to the recipient"""
        if not content:
            return
        
        # Store message in history first
        timestamp = datetime.now(timezone.utc)
        formatted_message = {
            "content": content,
            "sender": self.client.email,
            "timestamp": timestamp.isoformat(),
            "is_self": True
        }
        
        with self.message_lock:
            self.message_history.append(formatted_message)
            
        try:
            future = rpc.send(
                url=f"syft://{self.recipient}/api_data/chat/rpc/message",
                body=ChatMessage(
                    content=content,
                    sender=self.client.email
                ),
                expiry="5m",
                cache=True,
                client=self.client
            )
            
            # Wait for response but don't block UI
            def wait_for_response():
                try:
                    response = future.wait(timeout=30)
                    if response.status_code != 200:
                        logger.error(f"Failed to deliver message: {response.status_code}")
                except Exception as e:
                    logger.error(f"Error sending message: {e}")
                    
            threading.Thread(target=wait_for_response, daemon=True).start()
            
        except Exception as e:
            logger.error(f"Error preparing message: {e}")
    
    def run_server(self):
        """Run the server to receive messages"""
        try:
            logger.info(f"Listening for messages as {self.client.email}")
            self.box.run_forever()
        except Exception as e:
            logger.error(f"Server error: {e}")
            self.running = False
    
    def get_messages(self):
        """Get all messages in the history"""
        with self.message_lock:
            return self.message_history.copy()
    
    def change_recipient(self, new_recipient):
        """Change the chat recipient"""
        self.recipient = new_recipient
        # Add system message
        timestamp = datetime.now(timezone.utc)
        system_message = {
            "content": f"Now chatting with {new_recipient}",
            "sender": "System",
            "timestamp": timestamp.isoformat(),
            "is_self": False
        }
        with self.message_lock:
            self.message_history.append(system_message)
        return True


# Flask web application
def create_flask_app(chat_client):
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes
    
    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create a simple HTML template file
    template_path = os.path.join(templates_dir, 'chat.html')
    if not os.path.exists(template_path):
        with open(template_path, 'w') as f:
            f.write("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syft Chat</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f4f7f9;
        }
        .container {
            max-width: 800px;
            margin: 20px auto;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            height: calc(100vh - 40px);
            background-color: white;
        }
        .header {
            background-color: #4a90e2;
            color: white;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .recipient-info {
            display: flex;
            align-items: center;
        }
        .recipient-info h2 {
            margin: 0;
            font-size: 18px;
        }
        .user-info {
            font-size: 12px;
            opacity: 0.9;
        }
        .chat-messages {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
        }
        .message {
            margin-bottom: 15px;
            display: flex;
            flex-direction: column;
        }
        .message-content {
            max-width: 70%;
            padding: 10px 15px;
            border-radius: 18px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            position: relative;
        }
        .message.self {
            align-items: flex-end;
        }
        .message.other {
            align-items: flex-start;
        }
        .message.system {
            align-items: center;
        }
        .message.self .message-content {
            background-color: #4a90e2;
            color: white;
            border-bottom-right-radius: 5px;
        }
        .message.other .message-content {
            background-color: #e5e5ea;
            color: black;
            border-bottom-left-radius: 5px;
        }
        .message.system .message-content {
            background-color: #f0f0f0;
            color: #666;
            font-style: italic;
            padding: 8px 12px;
            border-radius: 10px;
            font-size: 0.9em;
            max-width: 100%;
            text-align: center;
        }
        .message-meta {
            font-size: 12px;
            margin-top: 5px;
            opacity: 0.7;
        }
        .message-form {
            display: flex;
            padding: 15px;
            border-top: 1px solid #e6e6e6;
            background-color: white;
        }
        .message-input {
            flex: 1;
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 20px;
            outline: none;
            margin-right: 10px;
        }
        .send-button {
            background-color: #4a90e2;
            color: white;
            border: none;
            border-radius: 20px;
            padding: 10px 20px;
            cursor: pointer;
            font-weight: bold;
        }
        .change-recipient {
            background-color: transparent;
            color: white;
            border: 1px solid white;
            border-radius: 15px;
            padding: 5px 10px;
            font-size: 12px;
            cursor: pointer;
        }
        .system-timestamp {
            font-size: 11px;
            color: #999;
            margin-top: 3px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="recipient-info">
                <h2>Chat with <span id="recipient-name">{{ recipient }}</span></h2>
            </div>
            <div class="user-info">
                Connected as {{ user_email }}
                <button class="change-recipient" onclick="changeRecipient()">Change Recipient</button>
            </div>
        </div>
        <div id="chat-messages" class="chat-messages">
            <!-- Messages will be populated here -->
        </div>
        <div class="message-form">
            <input type="text" id="message-input" class="message-input" placeholder="Type a message...">
            <button id="send-button" class="send-button">Send</button>
        </div>
    </div>

    <script>
        // Send a message
        document.getElementById('send-button').addEventListener('click', sendMessage);
        document.getElementById('message-input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });

        function sendMessage() {
            const messageInput = document.getElementById('message-input');
            const message = messageInput.value.trim();
            
            if (message) {
                fetch('/send', {
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
                    }
                })
                .catch(error => {
                    console.error('Error sending message:', error);
                });
            }
        }

        // Change recipient
        function changeRecipient() {
            const newRecipient = prompt("Enter new recipient's email address:");
            if (newRecipient) {
                fetch('/change_recipient', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ recipient: newRecipient }),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        document.getElementById('recipient-name').textContent = newRecipient;
                        refreshMessages();
                    }
                })
                .catch(error => {
                    console.error('Error changing recipient:', error);
                });
            }
        }

        // Format timestamp
        function formatTimestamp(isoString) {
            const date = new Date(isoString);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        // Refresh messages
        function refreshMessages() {
            fetch('/messages')
                .then(response => response.json())
                .then(data => {
                    const messagesContainer = document.getElementById('chat-messages');
                    
                    // Clear existing content for simplicity
                    messagesContainer.innerHTML = '';
                    
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
                        messagesContainer.appendChild(messageEl);
                    });
                    
                    // Scroll to bottom
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                })
                .catch(error => {
                    console.error('Error fetching messages:', error);
                });
        }

        // Initially load messages and set up periodic refresh
        refreshMessages();
        setInterval(refreshMessages, 2000);  // Poll every 2 seconds
    </script>
</body>
</html>
            """)
    
    @app.route('/')
    def index():
        return render_template('chat.html', 
                              recipient=chat_client.recipient, 
                              user_email=chat_client.client.email)
    
    @app.route('/messages')
    def get_messages():
        messages = chat_client.get_messages()
        return jsonify({"messages": messages})
    
    @app.route('/send', methods=['POST'])
    def send_message():
        data = request.json
        message = data.get('message', '')
        
        if message:
            chat_client.send_message(message)
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Empty message"})
    
    @app.route('/change_recipient', methods=['POST'])
    def change_recipient():
        data = request.json
        new_recipient = data.get('recipient', '')
        
        if new_recipient:
            chat_client.change_recipient(new_recipient)
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Invalid recipient"})
    
    return app


def run_flask(app, host='127.0.0.1', port=5000):
    """Run Flask in a separate thread"""
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Parse command line arguments
    parser = arg_parser.ArgumentParser(description="P2P Chat Client")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--recipient", "-r",
        type=str,
        required=False,
        help="Email address of the chat recipient"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=5000,
        help="Port for the web interface (default: 5000)"
    )
    args = parser.parse_args()
    
    print(f"Using config: {args.config if args.config else 'default'}")
    
    # If recipient not provided as argument, ask for it
    recipient = args.recipient
    if not recipient:
        recipient = input("Enter recipient's email address: ")
        
    # Create and start the chat client
    chat_client = ChatClient(config_path=args.config, recipient=recipient)
    
    # Start the message receiver in a separate thread
    server_thread = threading.Thread(target=chat_client.run_server, daemon=True)
    server_thread.start()
    
    # Create and run the Flask app
    app = create_flask_app(chat_client)
    
    print(f"Starting web interface at http://127.0.0.1:{args.port}")
    print(f"Chat session started. You ({chat_client.client.email}) -> {chat_client.recipient}")
    
    # Run Flask app (this will block until the server is stopped)
    run_flask(app, port=args.port)
