from __future__ import annotations

import argparse as arg_parser
import threading
import time
import json
import os
import sys
import uuid
import requests
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Set, Optional, Union, Any

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
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    to_ai: bool = False  # Flag to indicate if message is specifically for AI
    human_only: bool = False  # Flag to indicate this message should not get AI responses
    is_ai_response: bool = False  # Flag to indicate this is an AI response
    ai_sender: str = None  # The person whose AI generated this response
    reply_to_message_id: str = None  # ID of the message this is responding to
    
    def to_dict(self):
        return {
            "content": self.content,
            "sender": self.sender,
            "conversation_id": self.conversation_id,
            "conversation_name": self.conversation_name,
            "all_participants": self.all_participants,
            "ts": self.ts.isoformat(),
            "message_id": self.message_id,
            "to_ai": self.to_ai,
            "human_only": self.human_only,
            "is_ai_response": self.is_ai_response,
            "ai_sender": self.ai_sender,
            "reply_to_message_id": self.reply_to_message_id
        }


class ChatResponse(BaseModel):
    status: str
    ts: datetime
    message_id: str = None


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


class OllamaHandler:
    """Handler for Ollama AI integration"""
    def __init__(self, base_url="http://localhost:11434", model="llama3.2:latest"):
        self.base_url = base_url
        self.model = model
        # The API endpoint is just /api/generate
        self.api_url = f"{self.base_url}/api/generate"
        
    def generate_response(self, prompt: str) -> str:
        """Generate a response using Ollama model"""
        try:
            # Updated payload structure to match Ollama API
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }
            
            # Add debug logging
            logger.info(f"Sending request to Ollama API at {self.api_url}")
            logger.info(f"Using model: {self.model}")
            
            response = requests.post(self.api_url, json=payload)
            logger.info(f"Ollama API response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "Sorry, I couldn't generate a response.")
            else:
                # Try to get more details from the error response
                try:
                    error_details = response.json()
                    return f"Error from Ollama API: {response.status_code} - {error_details.get('error', 'Unknown error')}"
                except:
                    return f"Error from Ollama API: {response.status_code}"
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {str(e)}")
            return f"Failed to connect to Ollama: {str(e)}"
    
    def format_chat_prompt(self, sender: str, message: str, conversation_history: List[dict]) -> str:
        """Format a prompt for the AI using conversation context"""
        # Get last few messages for context (limit to 5 for brevity)
        context_messages = conversation_history[-5:] if len(conversation_history) > 5 else conversation_history
        
        prompt = f"""You are an AI assistant helping to respond to chat messages.

Recent conversation:
"""
        
        # Add conversation context
        for msg in context_messages:
            sender_name = "You" if msg.get("is_self", False) else msg.get("sender", "Unknown")
            prompt += f"{sender_name}: {msg.get('content', '')}\n"
        
        # Add the current message and request
        prompt += f"\n{sender}: {message}\n\nPlease write a helpful and friendly response:"
        
        return prompt

    def _check_available_models(self):
        """Check what models are available in Ollama"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [model["name"] for model in models]
                logger.info(f"Available Ollama models: {model_names}")
                return model_names
            else:
                logger.warning(f"Failed to get available models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error checking available models: {e}")
            return []

    def generate_summary(self, responses: List[dict]) -> str:
        """Generate a semantic average of multiple AI responses using Ollama model"""
        if not responses or len(responses) <= 1:
            return responses[0]["content"] if responses else ""
        
        # Construct a prompt that asks for a semantic average response
        prompt = f"""Pretend that each of these people got together to co-write a reply — and then write what they would collectively write:

"""
        # Add each response to the prompt
        for i, response in enumerate(responses, 1):
            ai_owner = response.get("ai_sender", "Unknown")
            prompt += f"\n--- Response #{i} from {ai_owner}'s AI ---\n{response.get('content', '')}\n"
        
        prompt += """

Rather than summarizing these responses, please write a single cohesive response that:
1. Represents what these AI assistants would collectively write if they collaborated
2. Blends the style, tone, and content from all responses into one "average" voice
3. Incorporates the most common points made across all responses
4. Presents a unified perspective that feels like a single, balanced answer
5. Is shorter than the longest individual response.

Write as if you are the collective voice of all these AIs speaking together. Don't refer to the individual responses or mention that this is a blend of multiple answers.
"""
        
        try:
            logger.info(f"Generating semantic average for {len(responses)} AI responses")
            average_response = self.generate_response(prompt)
            return average_response
        except Exception as e:
            logger.error(f"Error generating semantic average: {e}")
            return "Could not generate combined response. Please expand to see individual responses."


# Class to handle chat functionality
class ChatClient:
    def __init__(self, config_path=None):
        self.client = Client.load(config_path)
        self.running = True
        self.conversations = {}  # Dictionary of conversation_id -> Conversation
        self.conversation_lock = threading.Lock()
        
        # AI auto-response settings
        self.ai_enabled = False
        self.ollama_handler = OllamaHandler()
        self.ai_settings = {
            "model": "llama3.2:latest",
            "auto_respond": False,
            "base_url": "http://localhost:11434"
        }
        
        # Try to load AI settings
        self._load_ai_settings()
        
        # Set up event handler for receiving messages
        self.box = SyftEvents("chat", client=self.client)
        
        # Add to __init__ method
        self.ai_response_summaries = {}  # Store summaries for AI response groups
        
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
                "conversation_id": message.conversation_id,
                "message_id": getattr(message, "message_id", str(uuid.uuid4())),
                "delivered": True,  # Messages received are already delivered
                "to_ai": getattr(message, "to_ai", False),  # Include the to_ai flag
                "human_only": getattr(message, "human_only", False),  # Include the human_only flag
                "is_ai_response": getattr(message, "is_ai_response", False),  # Include the is_ai_response flag
                "ai_sender": getattr(message, "ai_sender", None),  # Include the ai_sender
                "reply_to_message_id": getattr(message, "reply_to_message_id", None)  # Include the reply_to_message_id
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
            
            # Check if this message is specifically for AI or if we should auto-respond
            to_ai = getattr(message, "to_ai", False)
            is_ai_response = getattr(message, "is_ai_response", False)
            original_message_id = getattr(message, "message_id", None)

            # CRITICAL FIX: Never respond to messages that are already AI responses
            if is_ai_response:
                logger.info(f"Ignoring AI response from {message.sender} to prevent response loops")
                return ChatResponse(
                    status="delivered",
                    ts=datetime.now(timezone.utc),
                    message_id=original_message_id
                )

            if to_ai and message.sender != "System":
                # Always process AI-targeted messages if AI is enabled
                if self.ai_enabled:
                    # Process in a separate thread to avoid blocking
                    threading.Thread(
                        target=self._process_ai_response,
                        args=(conversation_id, message.sender, message.content, original_message_id),
                        daemon=True
                    ).start()
                else:
                    logger.info(f"Message from {message.sender} was sent to AI, but AI is disabled")
            # Only auto-respond if explicitly enabled AND the message isn't marked as human-only
            elif self.ai_enabled and self.ai_settings.get("auto_respond", False) and not getattr(message, "human_only", False) and message.sender != "System":
                # Process in a separate thread to avoid blocking
                threading.Thread(
                    target=self._process_ai_response,
                    args=(conversation_id, message.sender, message.content, original_message_id),
                    daemon=True
                ).start()
            
            return ChatResponse(
                status="delivered",
                ts=datetime.now(timezone.utc),
                message_id=original_message_id
            )
    
    def _load_ai_settings(self):
        """Load AI settings from file"""
        settings_path = os.path.join(os.path.dirname(__file__), 'ai_settings.json')
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    self.ai_settings.update(settings)
                    
                    # Update Ollama handler settings
                    self.ollama_handler = OllamaHandler(
                        base_url=self.ai_settings.get("base_url", "http://localhost:11434"),
                        model=self.ai_settings.get("model", "llama3.2")
                    )
                    
                    # Set AI enabled state
                    self.ai_enabled = self.ai_settings.get("auto_respond", False)
                    
                    logger.info(f"Loaded AI settings: {self.ai_settings}")
            except Exception as e:
                logger.error(f"Error loading AI settings: {e}")
    
    def _save_ai_settings(self):
        """Save AI settings to file"""
        settings_path = os.path.join(os.path.dirname(__file__), 'ai_settings.json')
        try:
            with open(settings_path, 'w') as f:
                json.dump(self.ai_settings, f, indent=2)
            logger.info(f"Saved AI settings: {self.ai_settings}")
        except Exception as e:
            logger.error(f"Error saving AI settings: {e}")
    
    def _process_ai_response(self, conversation_id: str, sender: str, message: str, original_message_id: str = None):
        """Process an AI response to an incoming message"""
        try:
            # Get conversation
            conversation = self.get_conversation(conversation_id)
            if not conversation:
                logger.error(f"Conversation {conversation_id} not found for AI response")
                return
            
            # Get conversation history
            history = conversation.get_messages()
            
            # Generate AI response
            prompt = self.ollama_handler.format_chat_prompt(sender, message, history)
            ai_response = self.ollama_handler.generate_response(prompt)
            
            # Small delay to make the conversation feel more natural
            time.sleep(1.5)
            
            # Send the response
            self.send_message(
                conversation_id, 
                ai_response, 
                to_ai=False,  # This is from AI, not to AI
                is_ai_response=True,
                ai_sender=self.client.email, # The owner of this AI
                reply_to_message_id=original_message_id # Link to original message
            )
            
            logger.info(f"Sent AI response in conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
    
    def update_ai_settings(self, settings: dict):
        """Update AI settings"""
        self.ai_settings.update(settings)
        
        # Update Ollama handler if needed
        if "base_url" in settings or "model" in settings:
            self.ollama_handler = OllamaHandler(
                base_url=self.ai_settings.get("base_url", "http://localhost:11434"),
                model=self.ai_settings.get("model", "llama3.2:latest")
            )
        
        # Update AI enabled state
        self.ai_enabled = self.ai_settings.get("auto_respond", False)
        
        # Save settings
        self._save_ai_settings()
        
        return self.ai_settings
    
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
    
    def send_message(self, conversation_id: str, content: str, to_ai: bool = False, 
                    is_ai_response: bool = False, ai_sender: str = None, 
                    reply_to_message_id: str = None):
        """Send a message to all recipients in a conversation"""
        if not content or not conversation_id:
            return False
        
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return False
        
        # Generate a unique message ID
        message_id = str(uuid.uuid4())
        
        # Store message in conversation history first with delivered=False
        timestamp = datetime.now(timezone.utc)
        formatted_message = {
            "content": content,
            "sender": self.client.email,
            "timestamp": timestamp.isoformat(),
            "is_self": True,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "delivered": False,  # Initially not delivered
            "delivery_percent": 0,  # New field for tracking percentage
            "delivered_to": [],  # Track which recipients have received the message
            "to_ai": to_ai,  # Flag to indicate if message is for AI
            "human_only": not to_ai and not is_ai_response,  # If not to_ai and not an AI response, mark as human_only
            "is_ai_response": is_ai_response,
            "ai_sender": ai_sender,
            "reply_to_message_id": reply_to_message_id
        }
        
        conversation.add_message(formatted_message)
        
        # Create a full list of all participants (including self)
        all_participants = conversation.recipients.copy()
        all_participants.append(self.client.email)
        
        # Total recipients count for percentage calculation
        total_recipients = len(conversation.recipients)
        
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
                        all_participants=all_participants,  # Include all participants in the message
                        message_id=message_id,
                        to_ai=to_ai,  # Include the to_ai flag
                        human_only=not to_ai and not is_ai_response,  # If not to_ai and not an AI response, mark as human_only
                        is_ai_response=is_ai_response,
                        ai_sender=ai_sender,
                        reply_to_message_id=reply_to_message_id
                    ),
                    expiry="5m",
                    cache=True,
                    client=self.client
                )
                
                # Wait for response but don't block UI
                def wait_for_response(recipient_email):
                    try:
                        response = future.wait(timeout=30)
                        if response.status_code == 200:
                            # Update delivery status when we get confirmation
                            with self.conversation_lock:
                                for msg in conversation.messages:
                                    if msg.get("message_id") == message_id and msg.get("is_self"):
                                        # Add to delivered_to list
                                        if recipient_email not in msg.get("delivered_to", []):
                                            msg.setdefault("delivered_to", []).append(recipient_email)
                                        
                                        # Calculate and update percentage
                                        delivered_count = len(msg.get("delivered_to", []))
                                        # Exclude "System" from the recipient count
                                        actual_recipients = [r for r in conversation.recipients if r != "System"]
                                        actual_recipient_count = len(actual_recipients)
                                        if actual_recipient_count > 0:
                                            msg["delivery_percent"] = int((delivered_count / actual_recipient_count) * 100)
                                        
                                        # If all recipients have received, mark as fully delivered
                                        if delivered_count >= actual_recipient_count:
                                            msg["delivered"] = True
                    # else:
                    #     logger.error(f"Failed to deliver message to {recipient_email}: {response.status_code}")
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

    # Add a method to generate and store summaries
    def generate_ai_response_summary(self, conversation_id: str, reply_to_message_id: str) -> str:
        """Generate a summary of all AI responses to a particular message"""
        try:
            if not self.ai_enabled:
                return ""
                
            # Check if we already have a cached summary
            summary_key = f"{conversation_id}:{reply_to_message_id}"
            if summary_key in self.ai_response_summaries:
                logger.debug(f"Using cached summary for {summary_key}")
                return self.ai_response_summaries[summary_key]
                
            conversation = self.get_conversation(conversation_id)
            if not conversation:
                return ""
                
            # Find all AI responses to this message
            ai_responses = []
            for msg in conversation.get_messages():
                if (msg.get("is_ai_response") and 
                    msg.get("reply_to_message_id") == reply_to_message_id):
                    ai_responses.append(msg)
            
            # If we have multiple responses, generate a summary
            if len(ai_responses) > 1:
                logger.info(f"Generating summary for {len(ai_responses)} AI responses to message {reply_to_message_id}")
                summary = self.ollama_handler.generate_summary(ai_responses)
                
                # Store the summary
                self.ai_response_summaries[summary_key] = summary
                
                return summary
            elif len(ai_responses) == 1:
                # For a single response, just use that content
                single_response = ai_responses[0].get("content", "")
                # Cache this too so we don't keep checking
                self.ai_response_summaries[summary_key] = single_response
                return single_response
            else:
                # Cache empty string for no responses
                self.ai_response_summaries[summary_key] = ""
                return ""
        except Exception as e:
            logger.error(f"Error generating AI response summary: {e}")
            return ""


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
        to_ai = data.get('to_ai', False)  # Check if this is for AI
        
        if message and chat_client.send_message(conversation_id, message, to_ai=to_ai):
            # Get the message ID of the most recent message sent by the user
            conversation = chat_client.get_conversation(conversation_id)
            if conversation:
                user_messages = [msg for msg in conversation.get_messages() 
                              if msg.get('is_self') and msg.get('content') == message]
                if user_messages:
                    # Get the most recent matching message (should be the one we just sent)
                    latest_message = max(user_messages, key=lambda x: x.get('timestamp', ''))
                    message_id = latest_message.get('message_id')
                    return jsonify({"status": "success", "message_id": message_id})
            
            # Fallback if we can't find the message ID
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
    
    @app.route('/ai_settings', methods=['GET'])
    def get_ai_settings():
        """Get current AI settings"""
        return jsonify({
            "settings": chat_client.ai_settings,
            "enabled": chat_client.ai_enabled
        })
    
    @app.route('/ai_settings', methods=['POST'])
    def update_ai_settings():
        """Update AI settings"""
        data = request.json
        try:
            updated_settings = chat_client.update_ai_settings(data)
            return jsonify({
                "status": "success",
                "settings": updated_settings,
                "enabled": chat_client.ai_enabled
            })
        except Exception as e:
            logger.error(f"Error updating AI settings: {e}")
            return jsonify({
                "status": "error",
                "message": str(e)
            })
    
    @app.route('/test_ollama', methods=['GET'])
    def test_ollama():
        """Test the Ollama API connection"""
        try:
            base_url = chat_client.ai_settings.get("base_url", "http://localhost:11434")
            model = chat_client.ai_settings.get("model", "llama3.2:latest")
            
            # First, check if the Ollama server is running
            try:
                server_response = requests.get(f"{base_url}/api/version")
                server_status = server_response.status_code == 200
                server_version = server_response.json().get("version", "unknown") if server_status else "not available"
            except:
                server_status = False
                server_version = "not available"
            
            # Then check if the model is available
            try:
                models_response = requests.get(f"{base_url}/api/tags")
                if models_response.status_code == 200:
                    all_models = models_response.json().get("models", [])
                    available_models = [m["name"] for m in all_models]
                    model_available = model in available_models
                else:
                    available_models = []
                    model_available = False
            except:
                available_models = []
                model_available = False
            
            return jsonify({
                "status": "success" if server_status else "error",
                "server": {
                    "running": server_status,
                    "url": base_url,
                    "version": server_version
                },
                "models": {
                    "available": available_models,
                    "selected": model,
                    "is_available": model_available
                },
                "next_steps": "Pull the model" if (server_status and not model_available) else (
                    "Install and start Ollama" if not server_status else "Ready to use"
                )
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            })
    
    @app.route('/conversation/<conversation_id>/ai_summary/<message_id>', methods=['GET'])
    def get_ai_summary(conversation_id, message_id):
        """Get or generate a summary of AI responses to a message"""
        summary = chat_client.generate_ai_response_summary(conversation_id, message_id)
        return jsonify({"summary": summary})
    
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
            height: 100%;  /* Ensure full height */
            overflow: hidden;  /* Add this to prevent content overflow */
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
            flex-shrink: 0;  /* Prevent header from shrinking */
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
            display: flex;
            flex-direction: column;
            min-height: 0;  /* Critical for allowing flex containers to scroll */
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
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .delivery-status {
            display: inline-flex;
            align-items: center;
            margin-left: 5px;
            gap: 4px;
        }
        
        .status-pending {
            color: var(--text-muted);
        }
        
        .status-delivered {
            color: var(--success-color);
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
            flex-shrink: 0;  /* Prevent form from shrinking */
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

        .send-buttons {
            display: flex;
            gap: 8px;
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
        
        .send-ai-button {
            background-color: #43b581; /* A different color for the AI button */
        }
        
        .send-ai-button:hover {
            background-color: #3ca374;
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
        
        /* Delivery status indicators */
        .delivery-status {
            display: inline-flex;
            align-items: center;
            margin-left: 5px;
            gap: 4px;
        }
        
        .status-pending {
            color: var(--text-muted);
        }
        
        .status-delivered {
            color: var(--success-color);
        }
        
        /* Pie chart styles */
        .pie-chart {
            position: relative;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: var(--bg-accent);
            display: inline-flex;
            justify-content: center;
            align-items: center;
        }
        
        .pie-percent-text {
            font-size: 10px;
            color: var(--text-muted);
        }
        
        /* AI settings styles */
        .ai-toggle-container {
            margin-top: 10px;
            padding: 10px 16px;
            background-color: var(--bg-tertiary);
            border-radius: var(--border-radius);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .ai-settings-btn {
            color: var(--accent-color);
            background: none;
            border: none;
            cursor: pointer;
            font-size: 14px;
        }
        
        .ai-settings-btn:hover {
            text-decoration: underline;
        }
        
        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 40px;
            height: 22px;
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
            background-color: var(--bg-accent);
            transition: .4s;
            border-radius: 34px;
        }
        
        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        input:checked + .toggle-slider {
            background-color: var(--accent-color);
        }
        
        input:checked + .toggle-slider:before {
            transform: translateX(18px);
        }
        
        /* AI settings modal */
        .ai-settings-container {
            margin-bottom: 15px;
        }
        
        .ai-settings-container h4 {
            margin-bottom: 10px;
            color: var(--text-primary);
        }
        
        .ai-status {
            margin-top: 5px;
            font-size: 12px;
            color: var(--text-secondary);
        }
        
        .ai-response-indicator {
            position: absolute;
            bottom: 10px;
            left: 50%;
            transform: translateX(-50%);
            background-color: var(--bg-tertiary);
            color: var(--accent-color);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            display: none;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
            z-index: 10;
        }
        
        .ai-response-indicator.show {
            display: flex;
            align-items: center;
            gap: 6px;
            animation: fadeIn 0.3s;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        .ai-dot {
            height: 8px;
            width: 8px;
            background-color: var(--accent-color);
            border-radius: 50%;
            display: inline-block;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0% { transform: scale(0.8); opacity: 0.7; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.8); opacity: 0.7; }
        }

        /* AI response group styles - improved layout */
        .ai-response-group {
            max-width: 90%;
            margin: 15px auto;
            border-radius: 12px;
            background-color: rgba(67, 181, 129, 0.1);
            border: 1px solid rgba(67, 181, 129, 0.2);
            overflow: hidden;
            min-height: 220px; /* Default collapsed height */
            transition: min-height 0.3s ease-out;
        }

        .ai-response-header {
            padding: 16px 20px; /* Increased padding */
            background-color: rgba(67, 181, 129, 0.15);
            display: flex;
            flex-direction: column; /* Stack elements vertically */
            cursor: pointer; /* Explicitly show pointer cursor */
            transition: background-color 0.2s;
            position: relative; /* For hover effects */
        }

        .ai-response-header:hover {
            background-color: rgba(67, 181, 129, 0.25);
        }
        
        /* Remove the overlapping hover indicator */
        .ai-response-header:hover::after {
            display: none; /* Remove the overlapping indicator */
        }
        
        /* Add subtle highlight to the entire header instead */
        .ai-response-header:hover {
            box-shadow: inset 0 0 0 2px rgba(67, 181, 129, 0.4);
        }
        
        /* Make summary content have normal cursor for text selection */
        .ai-summary-content {
            cursor: auto; /* Default cursor behavior */
            position: relative; /* For positioning the expand/collapse icon */
        }
        
        /* Add subtle visual indicator that shows the expand/collapse action */
        .ai-summary-text {
            position: relative;
            padding-right: 5px; /* Space for the subtle indicator */
        }

        .ai-response-summary {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px; /* Add space between summary and content */
        }

        .ai-response-title {
            font-weight: 600; /* Made slightly bolder */
            font-size: 15px; /* Slightly larger */
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 10px; /* More space between icon and text */
        }

        .ai-response-title i {
            color: #43b581;
            font-size: 16px; /* Slightly larger icon */
        }

        .ai-response-count {
            background-color: rgba(67, 181, 129, 0.3);
            color: var(--text-primary);
            padding: 4px 12px; /* More padding */
            border-radius: 16px; /* More rounded */
            font-size: 13px; /* Slightly larger */
            font-weight: 500; /* Medium weight */
            display: flex;
            align-items: center;
            gap: 6px; /* Space between text and icon */
        }
        
        .ai-response-count i {
            transition: transform 0.3s;
        }
        
        .ai-response-count i.open {
            transform: rotate(180deg);
        }

        .ai-response-body {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.5s ease-out;
        }

        .ai-response-body.expanded {
            max-height: 400px; /* Set a fixed maximum height */
            overflow-y: auto;  /* Enable vertical scrolling */
            min-height: 300px;
        }

        .ai-response-item {
            padding: 12px 15px;
            border-bottom: 1px solid rgba(67, 181, 129, 0.2);
        }

        .ai-response-item:last-child {
            border-bottom: none;
        }

        .ai-response-from {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: var(--text-secondary);
            margin-bottom: 5px;
        }

        .ai-response-content {
            color: var(--text-primary);
            white-space: pre-wrap;
        }

        /* AI summary content improvements */
        .ai-summary-content {
            padding: 15px 20px; /* More padding */
            border-top: 1px solid rgba(67, 181, 129, 0.2);
            white-space: pre-wrap;
            color: var(--text-primary);
            max-height: 200px;
            min-height: 60px; /* Ensure minimum height */
            overflow-y: auto; /* Allow vertical scrolling in summary */
            scrollbar-width: thin;
            scrollbar-color: rgba(67, 181, 129, 0.5) rgba(67, 181, 129, 0.1);
            line-height: 1.6; /* Improved line spacing */
            font-size: 14px; /* Standardized font size */
        }
        
        .ai-summary-content::-webkit-scrollbar {
            width: 6px;
        }
        
        .ai-summary-content::-webkit-scrollbar-thumb {
            background-color: rgba(67, 181, 129, 0.5);
            border-radius: 3px;
        }
        
        .ai-summary-content::-webkit-scrollbar-track {
            background-color: rgba(67, 181, 129, 0.1);
            border-radius: 3px;
        }

        .ai-summary-loading {
            color: var(--text-secondary);
            font-style: italic;
            display: flex;
            align-items: center;
            gap: 8px;
            min-height: 40px; /* Ensure minimum height when loading */
        }

        .ai-summary-error {
            color: var(--text-muted);
            font-style: italic;
            min-height: 40px; /* Ensure minimum height for errors */
        }

        .ai-summary-text {
            line-height: 1.5;
            min-height: 60px; /* Ensure minimum height */
        }

        /* Conversations link styles */
        .conversations-link {
            color: var(--text-primary);
            text-decoration: none;
            cursor: pointer;
            transition: color var(--transition-speed);
        }

        .conversations-link:hover {
            color: var(--accent-color);
        }

        /* Message Styles Update */
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
        
        /* New style for messages sent to AI */
        .message.self.to-ai .message-content {
            background-color: #43b581; /* Same green color as the AI button */
            color: white;
            border-bottom-right-radius: 4px;
        }
        
        .message.other .message-content {
            background-color: var(--message-other);
            color: var(--text-primary);
            border-bottom-left-radius: 4px;
        }
        
        /* New style for received messages intended for AI */
        .message.other.to-ai .message-content {
            background-color: #43b581; /* Same green color as the AI button */
            color: white;
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
        
        /* Empty AI response group styles */
        .ai-response-group.empty-group {
            background-color: rgba(67, 181, 129, 0.05);
            border: 1px dashed rgba(67, 181, 129, 0.2);
        }
        
        .empty-group .ai-response-count {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .empty-group .fa-spin {
            color: var(--accent-color);
        }
        
        /* Placeholder response styling */
        .placeholder-response {
            opacity: 0.8;
        }
        
        .placeholder-loading {
            margin-top: 10px;
            display: flex;
            justify-content: center;
        }
        
        .dot-loading {
            display: inline-block;
            width: 8px;
            height: 8px;
            background-color: var(--accent-color);
            border-radius: 50%;
            margin: 0 3px;
            animation: dotPulse 1.5s infinite;
        }
        
        .dot-loading:nth-child(2) {
            animation-delay: 0.2s;
        }
        
        .dot-loading:nth-child(3) {
            animation-delay: 0.4s;
        }
        
        @keyframes dotPulse {
            0% { transform: scale(0.8); opacity: 0.5; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.8); opacity: 0.5; }
        }
        
        /* Placeholder response styling */
        .placeholder-group {
            background-color: rgba(67, 181, 129, 0.05);
            border: 1px dashed rgba(67, 181, 129, 0.3);
            margin: 10px 0;
            border-radius: var(--border-radius);
            overflow: hidden;
        }
        
        .typing-indicator {
            padding: 15px;
            display: flex;
            justify-content: flex-start;
            align-items: center;
        }
        
        .typing-indicator span {
            height: 10px;
            width: 10px;
            margin: 0 2px;
            background-color: var(--accent-color);
            border-radius: 50%;
            display: inline-block;
            opacity: 0.4;
        }
        
        .typing-indicator span:nth-of-type(1) {
            animation: pulse 1s infinite ease-in-out;
        }
        
        .typing-indicator span:nth-of-type(2) {
            animation: pulse 1s infinite ease-in-out .2s;
        }
        
        .typing-indicator span:nth-of-type(3) {
            animation: pulse 1s infinite ease-in-out .4s;
        }
        
        @keyframes pulse {
            0% { transform: scale(1); opacity: 0.4; }
            50% { transform: scale(1.3); opacity: 1; }
            100% { transform: scale(1); opacity: 0.4; }
        }
        
        .loading-animation {
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--accent-color);
        }
        
        .loading-animation i {
            color: var(--accent-color);
        }
        
        .placeholder-message {
            padding: 10px;
            background-color: rgba(67, 181, 129, 0.05);
            border-radius: 8px;
        }
        
        /* Update chat interface */
        #chat-interface {
            display: none; 
            flex: 1; 
            display: flex; 
            flex-direction: column;
            height: 100%;  /* Ensure it takes full height */
            overflow: hidden;  /* Contain the overflow */
        }
    </style>
</head>
<body>
    <div class="app-container">
        <div class="sidebar">
            <div class="sidebar-header">
                <h2><a href="/" id="conversations-link" class="conversations-link">Conversations</a></h2>
                <button id="new-chat-btn" class="new-chat-btn">
                    <i class="fas fa-plus"></i>
                    <span>New Chat</span>
                </button>
            </div>
            <div id="conversation-list" class="conversation-list">
                <!-- Conversations will be populated here -->
                <div class="no-conversations">No conversations yet</div>
            </div>
            <div class="ai-toggle-container">
                <div>
                    <label for="ai-toggle" class="ai-toggle-label">AI Auto-Respond</label>
                    <div id="ai-status" class="ai-status">Disabled</div>
                </div>
                <div class="ai-controls">
                    <label class="toggle-switch">
                        <input type="checkbox" id="ai-toggle">
                        <span class="toggle-slider"></span>
                    </label>
                    <button id="ai-settings-btn" class="ai-settings-btn">
                        <i class="fas fa-cog"></i>
                    </button>
                </div>
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
                    <div class="send-buttons">
                        <button id="send-button" class="send-button" title="Send to humans">
                            <i class="fas fa-paper-plane"></i>
                        </button>
                        <button id="send-ai-button" class="send-button send-ai-button" title="Send to AIs">
                            <i class="fas fa-robot"></i>
                        </button>
                    </div>
                </div>
            </div>
            <div id="ai-response-indicator" class="ai-response-indicator">
                <span class="ai-dot"></span>
                <span>AI is responding...</span>
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

    <div id="ai-settings-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>AI Auto-Response Settings</h3>
                <button class="close-modal" onclick="closeAISettingsModal()">&times;</button>
            </div>
            <div class="ai-settings-container">
                <h4>Ollama Model</h4>
                <select id="ai-model" class="form-control">
                    <option value="llama3.2:latest">llama3.2:latest</option>
                    <option value="mistral:latest">mistral:latest</option>
                    <option value="llama3:latest">llama3:latest</option>
                </select>
            </div>
            <div class="form-group">
                <label for="ai-url">Ollama API URL</label>
                <input type="text" id="ai-url" placeholder="http://localhost:11434">
                <div class="form-error" id="ai-url-error"></div>
            </div>
            <div class="modal-actions">
                <button class="cancel-btn" onclick="closeAISettingsModal()">Cancel</button>
                <button id="save-ai-settings-btn" class="create-btn">Save Settings</button>
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
        
        // Keep track of expanded AI response groups
        const expandedResponseGroups = {};
        
        // Track all scrollable elements
        function saveAllScrollPositions() {
            const scrollableElements = {};
            
            // Find all scrollable elements and save their position
            document.querySelectorAll('.ai-summary-content, .ai-response-body.expanded').forEach(el => {
                // Find containing response group to identify this element
                const parentGroup = el.closest('.ai-response-group');
                if (parentGroup && parentGroup.dataset.msgId) {
                    const messageId = parentGroup.dataset.msgId;
                    const isBody = el.classList.contains('ai-response-body');
                    const key = isBody ? `body-${messageId}` : `summary-${messageId}`;
                    
                    scrollableElements[key] = {
                        scrollTop: el.scrollTop,
                        element: el,
                        selector: isBody ? 
                            `.ai-response-group[data-msg-id="${messageId}"] .ai-response-body` : 
                            `.ai-response-group[data-msg-id="${messageId}"] .ai-summary-content`
                    };
                }
            });
            
            return scrollableElements;
        }
        
        function restoreAllScrollPositions(savedPositions) {
            // Wait a moment for DOM to update
            setTimeout(() => {
                for (const key in savedPositions) {
                    const saved = savedPositions[key];
                    if (saved.scrollTop > 0) {
                        const element = document.querySelector(saved.selector);
                        if (element) {
                            element.scrollTop = saved.scrollTop;
                        }
                    }
                }
            }, 100);
        }
        
        // Enhance the refreshMessages function to use our scroll position tracking
        const originalRefreshMessages = refreshMessages;
        refreshMessages = function() {
            // Save scroll positions of all scrollable elements
            const savedScrollPositions = saveAllScrollPositions();
            
            // Call the original refresh
            originalRefreshMessages();
            
            // Restore all scroll positions
            restoreAllScrollPositions(savedScrollPositions);
        };
        
        // Refresh messages for current conversation
        function refreshMessages() {
            if (!currentConversationId) return;
            
            fetch(`/conversation/${currentConversationId}/messages`)
                .then(response => response.json())
                .then(data => {
                    // Remember scroll position before refresh
                    const scrollPos = chatMessages.scrollTop;
                    const isAtBottom = chatMessages.scrollHeight - chatMessages.clientHeight <= chatMessages.scrollTop + 50;
                    
                    // Save all existing AI response groups for potential reuse
                    const existingResponseGroups = {};
                    document.querySelectorAll('.ai-response-group[data-msg-id]').forEach(el => {
                        const msgId = el.dataset.msgId;
                        if (msgId && !msgId.startsWith('temp-')) { // Only save real response groups
                            // Save expansion state and content
                            existingResponseGroups[msgId] = {
                                element: el,
                                expanded: el.querySelector('.ai-response-body.expanded') !== null,
                                summaryContent: el.querySelector('.ai-summary-content')?.innerHTML || ''
                            };
                        }
                    });
                    
                    // Store all existing temp elements before clearing the chat
                    const tempElements = [];
                    document.querySelectorAll('.ai-response-group[data-msg-id^="temp-"]').forEach(el => {
                        tempElements.push({
                            element: el.cloneNode(true),
                            id: el.dataset.msgId,
                            messageContent: el.previousElementSibling?.querySelector('.message-content')?.textContent || ''
                        });
                    });
                    
                    chatMessages.innerHTML = '';
                    
                    // Group AI responses by the message they are replying to
                    const aiResponseGroups = {};
                    const messagesToRender = [];
                    const messageIds = new Set(); // Track all real message IDs
                    
                    data.messages.forEach(msg => {
                        if (msg.message_id) {
                            messageIds.add(msg.message_id);
                        }
                        
                        if (msg.is_ai_response && msg.reply_to_message_id) {
                            // This is an AI response to a specific message
                            if (!aiResponseGroups[msg.reply_to_message_id]) {
                                aiResponseGroups[msg.reply_to_message_id] = [];
                            }
                            aiResponseGroups[msg.reply_to_message_id].push(msg);
                        } else {
                            // Regular message, add to render list
                            messagesToRender.push(msg);
                        }
                    });
                    
                    // Render messages and AI response groups
                    messagesToRender.forEach(msg => {
                        const messageEl = document.createElement('div');
                        if (msg.sender === 'System') {
                            messageEl.className = 'message system';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="system-timestamp">${formatTimestamp(msg.timestamp)}</div>
                            `;
                        } else if (msg.is_self) {
                            // Add to-ai class for messages directed to AI
                            messageEl.className = msg.to_ai ? 'message self to-ai' : 'message self';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="message-meta">
                                    ${formatTimestamp(msg.timestamp)}
                                    ${getDeliveryStatusHtml(msg)}
                                </div>
                            `;
                        } else {
                            // Add to-ai class for received messages directed to AI
                            messageEl.className = msg.to_ai ? 'message other to-ai' : 'message other';
                            messageEl.innerHTML = `
                                <div class="message-content">${msg.content}</div>
                                <div class="message-meta">${msg.sender} • ${formatTimestamp(msg.timestamp)}</div>
                            `;
                        }
                        chatMessages.appendChild(messageEl);
                        
                        // Check if there are AI responses to this message
                        if (aiResponseGroups[msg.message_id] && aiResponseGroups[msg.message_id].length > 0) {
                            const responses = aiResponseGroups[msg.message_id];
                            
                            // Check if we already have this response group and can reuse it
                            if (existingResponseGroups[msg.message_id]) {
                                // Just reuse the existing response group element
                                chatMessages.appendChild(existingResponseGroups[msg.message_id].element);
                            } else {
                                // Create a new response group
                                renderAIResponseGroup(responses, msg.message_id);
                            }
                        }
                    });
                    
                    // Re-add temporary response groups that don't have real responses yet
                    tempElements.forEach(temp => {
                        // Skip if we already have AI responses for this message ID
                        // or if the message ID is now a real one
                        if (temp.id && !temp.id.startsWith('temp-') && 
                            aiResponseGroups[temp.id] && aiResponseGroups[temp.id].length > 0) {
                            return;
                        }
                        
                        // Find the message this temp group belongs to
                        // We'll match based on content since the temp ID is likely different now
                        let found = false;
                        if (temp.messageContent) {
                            document.querySelectorAll('.message.to-ai').forEach(msgEl => {
                                const content = msgEl.querySelector('.message-content')?.textContent;
                                if (content === temp.messageContent && !msgEl.nextElementSibling?.classList.contains('ai-response-group')) {
                                    // Found matching message with no response group yet
                                    chatMessages.insertBefore(temp.element, msgEl.nextSibling);
                                    found = true;
                                }
                            });
                        }
                        
                        // If we didn't find a matching message, just add it at the end
                        if (!found && !document.querySelector(`.ai-response-group[data-msg-id="${temp.id}"]`)) {
                            chatMessages.appendChild(temp.element);
                        }
                    });
                    
                    // Restore scroll position or scroll to bottom if needed
                    if (isAtBottom) {
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    } else {
                        chatMessages.scrollTop = scrollPos;
                    }
                    
                    // Force scroll calculation after DOM has updated
                    setTimeout(() => {
                        if (isAtBottom) {
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        }
                    }, 100);
                })
                .catch(error => {
                    console.error('Error fetching messages:', error);
                });
        }
        
        // Restore and enhance the renderAIResponseGroup function
        function renderAIResponseGroup(responses, messageId) {
            if (!responses || responses.length === 0) return;
            
            // Save scroll position if replacing an existing element
            let previousBodyScrollTop = 0;
            let previousSummaryScrollTop = 0;
            const existingGroup = document.querySelector(`.ai-response-group[data-msg-id="${messageId}"]`);
            if (existingGroup) {
                const bodyEl = existingGroup.querySelector('.ai-response-body');
                const summaryEl = existingGroup.querySelector('.ai-summary-content');
                if (bodyEl) previousBodyScrollTop = bodyEl.scrollTop;
                if (summaryEl) previousSummaryScrollTop = summaryEl.scrollTop;
            }
            
            const groupDiv = document.createElement('div');
            groupDiv.className = 'ai-response-group';
            groupDiv.dataset.msgId = messageId;
            
            // Sort responses by timestamp
            responses.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
            
            // Create the header
            const headerDiv = document.createElement('div');
            headerDiv.className = 'ai-response-header';
            
            // Create the summary section with improved layout
            const summaryDiv = document.createElement('div');
            summaryDiv.className = 'ai-response-summary';
            summaryDiv.innerHTML = `
                <div class="ai-response-title">
                    <i class="fas fa-robot"></i> AI Response
                </div>
                <div class="ai-response-count">
                    <span>${responses.length} ${responses.length > 1 ? 'answers' : 'answer'}</span>
                    <i class="fas fa-chevron-down dropdown-icon"></i>
                </div>
            `;
            
            // Create a loading placeholder for the summary content
            const summaryContent = document.createElement('div');
            summaryContent.className = 'ai-summary-content';
            summaryContent.innerHTML = '<div class="ai-summary-loading"><i class="fas fa-circle-notch fa-spin"></i> Generating summary...</div>';
            
            // Create the body with all responses
            const bodyDiv = document.createElement('div');
            bodyDiv.className = 'ai-response-body';
            
            // Check if this group was previously expanded
            if (expandedResponseGroups[messageId]) {
                bodyDiv.classList.add('expanded');
                headerDiv.querySelector('.dropdown-icon')?.classList.add('open');
                groupDiv.style.minHeight = '500px'; // Set taller height for expanded state
            } else {
                groupDiv.style.minHeight = '220px'; // Set default collapsed height
            }
            
            let bodyContent = '';
            responses.forEach(response => {
                const aiOwner = response.ai_sender || 'Unknown';
                bodyContent += `
                    <div class="ai-response-item">
                        <div class="ai-response-from">
                            <span>${aiOwner}'s AI</span>
                            <span>${formatTimestamp(response.timestamp)}</span>
                        </div>
                        <div class="ai-response-content">${response.content}</div>
                    </div>
                `;
            });
            
            bodyDiv.innerHTML = bodyContent;
            
            // Fetch the summary
            fetchAISummary(currentConversationId, messageId)
                .then(summary => {
                    if (summary) {
                        summaryContent.innerHTML = `<div class="ai-summary-text">${summary}</div>`;
                    } else if (responses.length === 1) {
                        // For a single response, just show the content
                        summaryContent.innerHTML = `<div class="ai-summary-text">${responses[0].content}</div>`;
                    } else {
                        summaryContent.innerHTML = '<div class="ai-summary-error">No summary available. Please expand to see individual responses.</div>';
                    }
                    
                    // Restore scroll positions after content is loaded
                    setTimeout(() => {
                        if (previousSummaryScrollTop > 0) {
                            summaryContent.scrollTop = previousSummaryScrollTop;
                        }
                    }, 50);
                })
                .catch(error => {
                    console.error('Error fetching AI summary:', error);
                    summaryContent.innerHTML = '<div class="ai-summary-error">Error loading summary. Please expand to see individual responses.</div>';
                });
            
            // Move click handler to the header div instead of the summary div
            headerDiv.addEventListener('click', function(event) {
                // Prevent event from bubbling up
                event.stopPropagation();
                
                // Always allow toggling the expanded state regardless of where clicked
                // We'll handle text selection separately with mousedown/up events
                
                // Toggle expanded state
                bodyDiv.classList.toggle('expanded');
                this.querySelector('.dropdown-icon')?.classList.toggle('open');
                
                // Store expansion state
                expandedResponseGroups[messageId] = bodyDiv.classList.contains('expanded');
                
                // Adjust the min-height of the entire group based on expansion state
                if (bodyDiv.classList.contains('expanded')) {
                    // Expanded: set taller min-height
                    groupDiv.style.minHeight = '500px';
                } else {
                    // Collapsed: set shorter min-height
                    groupDiv.style.minHeight = '220px';
                }
            });
            
            // For text selection, we'll use mousedown/mouseup events on the summary content
            let isSelecting = false;
            let selectStartX = 0;
            let selectStartY = 0;
            
            summaryContent.addEventListener('mousedown', function(event) {
                isSelecting = true;
                selectStartX = event.clientX;
                selectStartY = event.clientY;
                // Don't stop propagation here to allow for default text selection
            });
            
            summaryContent.addEventListener('mousemove', function(event) {
                if (isSelecting) {
                    // If user has moved a significant distance, they're probably selecting text
                    const dx = Math.abs(event.clientX - selectStartX);
                    const dy = Math.abs(event.clientY - selectStartY);
                    if (dx > 5 || dy > 5) {
                        event.stopPropagation();
                    }
                }
            });
            
            document.addEventListener('mouseup', function() {
                isSelecting = false;
            });
            
            // Prevent clicks inside the dropdown from closing it
            bodyDiv.addEventListener('click', function(event) {
                event.stopPropagation();
            });
            
            // Prevent clicks inside summary content from toggling (for text selection)
            summaryContent.addEventListener('click', function(event) {
                event.stopPropagation();
            });
            
            // Build the complete component
            headerDiv.appendChild(summaryDiv);
            headerDiv.appendChild(summaryContent);
            groupDiv.appendChild(headerDiv);
            groupDiv.appendChild(bodyDiv);
            
            // Replace existing element if present, otherwise append
            if (existingGroup) {
                chatMessages.replaceChild(groupDiv, existingGroup);
            } else {
                chatMessages.appendChild(groupDiv);
            }
            
            // Restore scroll position after rendering
            setTimeout(() => {
                if (previousBodyScrollTop > 0 && bodyDiv.classList.contains('expanded')) {
                    bodyDiv.scrollTop = previousBodyScrollTop;
                }
            }, 100);
        }

        // Modify fetchAISummary to cache results
        let aiSummaryCache = {};
        
        async function fetchAISummary(conversationId, messageId) {
            // Check cache first
            const cacheKey = `${conversationId}:${messageId}`;
            if (aiSummaryCache[cacheKey]) {
                return aiSummaryCache[cacheKey];
            }
            
            try {
                const response = await fetch(`/conversation/${conversationId}/ai_summary/${messageId}`);
                if (response.ok) {
                    const data = await response.json();
                    // Cache the result
                    aiSummaryCache[cacheKey] = data.summary;
                    return data.summary;
                }
                return null;
            } catch (error) {
                console.error('Error fetching summary:', error);
                return null;
            }
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
        
        // Store for keeping track of placeholder responses
        const placeholderResponses = {};
        
        // Send a message to AI in the current conversation
        function sendAIMessage() {
            if (!currentConversationId) return;
            
            const message = messageInput.value.trim();
            if (!message) return;
            
            fetch(`/conversation/${currentConversationId}/send`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    message,
                    to_ai: true
                }),
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    messageInput.value = '';
                    refreshMessages();
                    
                    // Always show the AI response indicator when sending directly to AI
                    showAIResponseIndicator();
                } else {
                    alert(data.message || 'Failed to send message to AI');
                }
            })
            .catch(error => {
                console.error('Error sending message to AI:', error);
                alert('Error sending message to AI. Please try again.');
            });
        }
        
        
        // Start polling for real responses
        function startPollingForRealResponses(clientMessageId) {
            if (!placeholderResponses[clientMessageId]) return;
            
            const realMessageId = placeholderResponses[clientMessageId].realMessageId;
            
            // Set up a recurring check
            const checkInterval = setInterval(() => {
                if (!currentConversationId || 
                    !placeholderResponses[clientMessageId] ||
                    !document.querySelector(`.placeholder-group[data-client-id="${clientMessageId}"]`)) {
                    // Stop polling if conversation changed or placeholder was removed
                    clearInterval(checkInterval);
                    return;
                }
                
                // Check for real responses
                fetch(`/conversation/${currentConversationId}/messages`)
                    .then(response => response.json())
                    .then(data => {
                        // Look for real AI responses
                        const aiResponses = [];
                        let targetMessageId = realMessageId;
                        
                        // If we don't have a real message ID yet, try to find it
                        if (!targetMessageId) {
                            // Look for messages matching our content
                            const messageContent = placeholderResponses[clientMessageId].messageContent;
                            for (const msg of data.messages) {
                                if (msg.is_self && msg.content === messageContent && msg.to_ai) {
                                    targetMessageId = msg.message_id;
                                    placeholderResponses[clientMessageId].realMessageId = targetMessageId;
                                    break;
                                }
                            }
                        }
                        
                        // Now look for responses to this message
                        if (targetMessageId) {
                            for (const msg of data.messages) {
                                if (msg.is_ai_response && msg.reply_to_message_id === targetMessageId) {
                                    aiResponses.push(msg);
                                }
                            }
                        }
                        
                        // If we found responses, update the placeholder
                        if (aiResponses.length > 0) {
                            updatePlaceholderWithResponses(clientMessageId, aiResponses);
                            
                            // Stop polling after we find responses
                            clearInterval(checkInterval);
                            
                            // Hide the indicator
                            hideAIResponseIndicator();
                            
                            // Remove this from placeholders as it's now a real response
                            delete placeholderResponses[clientMessageId];
                            
                            // Do a full refresh to sync everything
                            setTimeout(refreshMessages, 2000);
                        }
                    })
                    .catch(error => {
                        console.error('Error checking for responses:', error);
                    });
            }, 2000); // Check every 2 seconds
            
            // Set a timeout to stop polling after 1 minute
            setTimeout(() => {
                clearInterval(checkInterval);
            }, 60000);
        }
        
        // Check for AI responses in the background without destroying the UI
        function checkForAIResponses(tempId, realId) {
            if (!currentConversationId) return;
            
            fetch(`/conversation/${currentConversationId}/messages`)
                .then(response => response.json())
                .then(data => {
                    // Look for AI responses to our message
                    const aiResponses = [];
                    
                    data.messages.forEach(msg => {
                        if (msg.is_ai_response && 
                            (msg.reply_to_message_id === realId || 
                             msg.reply_to_message_id === tempId)) {
                            aiResponses.push(msg);
                        }
                    });
                    
                    // Update our temporary group if we found responses
                    if (aiResponses.length > 0) {
                        // Find the temporary group
                        const tempGroup = document.querySelector(`.ai-response-group[data-msg-id="${tempId}"]`) || 
                                          document.querySelector(`.ai-response-group[data-msg-id="${realId}"]`);
                        
                        if (tempGroup) {
                            // Update count
                            const countDisplay = tempGroup.querySelector('.ai-response-count');
                            if (countDisplay) {
                                countDisplay.innerHTML = `
                                    ${aiResponses.length} ${aiResponses.length > 1 ? 'answers' : 'answer'} <i class="fas fa-chevron-down dropdown-icon"></i>
                                `;
                            }
                            
                            // Update body content
                            const bodyDiv = tempGroup.querySelector('.ai-response-body');
                            if (bodyDiv) {
                                // Sort responses by timestamp
                                aiResponses.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
                                
                                let bodyContent = '';
                                aiResponses.forEach(response => {
                                    const aiOwner = response.ai_sender || 'Unknown';
                                    bodyContent += `
                                        <div class="ai-response-item">
                                            <div class="ai-response-from">
                                                <span>${aiOwner}'s AI</span>
                                                <span>${formatTimestamp(response.timestamp)}</span>
                                            </div>
                                            <div class="ai-response-content">${response.content}</div>
                                        </div>
                                    `;
                                });
                                
                                bodyDiv.innerHTML = bodyContent;
                            }
                            
                            // Update summary
                            const summaryContent = tempGroup.querySelector('.ai-summary-content');
                            if (summaryContent) {
                                if (aiResponses.length === 1) {
                                    // For a single response, just show the content
                                    summaryContent.innerHTML = `<div class="ai-summary-text">${aiResponses[0].content}</div>`;
                                } else if (aiResponses.length > 1) {
                                    // Try to get a summary for multiple responses
                                    fetchAISummary(currentConversationId, realId)
                                        .then(summary => {
                                            if (summary) {
                                                summaryContent.innerHTML = `<div class="ai-summary-text">${summary}</div>`;
                                            } else {
                                                summaryContent.innerHTML = '<div class="ai-summary-text">Multiple AI responses received. Click to expand.</div>';
                                            }
                                        })
                                        .catch(error => {
                                            console.error('Error fetching AI summary:', error);
                                            summaryContent.innerHTML = '<div class="ai-summary-text">Multiple AI responses received. Click to expand.</div>';
                                        });
                                }
                            }
                            
                            // Remove empty-group class
                            tempGroup.classList.remove('empty-group');
                            
                            // Hide AI response indicator
                            hideAIResponseIndicator();
                        }
                    }
                    
                    // If we still have no responses, check again in 3 seconds
                    if (aiResponses.length === 0) {
                        setTimeout(() => {
                            checkForAIResponses(tempId, realId);
                        }, 3000);
                    } else {
                        // Do a full refresh after we've updated the UI
                        setTimeout(refreshMessages, 5000);
                    }
                })
                .catch(error => {
                    console.error('Error checking for AI responses:', error);
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
        document.getElementById('send-ai-button').addEventListener('click', sendAIMessage);
        
        messageInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                // Default behavior is to send to humans
                sendMessage();
            }
        });
        
        // Add Ctrl+Enter to send to AI
        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                sendAIMessage();
                e.preventDefault();
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
        setInterval(refreshMessages, 15000);     // Refresh messages less frequently (every 15 seconds)

        // Add this function to the JavaScript section
        function getDeliveryStatusHtml(message) {
            if (!message.is_self) return '';
            
            if (message.delivered) {
                return '<span class="delivery-status status-delivered"><i class="fas fa-check"></i></span>';
            } else {
                // If we have delivery_percent, show a pie chart using conic-gradient
                if (message.delivery_percent !== undefined) {
                    const percent = message.delivery_percent;
                    return `
                        <span class="delivery-status">
                            <div class="pie-chart" title="${percent}% delivered" 
                                 style="background-image: conic-gradient(
                                        var(--accent-color) 0% ${percent}%, 
                                        var(--bg-accent) ${percent}% 100%
                                      );">
                            </div>
                            <span class="pie-percent-text">${percent}%</span>
                        </span>
                    `;
                } else {
                    // Fallback to the original gray dot
                    return '<span class="delivery-status status-pending"><i class="fas fa-circle"></i></span>';
                }
            }
        }

        // AI Settings functionality
        let aiSettings = {
            model: "llama3.2:latest",
            auto_respond: false,
            base_url: "http://localhost:11434"
        };
        
        function loadAISettings() {
            fetch('/ai_settings')
                .then(response => response.json())
                .then(data => {
                    aiSettings = data.settings;
                    
                    // Update UI
                    document.getElementById('ai-toggle').checked = data.enabled;
                    document.getElementById('ai-status').textContent = data.enabled ? 'Enabled' : 'Disabled';
                    document.getElementById('ai-model').value = aiSettings.model;
                    document.getElementById('ai-url').value = aiSettings.base_url;
                })
                .catch(error => {
                    console.error('Error loading AI settings:', error);
                });
        }
        
        function updateAISettings(settings) {
            fetch('/ai_settings', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(settings),
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    aiSettings = data.settings;
                    
                    // Update UI
                    document.getElementById('ai-toggle').checked = data.enabled;
                    document.getElementById('ai-status').textContent = data.enabled ? 'Enabled' : 'Disabled';
                    
                    // Close modal if open
                    closeAISettingsModal();
                } else {
                    alert(data.message || 'Failed to update AI settings');
                }
            })
            .catch(error => {
                console.error('Error updating AI settings:', error);
                alert('Error updating AI settings. Please try again.');
            });
        }
        
        function openAISettingsModal() {
            document.getElementById('ai-settings-modal').style.display = 'flex';
            document.getElementById('ai-model').value = aiSettings.model;
            document.getElementById('ai-url').value = aiSettings.base_url;
        }
        
        function closeAISettingsModal() {
            document.getElementById('ai-settings-modal').style.display = 'none';
        }
        
        // AI response indicator
        function showAIResponseIndicator() {
            const indicator = document.getElementById('ai-response-indicator');
            indicator.classList.add('show');
            
            // Auto-hide after 20 seconds (failsafe)
            setTimeout(() => {
                hideAIResponseIndicator();
            }, 20000);
        }
        
        function hideAIResponseIndicator() {
            const indicator = document.getElementById('ai-response-indicator');
            indicator.classList.remove('show');
        }
        
        // Set up event listeners
        document.addEventListener('DOMContentLoaded', function() {
            // ... existing DOMContentLoaded code ...
            
            // Load AI settings
            loadAISettings();
            
            // AI toggle listener
            document.getElementById('ai-toggle').addEventListener('change', function(e) {
                updateAISettings({ auto_respond: e.target.checked });
            });
            
            // AI settings button listener
            document.getElementById('ai-settings-btn').addEventListener('click', openAISettingsModal);
            
            // Save AI settings button
            document.getElementById('save-ai-settings-btn').addEventListener('click', function() {
                const model = document.getElementById('ai-model').value;
                const baseUrl = document.getElementById('ai-url').value;
                
                // Basic URL validation
                if (!baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
                    document.getElementById('ai-url-error').textContent = 'URL must start with http:// or https://';
                    document.getElementById('ai-url-error').style.display = 'block';
                    return;
                }
                
                document.getElementById('ai-url-error').style.display = 'none';
                
                // Get current enabled state
                const autoRespond = document.getElementById('ai-toggle').checked;
                
                updateAISettings({
                    model: model,
                    base_url: baseUrl,
                    auto_respond: autoRespond
                });
            });
            
            // Check for new message from server that has AI response indicator
            const originalRefreshMessages = refreshMessages;
            refreshMessages = function() {
                // Remember previous message count
                const prevMsgCount = currentConversationId ? 
                    document.querySelectorAll('#chat-messages .message').length : 0;
                
                // Call original function
                originalRefreshMessages();
                
                // After refreshing, check if new messages were added
                setTimeout(() => {
                    if (currentConversationId) {
                        const newMsgCount = document.querySelectorAll('#chat-messages .message').length;
                        if (newMsgCount > prevMsgCount) {
                            // Hide any active AI response indicator
                            hideAIResponseIndicator();
                        }
                    }
                }, 100);
            };
            
            // Show AI indicator when sending a message if AI is enabled
            const originalSendMessage = sendMessage;
            sendMessage = function() {
                // Call original function
                originalSendMessage();
                
                // Show indicator if AI is enabled
                if (document.getElementById('ai-toggle').checked) {
                    setTimeout(() => {
                        showAIResponseIndicator();
                    }, 500);
                }
            };
            
            // Add click handler for the Conversations link
            document.getElementById('conversations-link').addEventListener('click', function(e) {
                e.preventDefault();
                
                // Show welcome screen, hide chat interface
                welcomeScreen.style.display = 'flex';
                chatInterface.style.display = 'none';
                currentConversationId = null;
                
                // Update URL without reloading
                history.pushState({}, '', '/');
                
                // Clear active states in the sidebar
                document.querySelectorAll('.conversation-item').forEach(item => {
                    item.classList.remove('active');
                });
            });
        });
        
        // Add a function to ensure scrolling to the bottom of the chat
        function scrollToBottom() {
            if (chatMessages) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
                
                // Do it again after a short delay to ensure all content is rendered
                setTimeout(() => {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }, 100);
            }
        }
        
        // Modify the sendMessage function to scroll to bottom
        const originalSendMessage = sendMessage;
        sendMessage = function() {
            // Call original function
            originalSendMessage();
            
            // Scroll to bottom
            scrollToBottom();
        };
        
        // Also modify sendAIMessage to scroll to bottom
        const originalSendAIMessage = sendAIMessage;
        sendAIMessage = function() {
            // Call original function
            originalSendAIMessage();
            
            // Scroll to bottom
            scrollToBottom();
        };
        
        // Make sure to scroll to bottom when first selecting a conversation
        const originalSelectConversation = selectConversation;
        selectConversation = function(conversationId) {
            // Call original function
            originalSelectConversation(conversationId);
            
            // Scroll to bottom after a short delay to ensure messages are loaded
            setTimeout(scrollToBottom, 300);
        };

        // Helper function to reattach event listeners to reused response groups
        function reattachResponseGroupListeners(element, messageId, wasExpanded) {
            // Find the header element and body element
            const headerDiv = element.querySelector('.ai-response-header');
            const bodyDiv = element.querySelector('.ai-response-body');
            const summaryContent = element.querySelector('.ai-summary-content');
            
            if (!headerDiv || !bodyDiv) return;
            
            // Clear existing event listeners by cloning and replacing
            const newHeaderDiv = headerDiv.cloneNode(true);
            headerDiv.parentNode.replaceChild(newHeaderDiv, headerDiv);
            
            // Add click handler to toggle expanded state
            newHeaderDiv.addEventListener('click', function(event) {
                // Prevent event from bubbling up
                event.stopPropagation();
                
                // Always toggle regardless of where clicked
                
                // Toggle expanded state
                bodyDiv.classList.toggle('expanded');
                this.querySelector('.dropdown-icon')?.classList.toggle('open');
                
                // Store expansion state
                expandedResponseGroups[messageId] = bodyDiv.classList.contains('expanded');
                
                // Adjust the min-height of the entire group based on expansion state
                if (bodyDiv.classList.contains('expanded')) {
                    // Expanded: set taller min-height
                    element.style.minHeight = '500px';
                } else {
                    // Collapsed: set shorter min-height
                    element.style.minHeight = '220px';
                }
            });
            
            // For text selection in the summary content
            if (summaryContent) {
                let isSelecting = false;
                let selectStartX = 0;
                let selectStartY = 0;
                
                const newSummaryContent = summaryContent.cloneNode(true);
                summaryContent.parentNode.replaceChild(newSummaryContent, summaryContent);
                
                newSummaryContent.addEventListener('mousedown', function(event) {
                    isSelecting = true;
                    selectStartX = event.clientX;
                    selectStartY = event.clientY;
                    // Don't stop propagation here
                });
                
                newSummaryContent.addEventListener('mousemove', function(event) {
                    if (isSelecting) {
                        // If user has moved a significant distance, they're probably selecting text
                        const dx = Math.abs(event.clientX - selectStartX);
                        const dy = Math.abs(event.clientY - selectStartY);
                        if (dx > 5 || dy > 5) {
                            event.stopPropagation();
                        }
                    }
                });
            }
            
            // Prevent clicks inside the dropdown from closing it
            bodyDiv.addEventListener('click', function(event) {
                event.stopPropagation();
            });
            
            // If it was expanded before, make sure it stays expanded
            if (wasExpanded) {
                bodyDiv.classList.add('expanded');
                element.querySelector('.dropdown-icon')?.classList.add('open');
                expandedResponseGroups[messageId] = true;
                element.style.minHeight = '500px'; // Set the expanded height
            } else {
                element.style.minHeight = '220px'; // Set the collapsed height
            }
        }
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
