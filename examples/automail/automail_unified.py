from __future__ import annotations

import time
import threading
import json
import uuid
import requests
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import os
import queue

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from loguru import logger

# Initialize Flask and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'automail_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Create log directory if it doesn't exist
LOGS_DIR = Path("automail_logs")
LOGS_DIR.mkdir(exist_ok=True)
MESSAGE_LOG = LOGS_DIR / "message_log.json"
OVERRIDE_LOG = LOGS_DIR / "override_log.json"

# Track users and their status
active_users = {}  # username -> last_active_time
user_sessions = {}  # username -> session_id
pending_messages = defaultdict(list)  # recipient -> list of pending messages
conversation_history = defaultdict(list)  # conversation_id -> messages
message_store = {}  # message_id -> message_details

# Ollama API settings
OLLAMA_API_BASE = "http://localhost:11434/api"
OLLAMA_MODEL = "llama3.2"

# Constants
AI_RESPONSE_DELAY = 5  # seconds to wait before AI responds


def check_ollama():
    """Check if Ollama is running and return the available models."""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/tags")
        if response.status_code == 200:
            available_models = [model["name"] for model in response.json().get("models", [])]
            
            # Try to find a suitable model in this order of preference
            preferred_models = ["llama3.2", "llama3", "llama3:latest", "llama3.2:latest", 
                               "llama2", "mistral", "gemma"]
            
            for model in preferred_models:
                if model in available_models:
                    return model
                
            # If none of our preferred models are available, use the first one
            if available_models:
                return available_models[0]
    except:
        pass
    return None


def get_ai_response(message, conversation_id):
    """Get a response from the AI based on conversation history."""
    try:
        # Generate a unique message ID
        message_id = str(uuid.uuid4())
        
        # Get recent conversation history
        recent_messages = conversation_history[conversation_id][-20:]
        
        # Call Ollama API
        response = requests.post(
            f"{OLLAMA_API_BASE}/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": recent_messages,
                "stream": False
            }
        )
        
        if response.status_code == 200:
            ai_response = response.json()
            if "message" in ai_response and "content" in ai_response["message"]:
                response_text = ai_response["message"]["content"]
            else:
                response_text = "I couldn't generate a proper response. Could you try again?"
        else:
            response_text = "Sorry, there was an error generating a response."
    
    except Exception as e:
        logger.error(f"Error getting AI response: {e}")
        response_text = "Sorry, I'm having technical difficulties right now."
    
    return response_text, message_id


def log_message(sender, recipient, message, response=None, ai_generated=False):
    """Log the message for monitoring and history."""
    try:
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_id = str(uuid.uuid4())
        
        # Read existing log if it exists
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                except json.JSONDecodeError:
                    log_data = []
        else:
            log_data = []
        
        # Add new message entry
        entry = {
            "id": message_id,
            "from": sender,
            "to": recipient,
            "message": message,
            "timestamp": timestamp,
        }
        
        if response:
            entry["response"] = response
            entry["ai_generated"] = ai_generated
        
        log_data.append(entry)
        
        # Keep only last 100 messages
        if len(log_data) > 100:
            log_data = log_data[-100:]
        
        # Write back to file
        with open(MESSAGE_LOG, "w") as f:
            json.dump(log_data, f)
        
        return message_id
    except Exception as e:
        logger.error(f"Error logging message: {e}")
        return str(uuid.uuid4())


def schedule_ai_response(sender, recipient, message, message_id, delay=AI_RESPONSE_DELAY):
    """Schedule an AI response after a delay if no human response is received."""
    def send_ai_response():
        # Check if message still needs AI response
        if message_id in pending_messages[recipient]:
            # Get conversation ID (unique to this sender-recipient pair)
            conversation_id = f"{sender}_{recipient}"
            
            # Add user message to conversation history if not already there
            if not any(m.get("role") == "user" and m.get("content") == message 
                      for m in conversation_history[conversation_id]):
                conversation_history[conversation_id].append({
                    "role": "user",
                    "content": message
                })
            
            # Generate AI response
            response_text, resp_message_id = get_ai_response(message, conversation_id)
            
            # Add AI response to conversation history
            conversation_history[conversation_id].append({
                "role": "assistant",
                "content": response_text
            })
            
            # Store message details for future reference
            message_store[resp_message_id] = {
                "response": response_text,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "sender": recipient,  # AI is responding on behalf of recipient
                "recipient": sender,
                "original_message": message,
                "ai_generated": True
            }
            
            # Log the AI-generated response
            log_message(recipient, sender, message, response_text, ai_generated=True)
            
            # Remove from pending
            pending_messages[recipient].remove(message_id)
            
            # Send message to sender via Socket.IO
            if sender in user_sessions:
                socketio.emit('message', {
                    'sender': recipient,
                    'message': response_text,
                    'timestamp': datetime.now().strftime("%H:%M:%S"),
                    'ai_generated': True,
                    'message_id': resp_message_id
                }, room=user_sessions[sender])
    
    # Schedule the AI response
    threading.Timer(delay, send_ai_response).start()


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        if username:
            # Store username in session
            return redirect(url_for('chat', username=username))
    return render_template('login.html')


