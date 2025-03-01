from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import json
import uuid
from pathlib import Path
import threading
import requests
from collections import defaultdict

from flask import Flask, render_template, request, jsonify
from loguru import logger
from pydantic import BaseModel

app = Flask(__name__)

# Track message IDs and their updates
message_store = {}

# Track conversation history for each recipient
conversation_history = defaultdict(list)

@dataclass
class PingRequest:
    msg: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PongResponse(BaseModel):
    msg: str
    ts: datetime


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Print the application header."""
    print("=" * 50)
    print("AutoMail Chat")
    print("Type 'quit' as recipient to exit")
    print("Press Enter without recipient to message yourself")
    print("=" * 50)
    print()


def format_message(email: str, msg: str, ts: datetime, is_me: bool = False):
    """Format a chat message."""
    name = "You" if is_me else email.split('@')[0]
    timestamp = ts.strftime("%H:%M:%S")
    return f"[{timestamp}] {name}: {msg}"


@app.route('/')
def home():
    """Render the chat interface."""
    return render_template('chat.html', my_email="user@automail")


@app.route('/send', methods=['POST'])
def send_message():
    """Send a message to the AI server and get a response."""
    data = request.json
    recipient = data.get('recipient', 'default_chat')
    message = data.get('message')
    
    if not message:
        return jsonify({"success": False, "message": "Empty message"})
    
    try:
        # Create a unique ID for this message
        message_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        # Add user message to conversation history
        conversation_history[recipient].append({
            "role": "user",
            "content": message
        })
        
        # Get only the last 20 messages to avoid context length issues
        recent_history = conversation_history[recipient][-20:]
        
        try:
            # Use HTTP to contact the AI server directly
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "llama3.2",
                    "messages": recent_history,
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                ai_response = response.json()
                if "message" in ai_response and "content" in ai_response["message"]:
                    response_text = ai_response["message"]["content"]
                else:
                    response_text = "AI could not generate a response"
                
                # Add AI response to conversation history
                conversation_history[recipient].append({
                    "role": "assistant",
                    "content": response_text
                })
                
                # Store the message ID for future update checks
                message_store[message_id] = {
                    "response": response_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "checked": False,
                    "recipient": recipient
                }
                
                # Log the message to the message log
                try:
                    LOGS_DIR = Path("automail_logs")
                    LOGS_DIR.mkdir(exist_ok=True)
                    MESSAGE_LOG = LOGS_DIR / "message_log.json"
                    
                    if MESSAGE_LOG.exists():
                        with open(MESSAGE_LOG, "r") as f:
                            try:
                                log_data = json.load(f)
                            except json.JSONDecodeError:
                                log_data = []
                    else:
                        log_data = []
                        
                    log_data.append({
                        "id": message_id,
                        "from": recipient,
                        "message": message,
                        "response": response_text,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "ai_generated": True
                    })
                    
                    with open(MESSAGE_LOG, "w") as f:
                        json.dump(log_data, f)
                except Exception as e:
                    logger.error(f"Error logging message: {e}")
                
                return jsonify({
                    "success": True,
                    "message": response_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "msg_id": message_id
                })
            else:
                return jsonify({
                    "success": False,
                    "message": f"AI server error: {response.status_code}",
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })
        except Exception as e:
            logger.error(f"Error sending message via HTTP: {e}")
            return jsonify({
                "success": False,
                "message": f"Failed to send: {str(e)}",
                "timestamp": datetime.now().strftime("%H:%M:%S")
            })
            
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({
            "success": False,
            "message": f"Failed to send: {str(e)}",
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })


@app.route('/get_updates', methods=['POST'])
def get_updates():
    """Check for updates to previous responses."""
    data = request.json
    message_ids = data.get('message_ids', [])
    
    if not message_ids:
        return jsonify({"updates": {}})
    
    try:
        # Get updates from the message log
        updates = {}
        
        # Get the message log
        LOGS_DIR = Path("automail_logs")
        MESSAGE_LOG = LOGS_DIR / "message_log.json"
        
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        if entry.get("id") in message_ids and entry.get("ai_generated") is False:
                            # This is a human-edited message
                            updates[entry.get("id")] = entry.get("response")
                            
                            # Update conversation history for future context
                            msg_id = entry.get("id")
                            if msg_id in message_store:
                                recipient = message_store[msg_id].get("recipient", "default_chat")
                                # Find and update this message in the conversation history
                                for i, msg in enumerate(conversation_history[recipient]):
                                    if msg.get("role") == "assistant" and msg.get("content") == message_store[msg_id]["response"]:
                                        # Update with the edited response
                                        conversation_history[recipient][i]["content"] = entry.get("response")
                                        break
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Error reading message log: {e}")
        
        return jsonify({"updates": updates})
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return jsonify({"updates": {}})


@app.route('/messages')
def get_messages():
    """Get the message log (for backup update checking)."""
    try:
        # Try to get the message log from the monitor server
        LOGS_DIR = Path("automail_logs")
        MESSAGE_LOG = LOGS_DIR / "message_log.json"
        
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    return jsonify(log_data)
                except json.JSONDecodeError:
                    logger.error("Error reading message log")
        
        return jsonify([])
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return jsonify([])


def check_for_updates():
    """Background task to check for message updates."""
    while True:
        try:
            # Check the message log for updates
            LOGS_DIR = Path("automail_logs")
            MESSAGE_LOG = LOGS_DIR / "message_log.json"
            
            if MESSAGE_LOG.exists():
                with open(MESSAGE_LOG, "r") as f:
                    try:
                        log_data = json.load(f)
                        for entry in log_data:
                            msg_id = entry.get("id")
                            if msg_id in message_store and entry.get("ai_generated") is False:
                                # This is a human-edited message, update our store
                                message_store[msg_id]["response"] = entry.get("response")
                                message_store[msg_id]["checked"] = True
                                
                                # Also update the conversation history
                                recipient = message_store[msg_id].get("recipient", "default_chat")
                                # Find and update this message in the conversation history
                                for i, msg in enumerate(conversation_history[recipient]):
                                    if msg.get("role") == "assistant" and i > 0 and conversation_history[recipient][i-1].get("role") == "user":
                                        # This is likely the response to check
                                        old_response = msg.get("content")
                                        if old_response == message_store[msg_id].get("original_response", old_response):
                                            # Update with the edited response
                                            conversation_history[recipient][i]["content"] = entry.get("response")
                                            break
                    except (json.JSONDecodeError, IOError) as e:
                        logger.error(f"Error reading message log: {e}")
        except Exception as e:
            logger.error(f"Error in update thread: {e}")
            
        # Sleep for a while before checking again
        time.sleep(10)


if __name__ == "__main__":
    # Start the background update check thread
    update_thread = threading.Thread(target=check_for_updates, daemon=True)
    update_thread.start()
    
    # Run the Flask app
    app.run(debug=False, port=5000)
