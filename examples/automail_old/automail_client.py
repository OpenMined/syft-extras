from __future__ import annotations

import time
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel
from syft_core import Client
from syft_rpc import rpc


class MessageRequest(BaseModel):
    """A message sent from one user to another."""
    message: str
    timestamp: datetime = datetime.now(timezone.utc)
    message_id: str = ""


class MessageResponse(BaseModel):
    """Response to a message, which may be AI-generated."""
    message: str
    timestamp: datetime
    message_id: str
    ai_generated: bool


class ContactListRequest(BaseModel):
    """Request to get the list of available contacts."""
    pass


class ContactListResponse(BaseModel):
    """Response containing the list of available contacts."""
    contacts: List[str]


@dataclass
class Message:
    """A message sent or received."""
    content: str
    sender: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_id: str = field(default_factory=lambda: "")
    ai_generated: bool = False
    is_sent: bool = False


class AutoMailClient:
    def __init__(self):
        self.client = Client.load()
        self.email = self.client.email
        logger.info(f"AutoMail client initialized for {self.email}")
        
        # Store messages by contact
        self.messages = {}
        
        # Load known contacts
        self.contacts = self.get_contacts()
    
    def get_contacts(self) -> List[str]:
        """Get the list of available contacts."""
        try:
            future = rpc.send(
                url=f"syft://*/api_data/automail/rpc/contacts",
                body=ContactListRequest(),
                expiry="5m",
                cache=True,
            )
            
            response = future.wait(timeout=10)
            response.raise_for_status()
            
            contacts_response = response.model(ContactListResponse)
            logger.info(f"Retrieved {len(contacts_response.contacts)} contacts")
            return contacts_response.contacts
        except Exception as e:
            logger.error(f"Error getting contacts: {e}")
            return []
    
    def send_message(self, recipient: str, message: str) -> Optional[Message]:
        """Send a message to a recipient and get their response."""
        if not message or not recipient:
            logger.error("Missing recipient or message")
            return None
        
        try:
            # Create message request
            request = MessageRequest(
                message=message,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Store the sent message
            sent_msg = Message(
                content=message,
                sender=self.email,
                timestamp=datetime.now(timezone.utc),
                is_sent=True
            )
            
            if recipient not in self.messages:
                self.messages[recipient] = []
            
            self.messages[recipient].append(sent_msg)
            
            # Send the message via RPC
            logger.info(f"Sending message to {recipient}: {message[:30]}...")
            start_time = time.time()
            
            future = rpc.send(
                url=f"syft://{recipient}/api_data/automail/rpc/message",
                body=request,
                expiry="5m",
                cache=False,
            )
            
            # Wait for the response
            response = future.wait(timeout=60)
            response.raise_for_status()
            
            # Parse the response
            message_response = response.model(MessageResponse)
            
            # Create a response message object
            response_msg = Message(
                content=message_response.message,
                sender=recipient,
                timestamp=message_response.timestamp,
                message_id=message_response.message_id,
                ai_generated=message_response.ai_generated,
                is_sent=False
            )
            
            # Store the response
            self.messages[recipient].append(response_msg)
            
            logger.info(f"Received response from {recipient}. Time taken: {time.time() - start_time:.2f}s")
            
            return response_msg
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    def get_conversation(self, contact: str) -> List[Message]:
        """Get the conversation history with a contact."""
        return self.messages.get(contact, [])


def run_cli():
    """Run a simple command-line interface for AutoMail."""
    client = AutoMailClient()
    print(f"AutoMail CLI - Logged in as {client.email}")
    
    while True:
        print("\nAvailable contacts:")
        contacts = client.contacts
        for i, contact in enumerate(contacts, 1):
            print(f"{i}. {contact}")
        
        print("\nCommands:")
        print("  s <contact_number> <message> - Send a message")
        print("  v <contact_number> - View conversation")
        print("  q - Quit")
        
        cmd = input("\nEnter command: ").strip()
        
        if cmd.startswith('s '):
            try:
                parts = cmd.split(' ', 2)
                if len(parts) < 3:
                    print("Error: Missing message")
                    continue
                
                contact_idx = int(parts[1]) - 1
                message = parts[2]
                
                if 0 <= contact_idx < len(contacts):
                    recipient = contacts[contact_idx]
                    response = client.send_message(recipient, message)
                    
                    if response:
                        print(f"\nYou: {message}")
                        print(f"{recipient}: {response.content}")
                        if response.ai_generated:
                            print("(AI-generated response)")
                    else:
                        print("Failed to send message or receive response")
                else:
                    print("Invalid contact number")
            except ValueError:
                print("Invalid contact number")
            except Exception as e:
                print(f"Error: {e}")
        
        elif cmd.startswith('v '):
            try:
                contact_idx = int(cmd.split(' ')[1]) - 1
                
                if 0 <= contact_idx < len(contacts):
                    contact = contacts[contact_idx]
                    conversation = client.get_conversation(contact)
                    
                    print(f"\nConversation with {contact}:")
                    if not conversation:
                        print("No messages yet")
                    else:
                        for msg in conversation:
                            sender = "You" if msg.is_sent else contact
                            ai_tag = " (AI)" if msg.ai_generated else ""
                            print(f"{msg.timestamp.strftime('%H:%M:%S')} {sender}{ai_tag}: {msg.content}")
                else:
                    print("Invalid contact number")
            except ValueError:
                print("Invalid contact number")
        
        elif cmd == 'q':
            break
        
        else:
            print("Unknown command")


if __name__ == "__main__":
    run_cli()
