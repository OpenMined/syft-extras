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
    selected_files: List[Dict[str, str]] = None  # List of files with user and path info
    
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
            "reply_to_message_id": self.reply_to_message_id,
            "selected_files": self.selected_files
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
    def __init__(self, base_url="http://localhost:11434", model="llama3.2:latest", client=None):
        self.base_url = base_url
        self.model = model
        # The API endpoint is just /api/generate
        self.api_url = f"{self.base_url}/api/generate"
        self.client = client  # Store the client reference
        
        # Print client details for debugging
        if client:
            print(f"OllamaHandler initialized with client: {client.email}")
            print(f"Client properties: {dir(client)}")
            if hasattr(client, 'workspace'):
                print(f"Workspace properties: {dir(client.workspace)}")
                print(f"Datasites path: {client.workspace.datasites}")
        else:
            print("OllamaHandler initialized with no client reference")
        
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
            print(f"Prompt length: {len(prompt)} characters")
            print(f"Prompt start: {prompt[:200]}...")
            print(f"Prompt end: ...{prompt[-200:]}")
            
            response = requests.post(self.api_url, json=payload)
            logger.info(f"Ollama API response status: {response.status_code}")
            print(f"Ollama response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"Response received, length: {len(result.get('response', ''))}")
                return result.get("response", "Sorry, I couldn't generate a response.")
            else:
                # Try to get more details from the error response
                try:
                    error_details = response.json()
                    print(f"Error response: {error_details}")
                    return f"Error from Ollama API: {response.status_code} - {error_details.get('error', 'Unknown error')}"
                except:
                    print(f"Could not parse error response, raw: {response.text}")
                    return f"Error from Ollama API: {response.status_code}"
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {str(e)}")
            print(f"Exception connecting to Ollama: {str(e)}")
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
            
            # Include file information if present
            selected_files = msg.get("selected_files", [])
            print("Selected files: ", selected_files)
            if selected_files:
                file_info = "\n[Referenced files: "
                file_names = []
                for file in selected_files:
                    path = file.get("path", "")
                    if path:
                        # Extract just the filename from the path
                        file_name = path.split('/')[-1]
                        file_names.append(file_name)
                
                if file_names:
                    file_info += ", ".join(file_names)
                    prompt += file_info + "]\n"
        
        # Add the current message and request
        prompt += f"\n{sender}: {message}\n\n"
        
        # Check if there are files to include in the latest message
        latest_msg = conversation_history[-1] if conversation_history else None
        if latest_msg:
            # Debug the latest message structure
            print(f"\n--- Processing files from message: {latest_msg.get('message_id')} ---")
            selected_files = latest_msg.get("selected_files", [])
            print(f"Selected files: {json.dumps(selected_files, indent=2)}")
            
            if selected_files:
                prompt += "Referenced file contents:\n\n"
                files_included = 0
                
                # Debug client information if available
                if self.client:
                    print(f"Client email: {self.client.email}")
                    print(f"Client workspace: {hasattr(self.client, 'workspace')}")
                    if hasattr(self.client, 'workspace'):
                        print(f"Datasites path: {self.client.workspace.datasites}")
                        print(f"Directory exists: {os.path.exists(str(self.client.workspace.datasites))}")
                else:
                    print("No client object available!")
                
                for file_info in selected_files:
                    # Debug file info structure
                    print(f"\nProcessing file: {json.dumps(file_info, indent=2) if isinstance(file_info, dict) else file_info}")
                    
                    # Handle both dict and string format (backward compatibility)
                    if isinstance(file_info, dict):
                        file_path = file_info.get("path", "")
                        user_email = file_info.get("user", "")
                        print(f"Dict format - path: {file_path}, user: {user_email}")
                    else:
                        # If it's just a string path, use the sender as the user
                        file_path = file_info
                        user_email = sender
                        print(f"String format - path: {file_path}, using sender as user: {user_email}")
                    
                    # Make sure we have both path and user
                    if not file_path:
                        print("Skipping file with empty path")
                        continue
                    
                    # Try multiple approaches to locate the file
                    possible_paths = []
                    
                    # 1. Direct path as provided
                    possible_paths.append(file_path)
                    print(f"1. Direct path: {file_path}")
                    
                    # 2. Using SyftBox/datasites path structure
                    if user_email:
                        datasite_path = f"SyftBox/datasites/{user_email}/{file_path}"
                        possible_paths.append(datasite_path)
                        print(f"2. SyftBox path: {datasite_path}")
                        
                        # Also try with home directory
                        home_path = os.path.expanduser(f"~/SyftBox/datasites/{user_email}/{file_path}")
                        possible_paths.append(home_path)
                        print(f"3. Home SyftBox path: {home_path}")
                        
                    # 4. Use the client's paths when available
                    if self.client:
                        try:
                            print(f"Using client paths for {self.client.email}")
                            
                            # For user's own files
                            if user_email == self.client.email:
                                # Try using my_datasite property
                                if hasattr(self.client, 'my_datasite'):
                                    user_path = self.client.my_datasite / file_path
                                    possible_paths.append(str(user_path))
                                    print(f"4. User's own datasite path: {user_path}")
                            
                            # Try using workspace.datasites
                            if hasattr(self.client, 'workspace') and hasattr(self.client.workspace, 'datasites'):
                                datasite_path = self.client.workspace.datasites / user_email / file_path
                                possible_paths.append(str(datasite_path))
                                print(f"5. Workspace datasite path: {datasite_path}")
                                
                                # Also try with just the base datasite path + file path
                                simple_path = self.client.workspace.datasites / file_path
                                possible_paths.append(str(simple_path))
                                print(f"6. Simple datasite path: {simple_path}")
                            
                            # If client has a config with data_dir
                            if hasattr(self.client, 'config') and hasattr(self.client.config, 'data_dir'):
                                data_dir_path = self.client.config.data_dir / "datasites" / user_email / file_path
                                possible_paths.append(str(data_dir_path))
                                print(f"7. Config data_dir path: {data_dir_path}")
                        except Exception as e:
                            print(f"Error resolving client paths: {e}")
                    
                    # 8. Try with absolute path from current directory
                    abs_path = os.path.abspath(file_path)
                    possible_paths.append(abs_path)
                    print(f"8. Absolute path: {abs_path}")
                    
                    # 9. Try current directory + file_path
                    cwd_path = os.path.join(os.getcwd(), file_path)
                    possible_paths.append(cwd_path)
                    print(f"9. CWD path: {cwd_path}")
                    
                    # Log all paths we're going to try
                    print(f"Will try these paths in order:")
                    for i, path in enumerate(possible_paths):
                        print(f"  {i+1}. {path}")
                    
                    # Try each path until we find one that works
                    file_read = False
                    for try_path in possible_paths:
                        print(f"\nAttempting to read file from: {try_path}")
                        try:
                            if os.path.exists(try_path):
                                print(f"Path exists: {try_path}")
                                if os.path.isfile(try_path):
                                    print(f"SUCCESS: Found file at: {try_path}")
                                    try:
                                        with open(try_path, 'r') as f:
                                            file_content = f.read()
                                            filename = os.path.basename(file_path)
                                            content_preview = file_content[:100] + "..." if len(file_content) > 100 else file_content
                                            print(f"Read file content ({len(file_content)} chars): {content_preview}")
                                            
                                            # Add file content to prompt with clear delimitation
                                            prompt += f"--- File: {filename} ---\n{file_content}\n--- End of {filename} ---\n\n"
                                            files_included += 1
                                            file_read = True
                                            break
                                    except UnicodeDecodeError as ude:
                                        print(f"UnicodeDecodeError reading file: {ude}")
                                        try:
                                            # Try with different encoding
                                            with open(try_path, 'r', encoding='latin1') as f:
                                                file_content = f.read()
                                                filename = os.path.basename(file_path)
                                                prompt += f"--- File: {filename} ---\n{file_content}\n--- End of {filename} ---\n\n"
                                                files_included += 1
                                                file_read = True
                                                break
                                        except Exception as e2:
                                            print(f"Second attempt failed: {e2}")
                                else:
                                    print(f"Path exists but is not a file: {try_path}")
                            else:
                                print(f"Path does not exist: {try_path}")
                        except PermissionError as pe:
                            print(f"Permission error reading file {try_path}: {pe}")
                        except Exception as e:
                            print(f"Unexpected error reading file {try_path}: {e}")
                    
                    if not file_read:
                        print(f"FAILED: Could not find or read file: {file_path}")
                        prompt += f"--- File: {os.path.basename(file_path)} ---\n(File could not be accessed)\n--- End of file ---\n\n"
                
                print(f"\nIncluded {files_included} of {len(selected_files)} files in the prompt")
        
        prompt += "Please write a helpful and friendly response:"
        
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


# Move the class definition to before ChatClient
class FileSelectionStorage:
    """Simple storage for file selections"""
    def __init__(self, chat_client):
        self.chat_client = chat_client
        self.file_selections = {}  # conversation_id -> {user_email -> [file_paths]}
    
    def get_conversation(self, conversation_id):
        """Get conversation with file selections metadata"""
        conversation = self.chat_client.get_conversation(conversation_id)
        if not conversation:
            return None
        
        # Convert to dict with metadata
        result = {
            "id": conversation.id,
            "name": conversation.name,
            "recipients": conversation.recipients,
            "created_by": conversation.created_by,
            "created_at": conversation.created_at.isoformat(),
            "message_count": len(conversation.messages),
            "metadata": {
                "selected_files": self.file_selections.get(conversation_id, {})
            }
        }
        return result
    
    def update_conversation(self, conversation_data):
        """Update file selections for a conversation"""
        conversation_id = conversation_data.get("id")
        if not conversation_id:
            return False
        
        # Extract and store the file selections
        metadata = conversation_data.get("metadata", {})
        selected_files = metadata.get("selected_files", {})
        
        # Update our file selections storage
        self.file_selections[conversation_id] = selected_files
        return True


# Class to handle chat functionality
class ChatClient:
    def __init__(self, config_path=None):
        self.client = Client.load(config_path)
        self.running = True
        self.conversations = {}  # Dictionary of conversation_id -> Conversation
        self.conversation_lock = threading.Lock()
        
        # AI auto-response settings
        self.ai_enabled = False
        self.ai_settings = {
            "model": "llama3.2:latest",
            "auto_respond": False,
            "base_url": "http://localhost:11434"
        }
        
        # Create Ollama handler with client reference
        self.ollama_handler = OllamaHandler(
            base_url=self.ai_settings.get("base_url", "http://localhost:11434"),
            model=self.ai_settings.get("model", "llama3.2:latest"),
            client=self.client  # Pass the client instance
        )
        
        # Add storage for file selections
        self.storage = FileSelectionStorage(self)
        
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
                "reply_to_message_id": getattr(message, "reply_to_message_id", None),  # Include the reply_to_message_id
                "selected_files": getattr(message, "selected_files", [])  # Include selected files
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
                        model=self.ai_settings.get("model", "llama3.2"),
                        client=self.client  # Pass the client instance
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
            
            # Find the original message to get its selected files
            original_selected_files = []
            original_sender = ""
            if original_message_id:
                for msg in history:
                    if msg.get("message_id") == original_message_id:
                        original_selected_files = msg.get("selected_files", [])
                        original_sender = msg.get("sender", "")
                        logger.info(f"Found original message. Selected files: {original_selected_files}")
                        break
            
            # Fix selected_files structure if needed
            processed_files = []
            for file_info in original_selected_files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    # Make sure it has a user field
                    if 'user' not in file_info:
                        file_info['user'] = original_sender or sender
                    processed_files.append(file_info)
                elif isinstance(file_info, str):
                    processed_files.append({
                        'path': file_info,
                        'user': original_sender or sender
                    })
            
            # Generate AI response
            prompt = self.ollama_handler.format_chat_prompt(sender, message, history)
            logger.info(f"Generated prompt length: {len(prompt)} characters")
            ai_response = self.ollama_handler.generate_response(prompt)
            
            # Small delay to make the conversation feel more natural
            time.sleep(1.5)
            
            # Send the response with the same selected files as the original message
            self.send_message(
                conversation_id, 
                ai_response, 
                to_ai=False,  # This is from AI, not to AI
                is_ai_response=True,
                ai_sender=self.client.email, # The owner of this AI
                reply_to_message_id=original_message_id, # Link to original message
                selected_files=processed_files  # Use the properly formatted files
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
                model=self.ai_settings.get("model", "llama3.2:latest"),
                client=self.client  # Pass the client instance
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
                    reply_to_message_id: str = None, selected_files: List[Dict] = None):
        """Send a message to all recipients in a conversation"""
        if not content or not conversation_id:
            return False
        
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return False
        
        # Generate a unique message ID
        message_id = str(uuid.uuid4())
        
        # Ensure selected_files is properly formatted with both path and user info
        processed_files = []
        if selected_files:
            for file_info in selected_files:
                if isinstance(file_info, dict) and 'path' in file_info:
                    # Make sure each file has a user field
                    if 'user' not in file_info:
                        file_info['user'] = self.client.email
                    processed_files.append(file_info)
                elif isinstance(file_info, str):
                    # Convert string paths to proper dict format
                    processed_files.append({
                        'path': file_info,
                        'user': self.client.email
                    })
        
        logger.info(f"Sending message with {len(processed_files)} selected files: {processed_files}")
        
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
            "reply_to_message_id": reply_to_message_id,
            "selected_files": processed_files  # Use the processed file list
        }
        
        conversation.add_message(formatted_message)
        
        # Create a full list of all participants (including self)
        all_participants = conversation.recipients.copy()
        all_participants.append(self.client.email)
        
        # Filter out "System" from recipients list - System isn't a real user
        actual_recipients = [r for r in conversation.recipients if r != "System"]
        
        # Total recipients count for percentage calculation
        total_recipients = len(actual_recipients)
        
        # Send message to each recipient (except System)
        for recipient in actual_recipients:
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
                        reply_to_message_id=reply_to_message_id,
                        selected_files=selected_files  # Include selected files
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
        selected_files = data.get('selected_files', [])  # Get selected files from request
        
        if message and chat_client.send_message(conversation_id, message, to_ai=to_ai, selected_files=selected_files):
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
    
    @app.route('/filesystem')
    def get_filesystem():
        path = request.args.get('path', '')
        user_email = request.args.get('user', chat_client.client.email)
        
        # Sanitize and validate path to prevent directory traversal attacks
        try:
            # Get the base directory for the specified user
            if user_email == chat_client.client.email:
                # For current user, use their own datasite
                base_dir = chat_client.client.my_datasite
            else:
                # For other users, use the datasite directory for that user
                # We'll access the parent directory of the user's datasite
                datasite_parent = chat_client.client.my_datasite.parent
                base_dir = datasite_parent / user_email
                
                # Check if this directory exists
                if not base_dir.exists() or not base_dir.is_dir():
                    return jsonify({"error": f"Datasite directory for {user_email} not found"}), 404
            
            # Convert relative path to absolute path within the user's directory
            if path:
                target_dir = (base_dir / path.lstrip('/')).resolve()
                # Ensure the target directory is still within the base directory
                if not str(target_dir).startswith(str(base_dir)):
                    return jsonify({"error": "Access denied: path is outside user directory"}), 403
            else:
                target_dir = base_dir
                
            # Get directory contents
            files = []
            for item in target_dir.iterdir():
                # Skip hidden files
                if item.name.startswith('.'):
                    continue
                    
                rel_path = str(item.relative_to(base_dir))
                files.append({
                    "name": item.name,
                    "path": rel_path,
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if not item.is_dir() else 0,
                    "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat()
                })
                
            return jsonify({"files": files})
        
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/update_file_selections', methods=['POST'])
    def update_file_selections():
        data = request.json
        conversation_id = data.get('conversation_id')
        user_email = data.get('user_email')
        selected_files = data.get('selected_files', [])
        
        if not conversation_id or not user_email:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        
        try:
            # Get the conversation
            conversation = chat_client.storage.get_conversation(conversation_id)
            if not conversation:
                return jsonify({'status': 'error', 'message': 'Conversation not found'}), 404
            
            # Initialize metadata if it doesn't exist
            if 'metadata' not in conversation:
                conversation['metadata'] = {}
            
            # Initialize selected_files if it doesn't exist
            if 'selected_files' not in conversation['metadata']:
                conversation['metadata']['selected_files'] = {}
            
            # Update the selected files for this user
            conversation['metadata']['selected_files'][user_email] = selected_files
            
            # Save the updated conversation
            chat_client.storage.update_conversation(conversation)
            
            return jsonify({'status': 'success', 'message': 'File selections updated'})
        
        except Exception as e:
            logger.error(f"Error updating file selections: {e}")
            return jsonify({'status': 'success', 'message': 'File selections processed', 
                           'note': 'Storage error occurred but selection was received'})
    
    @app.route('/conversation/<conversation_id>/file_selections', methods=['GET'])
    def get_file_selections(conversation_id):
        """Get file selections for a conversation"""
        user_email = request.args.get('user')
        
        if not conversation_id or not user_email:
            return jsonify({'status': 'error', 'message': 'Missing required parameters'}), 400
        
        try:
            # Get the conversation
            conversation = chat_client.storage.get_conversation(conversation_id)
            if not conversation:
                # Return empty selections if conversation not found
                return jsonify({
                    'status': 'success',
                    'selected_files': []
                })
            
            # Get selections for this user
            metadata = conversation.get('metadata', {})
            selected_files_map = metadata.get('selected_files', {})
            selected_files = selected_files_map.get(user_email, [])
            
            return jsonify({
                'status': 'success',
                'selected_files': selected_files
            })
        
        except Exception as e:
            logger.error(f"Error getting file selections: {e}")
            # Return empty selections on error to allow UI to continue
            return jsonify({
                'status': 'success',
                'selected_files': []
            })
    
    return app


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
