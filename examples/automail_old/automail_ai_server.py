from __future__ import annotations

from datetime import datetime, timezone
import os
import json
import uuid
import requests
from pathlib import Path
from collections import defaultdict

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request

# Create log directory if it doesn't exist
LOGS_DIR = Path("automail_logs")
LOGS_DIR.mkdir(exist_ok=True)
MESSAGE_LOG = LOGS_DIR / "message_log.json"
OVERRIDE_LOG = LOGS_DIR / "override_log.json"

# Store conversation history
conversation_history = defaultdict(list)

box = SyftEvents("pingpong")

# Ollama API settings
OLLAMA_API_BASE = "http://localhost:11434/api"
OLLAMA_MODEL = "llama3.2"  # Updated default model name

# Check if Ollama is running
try:
    logger.info("Checking Ollama service...")
    response = requests.get(f"{OLLAMA_API_BASE}/tags")
    if response.status_code == 200:
        available_models = [model["name"] for model in response.json().get("models", [])]
        logger.info(f"Available models: {available_models}")
        
        # Try to find a suitable model in this order of preference
        preferred_models = ["llama3.2", "llama3", "llama3:latest", "llama3.2:latest", 
                           "llama2", "mistral", "gemma"]
        
        model_found = False
        for model in preferred_models:
            if model in available_models:
                OLLAMA_MODEL = model
                logger.info(f"Using model: {OLLAMA_MODEL}")
                model_loaded = True
                model_found = True
                break
                
        if not model_found:
            if available_models:
                # Just use the first available model
                OLLAMA_MODEL = available_models[0]
                logger.info(f"No preferred model found. Using available model: {OLLAMA_MODEL}")
                model_loaded = True
            else:
                logger.warning("No models available in Ollama")
                logger.info("Please pull a model with: 'ollama pull llama3.2'")
                model_loaded = False
    else:
        logger.error("Ollama API responded with an error")
        model_loaded = False
except Exception as e:
    logger.error(f"Failed to connect to Ollama: {e}")
    logger.info("Please make sure Ollama is installed and running")
    logger.info("Install from: https://ollama.com/download")
    logger.info("Then run: 'ollama serve' and 'ollama pull llama3.2'")
    model_loaded = False

class PingRequest(BaseModel):
    """Request to send a ping."""
    msg: str = Field(description="Message content")
    ts: datetime = Field(description="Timestamp of the message")


class PongResponse(BaseModel):
    """Response to a ping request."""
    msg: str = Field(description="Response message")
    ts: datetime = Field(description="Timestamp of the response")
    msg_id: str = Field(description="Unique message ID for potential updates")