@app.route('/chat/<username>')
def chat(username):
    # Set user as active
    active_users[username] = datetime.now()
    return render_template('unified_chat.html', username=username, users=list(active_users.keys()))


@app.route('/monitor')
def monitor():
    """Monitoring interface to see and edit AI-generated messages."""
    return render_template('monitor.html')


@app.route('/messages')
def get_messages():
    """Get all messages from the log file."""
    try:
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    messages = json.load(f)
                    return jsonify(messages)
                except json.JSONDecodeError:
                    logger.error("Error reading message log")
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
    
    # Return empty list if no messages or error
    return jsonify([])


@app.route('/update_response', methods=['POST'])
def update_response():
    """Update an AI-generated response with a human correction."""
    data = request.json
    message_id = data.get('message_id')
    new_response = data.get('response')
    
    if not message_id or not new_response:
        return jsonify({"success": False, "error": "Missing message_id or response"})
    
    try:
        # Load existing overrides
        if OVERRIDE_LOG.exists():
            with open(OVERRIDE_LOG, "r") as f:
                try:
                    overrides = json.load(f)
                except json.JSONDecodeError:
                    overrides = {}
        else:
            overrides = {}
        
        # Add the new override
        overrides[message_id] = new_response
        
        # Save back to file
        with open(OVERRIDE_LOG, "w") as f:
            json.dump(overrides, f)
        
        # Update the message log
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        if entry.get("id") == message_id:
                            entry["response"] = new_response
                            entry["ai_generated"] = False  # Mark as human override
                            
                            # Notify the recipient of the update
                            if entry.get("to") in user_sessions:
                                socketio.emit('message_update', {
                                    'message_id': message_id,
                                    'new_text': new_response,
                                    'timestamp': datetime.now().strftime("%H:%M:%S"),
                                    'sender': entry.get("from")
                                }, room=user_sessions[entry.get("to")])
                    
                    with open(MESSAGE_LOG, "w") as f:
                        json.dump(log_data, f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Error updating message log: {e}")
                    return jsonify({"success": False, "error": f"Error updating log: {e}"})
        
        # If the message is in the conversation history, update it there too
        for conv_id, messages in conversation_history.items():
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("content") == message_store.get(message_id, {}).get("response"):
                    msg["content"] = new_response
                    break
        
        # Update our in-memory store
        if message_id in message_store:
            message_store[message_id]["response"] = new_response
            message_store[message_id]["ai_generated"] = False
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating response: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route('/generate_ai_response', methods=['POST'])
def generate_ai_response():
    """Generate an AI response locally using Ollama"""
    data = request.json
    sender = data.get('sender')
    message = data.get('message')
    recipient = data.get('recipient')
    
    if not sender or not message or not recipient:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Use conversation history for context if available
    conversation_id = f"{sender}_{recipient}"
    
    try:
        # Call local Ollama API
        response = requests.post(
            f"{OLLAMA_API_BASE}/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False
            }
        )
        
        if response.status_code == 200:
            ai_response = response.json()
            if "message" in ai_response and "content" in ai_response["message"]:
                response_text = ai_response["message"]["content"]
            else:
                response_text = "I couldn't generate a proper response. Could you try again?"
        else:
            response_text = "Sorry, there was an error generating a response."
    
    except Exception as e:
        logger.error(f"Error getting AI response: {e}")
        response_text = "Sorry, I'm having technical difficulties right now."
    
    return jsonify({"response": response_text})


@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")


@socketio.on('join')
def handle_join(data):
    username = data.get('username')
    if username:
        # Store user's session id
        user_sessions[username] = request.sid
        active_users[username] = datetime.now()
        
        # Join room with user's name
        join_room(username)
        
        # Get users list
        users = list(active_users.keys())
        
        # Notify everyone about the updated user list
        socketio.emit('user_list', {'users': users})
        
        # Send any pending messages for this user
        for msg_id in pending_messages.get(username, []):
            if msg_id in message_store:
                msg_data = message_store[msg_id]
                emit('message', {
                    'sender': msg_data['sender'],
                    'message': msg_data['original_message'],
                    'timestamp': msg_data['timestamp'],
                    'message_id': msg_id
                })


