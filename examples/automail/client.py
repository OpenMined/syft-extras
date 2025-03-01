from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


# Set up the event listener
box = SyftEvents("automail")
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Store client and recipient information
client_info = {"client": None, "recipient": None}
message_history = []


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
    
    # Handle timestamp formatting - might be string or datetime
    if isinstance(message.ts, datetime):
        time_str = message.ts.strftime('%H:%M:%S')
    else:
        # If ts is a string, just use it directly
        time_str = str(message.ts)
    
    # Format the message for the UI
    msg_data = {
        "sender": sender,
        "time": time_str,
        "content": message.content,
        "is_self": False
    }
    
    # Add to history and update UI
    message_history.append(msg_data)
    socketio.emit('new_message', msg_data)
    
    return ChatResponse(
        status="received",
        ts=datetime.now(timezone.utc),
    )


def send_message(recipient: str, content: str) -> None:
    """Send a chat message to another user."""
    client = client_info["client"]
    if not client:
        socketio.emit('status', {"message": "Not logged in"})
        return
    
    # Create the message
    message = ChatMessage(content=content, sender=client.email)
    
    # Generate a unique message ID to prevent duplicates
    message_id = f"{int(time.time())}-{hash(content) % 10000}"
    
    # Add to history immediately (optimistic UI update)
    msg_data = {
        "id": message_id,
        "sender": client.email,
        "time": datetime.now().strftime('%H:%M:%S'),
        "content": content,
        "is_self": True,
        "confirmed": False  # Mark as unconfirmed initially
    }
    message_history.append(msg_data)
    socketio.emit('new_message', msg_data)
    
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
            response = future.wait(timeout=30)
            response.raise_for_status()
            chat_response = response.model(ChatResponse)
            
            # Update message as confirmed
            for msg in message_history:
                if msg.get("id") == message_id:
                    msg["confirmed"] = True
                    break
            
            # Send confirmation to UI
            socketio.emit('new_message', {
                "id": message_id,
                "confirmed": True
            })
            
            socketio.emit('status', {"message": "Message delivered"})
            logger.debug(f"Message delivered: {chat_response.status}")
        except Exception as e:
            socketio.emit('status', {"message": f"Delivery status unknown: {str(e)}"})
            logger.error(f"Error sending message: {e}")
    
    # Start a thread to handle the send and confirmation
    threading.Thread(target=send_and_confirm).start()


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
def handle_connect():
    # Send the message history to newly connected clients
    socketio.emit('message_history', message_history)
    
    if client_info["client"] and client_info["recipient"]:
        socketio.emit('user_info', {
            "client": client_info["client"].email,
            "recipient": client_info["recipient"]
        })


@socketio.on('set_recipient')
def handle_set_recipient(data):
    recipient = data.get('recipient')
    if recipient:
        client_info["recipient"] = recipient
        socketio.emit('status', {"message": f"Now chatting with {recipient}"})


@socketio.on('send_message')
def handle_send_message(data):
    content = data.get('message')
    recipient = client_info["recipient"]
    
    if not content or not recipient:
        socketio.emit('status', {"message": "Message or recipient missing"})
        return
    
    # Send the message in a background thread to avoid blocking the Socket.IO event loop
    threading.Thread(target=send_message, args=(recipient, content)).start()


@socketio.on('heartbeat')
def handle_heartbeat():
    """Handle heartbeat messages to keep the connection alive."""
    return {'status': 'ok'}