def load_overrides():
    """Load any human overrides to AI responses."""
    if OVERRIDE_LOG.exists():
        try:
            with open(OVERRIDE_LOG, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def check_for_override(message_id):
    """Check if there's a human override for this message."""
    overrides = load_overrides()
    return overrides.get(message_id)


def log_message(sender, message, response, timestamp, message_id):
    """Log the message to a file for the monitoring server to read."""
    try:
        # Read existing log if it exists
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                except json.JSONDecodeError:
                    log_data = []
        else:
            log_data = []
            
        # Add new message with message_id
        log_data.append({
            "id": message_id,
            "from": sender,
            "message": message,
            "response": response,
            "timestamp": timestamp,
            "ai_generated": True  # Flag to indicate this was AI-generated
        })
        
        # Keep only the last 100 messages
        if len(log_data) > 100:
            log_data = log_data[-100:]
            
        # Write back to file
        with open(MESSAGE_LOG, "w") as f:
            json.dump(log_data, f)
    except Exception as e:
        logger.error(f"Error logging message: {e}")


def get_ai_response(message: str, conversation_id: str) -> (str, str):
    """Get a response from Ollama with conversation context."""
    try:
        # Generate a unique message ID
        message_id = str(uuid.uuid4())
        
        # Add the new message to history
        conversation_history[conversation_id].append({
            "message": message,
            "is_human": True
        })
        
        # Format the conversation context with limited history
        history = conversation_history[conversation_id]
        
        # Build a conversation format for Ollama
        # Ollama uses a specific chat format
        messages = []
        
        # Include the recent exchanges (up to 8 messages)
        for entry in history[-8:]:
            role = "user" if entry["is_human"] else "assistant"
            # Truncate very long messages
            content = entry["message"]
            if len(content) > 500:  # Truncate long messages
                content = content[:500] + "..."
            
            messages.append({"role": role, "content": content})
        
        # Generate response with Ollama
        if model_loaded:
            try:
                # Call Ollama API for chat completion
                response = requests.post(
                    f"{OLLAMA_API_BASE}/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "options": {
                            "temperature": 0.7,
                            "top_p": 0.9,
                        },
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    # Extract the assistant's response from Ollama
                    response_data = response.json()
                    if "message" in response_data and "content" in response_data["message"]:
                        extracted_response = response_data["message"]["content"].strip()
                    else:
                        extracted_response = "I couldn't generate a proper response. Could you try again?"
                else:
                    logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                    extracted_response = "Sorry, there was an error communicating with my AI backend."
                
            except Exception as e:
                logger.error(f"Error generating Ollama response: {e}")
                extracted_response = "Sorry, I'm having trouble with this conversation."
        else:
            # Fallback responses if Ollama not available
            extracted_response = "I understand your message, but my AI model isn't currently available. Please make sure Ollama is running and has the llama3 model."
        
        # Add the response to history
        conversation_history[conversation_id].append({
            "message": extracted_response,
            "is_human": False
        })
            
        return extracted_response, message_id
    except Exception as e:
        logger.error(f"Error in response generation: {e}")
        return "Sorry, I'm having technical difficulties right now.", str(uuid.uuid4())


@box.on_request("/ping")
def pong(ping: PingRequest, ctx: Request) -> PongResponse:
    """Respond to a message with an AI-generated response."""
    logger.info(f"Got message - {ping}")
    
    # Simplified sender extraction
    sender_email = "user@automail"  # Default fallback
    
    # Get AI response with conversation history
    response, message_id = get_ai_response(ping.msg, sender_email)
    timestamp = datetime.now(timezone.utc)
    
    # Check if there's a human override for this message ID
    # (this will be empty for new messages)
    override = check_for_override(message_id)
    if override:
        response = override
    
    # Log the message for the monitoring server
    log_message(
        sender_email, 
        ping.msg,
        response,
        timestamp.strftime("%H:%M:%S"),
        message_id
    )
    
    return PongResponse(
        msg=response,
        ts=timestamp,
        msg_id=message_id
    )


# New endpoint to update a response
@box.on_request("/update_response")
def update_response(req: dict, ctx: Request) -> dict:
    """Update an AI response with a human-provided alternative."""
    message_id = req.get("message_id")
    new_response = req.get("response")
    
    if not message_id or not new_response:
        return {"success": False, "error": "Missing message_id or response"}
    
    try:
        # Load existing overrides
        overrides = load_overrides()
        
        # Add the new override
        overrides[message_id] = new_response
        
        # Save back to file
        with open(OVERRIDE_LOG, "w") as f:
            json.dump(overrides, f)
        
        # Update the message log too
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        if entry.get("id") == message_id:
                            entry["response"] = new_response
                            entry["ai_generated"] = False  # Mark as human override
                    
                    with open(MESSAGE_LOG, "w") as f:
                        json.dump(log_data, f)
                except (json.JSONDecodeError, IOError):
                    pass
        
        logger.info(f"Updated response for message {message_id}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error updating response: {e}")
        return {"success": False, "error": str(e)}


@box.on_request("/get_updates")
def get_updates(req: dict, ctx: Request) -> dict:
    """Get any updated responses for a list of message IDs."""
    message_ids = req.get("message_ids", [])
    
    if not message_ids:
        return {"updates": {}}
    
    try:
        # Load existing overrides
        overrides = load_overrides()
        
        # Filter to just the requested message IDs
        updates = {msg_id: overrides.get(msg_id) for msg_id in message_ids if msg_id in overrides}
        
        # Also check the message log for human-edited messages
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        if entry.get("id") in message_ids and entry.get("ai_generated") is False:
                            # This is a human-edited message
                            updates[entry.get("id")] = entry.get("response")
                except (json.JSONDecodeError, IOError):
                    pass
        
        return {"updates": updates}
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return {"updates": {}}


def run_server():
    """Run the RPC server."""
    try:
        print("Running local AI chat server with Ollama for", box.app_rpc_dir)
        box.run_forever()
    except Exception as e:
        print(f"Server error: {e}")


if __name__ == "__main__":
    # Clean up any existing message log
    if MESSAGE_LOG.exists():
        MESSAGE_LOG.unlink()
    
    # Start the server
    run_server() 