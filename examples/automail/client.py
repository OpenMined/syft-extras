from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


@box.on_request("/message")
def handle_message(message: ChatMessage, ctx: Request) -> ChatResponse:
    """Handle incoming chat messages."""
    sender = message.sender if message.sender else "Unknown"
    
    # Handle timestamp formatting - might be string or datetime
    if isinstance(message.ts, datetime):
        time_str = message.ts.strftime('%H:%M:%S')
    else:
        # If ts is a string, just use it directly
        time_str = str(message.ts)
    
    print(f"\n[{time_str}] {sender}: {message.content}")
    print("You: ", end="", flush=True)
    return ChatResponse(
        status="received",
        ts=datetime.now(timezone.utc),
    )


def send_message(recipient: str, content: str) -> None:
    """Send a chat message to another user."""
    client = Client.load()
    
    # Create the message
    message = ChatMessage(content=content, sender=client.email)
    
    try:
        future = rpc.send(
            url=f"syft://{recipient}/api_data/automail/rpc/message",
            body=message,
            expiry="5m",
            cache=False,
        )
        
        # Wait for the response
        response = future.wait(timeout=30)
        response.raise_for_status()
        chat_response = response.model(ChatResponse)
        
        # Optional: log the delivery status
        logger.debug(f"Message delivered: {chat_response.status}")
    except Exception as e:
        print(f"\nError sending message: {e}")


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


def main():
    parser = argparse.ArgumentParser(description="Peer-to-peer chat client")
    parser.add_argument("recipient", help="Recipient's email address")
    args = parser.parse_args()
    
    client = Client.load()
    print(f"Logged in as: {client.email}")
    print(f"Chatting with: {args.recipient}")
    print("Type 'exit' to quit")
    print("-" * 50)
    
    # Start the server to listen for incoming messages
    server_thread = start_server()
    time.sleep(1)  # Give the server a moment to start
    
    try:
        while True:
            message = input("You: ")
            if message.lower() == "exit":
                break
                
            # Send the message
            send_message(args.recipient, message)
    except KeyboardInterrupt:
        print("\nExiting chat...")
    finally:
        print("Chat session ended.")
        # The server thread is daemon, so it will exit when the main thread exits


if __name__ == "__main__":
    main()