@socketio.on('get_messages')
def handle_get_messages():
    """Send message history to the client on request."""
    socketio.emit('message_history', message_history)
    return {'status': 'sent'}


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
            max-width: 800px;
            margin: 20px auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: #4a69bd;
            color: white;
            padding: 15px;
            text-align: center;
        }
        .chat-box {
            height: 400px;
            overflow-y: auto;
            padding: 15px;
            background-color: #f9f9f9;
            border-bottom: 1px solid #ddd;
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
        }
        .setup-area {
            padding: 15px;
            border-bottom: 1px solid #ddd;
        }
        .setup-area input, .setup-area button {
            padding: 8px;
            margin-right: 5px;
        }
        .controls {
            display: flex;
            justify-content: space-between;
            padding: 5px 15px;
            background-color: #f3f3f3;
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Syft Chat</h2>
            <div id="user-info"></div>
        </div>
        
        <div class="setup-area" id="setup-area">
            <input type="text" id="recipient-input" placeholder="Recipient's email">
            <button id="set-recipient">Set Recipient</button>
        </div>
        
        <div class="controls">
            <div>
                <span class="connection-status" id="connection-indicator"></span>
                <span id="connection-text">Connecting...</span>
            </div>
            <button class="refresh-button" id="refresh-button">Refresh Messages</button>
        </div>
        
        <div class="chat-box" id="chat-box"></div>
        
        <div class="status" id="status"></div>
        
        <div class="input-area">
            <input type="text" class="message-input" id="message-input" placeholder="Type your message...">
            <button class="send-button" id="send-button">Send</button>
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
        const recipientInput = document.getElementById('recipient-input');
        const setRecipientButton = document.getElementById('set-recipient');
        const userInfoDiv = document.getElementById('user-info');
        const setupArea = document.getElementById('setup-area');
        const refreshButton = document.getElementById('refresh-button');
        const connectionIndicator = document.getElementById('connection-indicator');
        const connectionText = document.getElementById('connection-text');
        
        // Connection status tracking
        let isConnected = false;
        
        // Connection event handlers
        socket.on('connect', () => {
            console.log('Socket connected');
            isConnected = true;
            connectionIndicator.className = 'connection-status connected';
            connectionText.textContent = 'Connected';
            statusDiv.textContent = 'Connected to server';
            
            // Request latest messages after connection
            requestMessages();
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
        
        socket.on('reconnect_failed', () => {
            console.log('Failed to reconnect');
            connectionIndicator.className = 'connection-status disconnected';
            connectionText.textContent = 'Reconnection failed';
            statusDiv.textContent = 'Failed to reconnect. Please refresh the page.';
        });
        
        socket.on('error', (error) => {
            console.error('Socket error:', error);
            statusDiv.textContent = 'Connection error';
        });
        
        // Function to request message history
        function requestMessages() {
            if (isConnected) {
                console.log('Requesting message history');
                socket.emit('get_messages');
            }
        }
        
        // Manual refresh button
        refreshButton.addEventListener('click', () => {
            requestMessages();
            statusDiv.textContent = 'Refreshing messages...';
        });
        
        // Display user info
        socket.on('user_info', (data) => {
            userInfoDiv.textContent = `Logged in as: ${data.client} | Chatting with: ${data.recipient}`;
            if (data.recipient) {
                setupArea.style.display = 'none';
            }
        });
        
        // Load message history
        socket.on('message_history', (messages) => {
            console.log(`Received message history: ${messages.length} messages`);
            chatBox.innerHTML = '';
            messages.forEach(message => {
                addMessageToChat(message);
            });
            scrollToBottom();
            statusDiv.textContent = `Loaded ${messages.length} messages`;
        });
        
        // Receive new messages
        socket.on('new_message', (message) => {
            console.log('Received new message:', message);
            
            // If this is a message confirmation update
            if (message.id && message.confirmed && !message.content) {
                const messageElements = document.querySelectorAll(`.message[data-id="${message.id}"]`);
                messageElements.forEach(el => {
                    el.classList.add('confirmed');
                });
                return;
            }
            
            addMessageToChat(message);
            scrollToBottom();
            
            // Play sound or flash title for notification
            notifyNewMessage();
        });
        
        // Update status
        socket.on('status', (data) => {
            statusDiv.textContent = data.message;
            setTimeout(() => {
                statusDiv.textContent = '';
            }, 3000);
        });
        
        // Set recipient
        setRecipientButton.addEventListener('click', () => {
            const recipient = recipientInput.value.trim();
            if (recipient) {
                socket.emit('set_recipient', { recipient });
                userInfoDiv.textContent = `Chatting with: ${recipient}`;
                setupArea.style.display = 'none';
            }
        });
        
        // Send message
        function sendMessage() {
            const message = messageInput.value.trim();
            if (message && isConnected) {
                socket.emit('send_message', { message });
                messageInput.value = '';
                statusDiv.textContent = 'Sending...';
            } else if (!isConnected) {
                statusDiv.textContent = 'Cannot send: disconnected';
            }
        }
        
        sendButton.addEventListener('click', sendMessage);
        
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
        
        function addMessageToChat(message) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${message.is_self ? 'self' : 'other'}`;
            if (message.id) {
                messageDiv.setAttribute('data-id', message.id);
                if (message.confirmed) {
                    messageDiv.classList.add('confirmed');
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
        
        function notifyNewMessage() {
            // You could add sound or browser notifications here
            // For example:
            // if (Notification.permission === "granted") {
            //     new Notification("New Message");
            // }
            
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
