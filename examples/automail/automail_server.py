from __future__ import annotations

from datetime import datetime, timezone
import os
from queue import Queue
import threading
from collections import defaultdict

from flask import Flask, render_template, jsonify
from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline

# Initialize Flask app
app = Flask(__name__)

# Create a queue for new messages
message_queue = Queue()

# Store conversation history
conversation_history = defaultdict(list)

box = SyftEvents("pingpong")

# Disable PyTorch distributed modules to avoid errors
os.environ["USE_DISTRIBUTED"] = "0"

# Initialize the model - using Blenderbot for better conversations
try:
    model_name = "facebook/blenderbot-400M-distill"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    generator = pipeline('text2text-generation',
                        model=model,
                        tokenizer=tokenizer,
                        device='cpu')
    model_loaded = True
except Exception as e:
    logger.error(f"Failed to load model: {e}")
    model_loaded = False

class PingRequest(BaseModel):
    """Request to send a ping."""
    msg: str = Field(description="Message content")
    ts: datetime = Field(description="Timestamp of the message")


class PongResponse(BaseModel):
    """Response to a ping request."""
    msg: str = Field(description="Response message")
    ts: datetime = Field(description="Timestamp of the response")


def format_conversation(history: list) -> str:
    """Format conversation history into a single context string."""
    context = ""
    for entry in history[-5:]:  # Keep last 5 messages for context
        role = "Human" if entry["is_human"] else "Assistant"
        context += f"{role}: {entry['message']}\n"
    return context.strip()


def get_ai_response(message: str, conversation_id: str) -> str:
    """Get a response from the local AI model with conversation context."""
    try:
        # Add the new message to history
        conversation_history[conversation_id].append({
            "message": message,
            "is_human": True
        })
        
        # Format the conversation context with limited history
        history = conversation_history[conversation_id]
        
        # Build a clean conversation format for the model
        # Limit to just last 4 turns (2 exchanges) to avoid context overflow
        conversation_text = ""
        
        # Include only the most recent exchanges
        for entry in history[-4:]:  # Much shorter context window
            prefix = "Human: " if entry["is_human"] else "Assistant: "
            # Also limit the length of each message
            entry_msg = entry["message"]
            if len(entry_msg) > 100:  # Truncate long messages
                entry_msg = entry_msg[:100] + "..."
            conversation_text += prefix + entry_msg + "\n"
            
        # Generate response with a simpler prompt format
        if model_loaded:
            try:
                # Keep the prompt short
                prompt = conversation_text + "Assistant: "
                
                # Check if prompt is too long and truncate if needed
                if len(prompt) > 512:  # Conservative token limit
                    logger.warning("Prompt too long, truncating")
                    prompt = prompt[-512:]  # Keep the last 512 chars
                
                outputs = generator(
                    prompt,
                    max_length=50,  # Shorter response
                    min_length=5,
                    temperature=0.7, 
                    do_sample=True,
                    num_return_sequences=1
                )
                
                # Just get the raw output
                full_response = outputs[0]['generated_text'].strip()
                
                # Simple response extraction
                response = full_response
                # If we have the assistant prefix, try to extract just the response
                if "Assistant: " in full_response:
                    response = full_response.split("Assistant: ")[-1].strip()
                
                # Fallback
                if not response:
                    response = "I'm not sure I understand. Could you explain that differently?"
            except Exception as e:
                logger.error(f"Error generating AI response: {e}")
                response = "Sorry, I'm having trouble with this conversation."
        else:
            # Fallback responses
            response = "I understand. Please continue."
        
        # Add the response to history
        conversation_history[conversation_id].append({
            "message": response,
            "is_human": False
        })
            
        return response
    except Exception as e:
        logger.error(f"Error in response generation: {e}")
        return "Sorry, I'm having technical difficulties right now."


@box.on_request("/ping")
def pong(ping: PingRequest, ctx: Request) -> PongResponse:
    """Respond to a message with an AI-generated response."""
    logger.info(f"Got message - {ping}")
    
    # Simplified sender extraction
    sender_email = "user@automail"  # Default fallback
    
    # Get AI response with conversation history
    response = get_ai_response(ping.msg, sender_email)
    timestamp = datetime.now(timezone.utc)
    
    # Add to monitoring queue
    message_queue.put({
        "from": sender_email,
        "message": ping.msg,
        "response": response,
        "timestamp": timestamp.strftime("%H:%M:%S")
    })
    
    return PongResponse(
        msg=response,
        ts=timestamp,
    )


@app.route('/')
def home():
    """Render the monitoring interface."""
    return render_template('monitor.html')


@app.route('/messages')
def get_messages():
    """Get new messages from the queue."""
    messages = []
    while not message_queue.empty():
        messages.append(message_queue.get())
    return jsonify(messages)


def run_server():
    """Run the RPC server."""
    try:
        print("Running local AI chat server for", box.app_rpc_dir)
        box.run_forever()
    except Exception as e:
        print(e)


if __name__ == "__main__":
    print("Loading AI model... this may take a moment...")
    if not model_loaded:
        print("Warning: AI model could not be loaded. Running in simplified mode.")
    
    # Start the RPC server in a separate thread
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Run the Flask app
    app.run(debug=False, port=5001)  # Using a different port than the client