@socketio.on('disconnect')
def handle_disconnect():
    # Find and remove the disconnected user
    for username, sid in list(user_sessions.items()):
        if sid == request.sid:
            del user_sessions[username]
            break
    
    # Update user list
    socketio.emit('user_list', {'users': list(user_sessions.keys())})


@socketio.on('message')
def handle_message(data):
    sender = data.get('sender')
    recipient = data.get('recipient')
    message = data.get('message')
    
    if not sender or not recipient or not message:
        return
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    message_id = log_message(sender, recipient, message)
    
    # Store message details
    message_store[message_id] = {
        "sender": sender,
        "recipient": recipient,
        "original_message": message,
        "timestamp": timestamp,
    }
    
    # If recipient is online, send the message for them to respond
    if recipient in user_sessions:
        socketio.emit('message_needs_response', {
            'sender': sender,
            'message': message,
            'timestamp': timestamp,
            'message_id': message_id
        }, room=user_sessions[recipient])
    else:
        # Recipient is offline, we can't get a response from their client
        # We could either queue the message or use a fallback AI service
        pass


@socketio.on('ai_response')
def handle_ai_response(data):
    """Handle AI responses generated by client machines"""
    original_sender = data.get('original_sender')
    responder = data.get('responder')
    message = data.get('message')
    original_message_id = data.get('original_message_id')
    
    if not original_sender or not responder or not message:
        return
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    message_id = str(uuid.uuid4())
    
    # Log the AI-generated response
    log_message(responder, original_sender, message, ai_generated=True)
    
    # Store message details
    message_store[message_id] = {
        "response": message,
        "timestamp": timestamp,
        "sender": responder,
        "recipient": original_sender,
        "ai_generated": True
    }
    
    # Send to the original sender
    if original_sender in user_sessions:
        socketio.emit('message', {
            'sender': responder,
            'message': message,
            'timestamp': timestamp,
            'ai_generated': True,
            'message_id': message_id
        }, room=user_sessions[original_sender])


@socketio.on('human_response')
def handle_human_response(data):
    """Handle a human response that cancels the pending AI response."""
    message_id = data.get('message_id')
    recipient = data.get('recipient')
    
    # Remove from pending messages to cancel AI response
    if message_id in pending_messages.get(recipient, []):
        pending_messages[recipient].remove(message_id)


@socketio.on('check_updates')
def handle_check_updates(data):
    """Check for updates to AI-generated messages."""
    message_ids = data.get('message_ids', [])
    
    if not message_ids:
        return
    
    # Load existing overrides
    overrides = {}
    if OVERRIDE_LOG.exists():
        try:
            with open(OVERRIDE_LOG, "r") as f:
                overrides = json.load(f)
        except json.JSONDecodeError:
            pass
    
    # Filter updates to requested message IDs
    updates = {msg_id: overrides[msg_id] for msg_id in message_ids if msg_id in overrides}
    
    if updates:
        emit('message_updates', {'updates': updates})


@app.template_filter('formatted_time')
def format_time(timestamp):
    """Format timestamp for display."""
    if isinstance(timestamp, str):
        return timestamp
    return timestamp.strftime("%H:%M:%S")


# Start the background tasks
def cleanup_inactive_users():
    """Remove users who haven't been active for more than 10 minutes."""
    while True:
        now = datetime.now()
        for username, last_active in list(active_users.items()):
            # If inactive for more than 10 minutes
            if (now - last_active).total_seconds() > 600:
                if username in active_users:
                    del active_users[username]
                if username in user_sessions:
                    del user_sessions[username]
        
        # Update user list
        socketio.emit('user_list', {'users': list(user_sessions.keys())})
        time.sleep(60)  # Check every minute


if __name__ == '__main__':
    # Check if Ollama is available
    model = check_ollama()
    if model:
        OLLAMA_MODEL = model
        logger.info(f"Using Ollama model: {OLLAMA_MODEL}")
    else:
        logger.warning("Ollama not available. AI responses will be limited.")
    
    # Start background thread to clean up inactive users
    cleanup_thread = threading.Thread(target=cleanup_inactive_users, daemon=True)
    cleanup_thread.start()
    
    # Run the app
    socketio.run(app, debug=False, host='0.0.0.0', port=5002) 