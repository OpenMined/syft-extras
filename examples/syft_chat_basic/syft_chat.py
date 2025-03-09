from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Callable, Type
import uuid

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request
from syft_core import Client
from syft_rpc import rpc


# ----------------- Message Models -----------------

class ChatMessage(BaseModel):
    """Model for chat messages exchanged between users."""
    msg_id: str = Field(description="Unique message ID")
    sender: str = Field(description="Email of the sender")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(description="Message timestamp")
    thread_id: Optional[str] = Field(default=None, description="Thread ID for conversation grouping")
    reply_to: Optional[str] = Field(default=None, description="ID of message being replied to")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional message metadata")


class ChatRequest(BaseModel):
    """Request to send a chat message."""
    message: ChatMessage = Field(description="The chat message to send")


class ChatResponse(BaseModel):
    """Response to a chat message request."""
    status: str = Field(description="Status of the message delivery")
    message_id: str = Field(description="ID of the delivered message")
    timestamp: datetime = Field(description="Timestamp of the response")


class ChatHistoryRequest(BaseModel):
    """Request to retrieve chat history."""
    limit: int = Field(default=50, description="Maximum number of messages to retrieve")
    thread_id: Optional[str] = Field(default=None, description="Filter by thread ID")
    since: Optional[datetime] = Field(default=None, description="Retrieve messages since this time")


class ChatHistoryResponse(BaseModel):
    """Response containing chat history."""
    messages: List[ChatMessage] = Field(description="List of chat messages")
    count: int = Field(description="Number of messages returned")


# ----------------- Syft Chat Client -----------------

class SyftChatClient:
    """Client for sending and receiving chat messages over Syft."""
    
    def __init__(self, 
                 config_path: Optional[str] = None,
                 app_name: str = "syft_chat"):
        """Initialize the Syft Chat client.
        
        Args:
            config_path: Optional path to a custom config.json file
            app_name: Name of your application (determines RPC directory)
        """
        self.client = Client.load(config_path)
        self.app_name = app_name
        self.stop_event = threading.Event()
        self.server_thread = None
        self.message_store: Dict[str, ChatMessage] = {}  # Local store of messages
        self.message_listeners: List[Callable[[ChatMessage], None]] = []
        
        logger.info(f"🔑 Connected as: {self.client.email}")
        
        # Start server in background thread
        self._start_server()
    
    def _start_server(self):
        """Start the RPC server in the background."""
        self.stop_event.clear()
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True
        )
        self.server_thread.start()
        logger.info(f"🔔 Server started for {self.client.email}")
    
    def _run_server(self):
        """Run the RPC server in a background thread."""
        box = self._create_server()
        logger.info(f"🚀 SERVER: Running {self.app_name} server as {self.client.email}")
        
        # Register handlers for different endpoints
        
        # Handler for incoming chat messages
        @box.on_request("/message")
        def message_handler(request_data: dict, ctx: Request) -> dict:
            # Convert to proper model
            try:
                if isinstance(request_data, dict):
                    request = ChatRequest(**request_data)
                else:
                    request = ChatRequest.model_validate(request_data)
            except Exception as e:
                logger.error(f"Failed to parse chat request: {e}")
                return ChatResponse(
                    status="error",
                    message_id="",
                    timestamp=datetime.now(timezone.utc)
                ).model_dump()
            
            # Process the message
            response = self._handle_message(request.message, ctx, box)
            return response.model_dump()
        
        # Handler for chat history requests
        @box.on_request("/history")
        def history_handler(request_data: dict, ctx: Request) -> dict:
            # Convert to proper model
            try:
                if isinstance(request_data, dict):
                    request = ChatHistoryRequest(**request_data)
                else:
                    request = ChatHistoryRequest.model_validate(request_data)
            except Exception as e:
                logger.error(f"Failed to parse history request: {e}")
                return ChatHistoryResponse(
                    messages=[],
                    count=0
                ).model_dump()
            
            # Process the history request
            response = self._handle_history_request(request, ctx, box)
            return response.model_dump()

        try:
            logger.info(f"📡 SERVER: Listening for requests at {box.app_rpc_dir}")
            
            # Start the server with error handling
            try:
                box.start()
            except RuntimeError as e:
                if "already scheduled" in str(e):
                    logger.warning(f"Watch already exists: {e}. Continuing anyway.")
                else:
                    raise
            
            # Process requests in a loop
            while not self.stop_event.is_set():
                box.process_pending_requests()
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ SERVER ERROR: {e}")
        finally:
            try:
                box.stop()
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
    
    def _create_server(self):
        """Create and return the SyftEvents server."""
        return SyftEvents(self.app_name, client=self.client)
    
    def _handle_message(self, message: ChatMessage, ctx: Request, box) -> ChatResponse:
        """Handle an incoming chat message."""
        logger.info(f"📨 RECEIVED: Message from {message.sender}: {message.content[:50]}...")
        
        # Store the message
        self.message_store[message.msg_id] = message
        
        # Notify listeners
        for listener in self.message_listeners:
            try:
                listener(message)
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
        
        return ChatResponse(
            status="delivered",
            message_id=message.msg_id,
            timestamp=datetime.now(timezone.utc)
        )
    
    def _handle_history_request(self, request: ChatHistoryRequest, ctx: Request, box) -> ChatHistoryResponse:
        """Handle a request for chat history."""
        # Filter messages based on request criteria
        filtered_messages = list(self.message_store.values())
        
        # Apply thread filter if specified
        if request.thread_id:
            filtered_messages = [m for m in filtered_messages if m.thread_id == request.thread_id]
        
        # Apply time filter if specified
        if request.since:
            filtered_messages = [m for m in filtered_messages if m.timestamp >= request.since]
        
        # Sort by timestamp
        filtered_messages.sort(key=lambda m: m.timestamp)
        
        # Apply limit
        if request.limit and len(filtered_messages) > request.limit:
            filtered_messages = filtered_messages[-request.limit:]
        
        return ChatHistoryResponse(
            messages=filtered_messages,
            count=len(filtered_messages)
        )
    
    def send_message(self, to_email: str, content: str, thread_id: Optional[str] = None, reply_to: Optional[str] = None) -> ChatResponse:
        """Send a chat message to the specified user.
        
        Args:
            to_email: Email of the recipient
            content: Message content
            thread_id: Optional thread ID for conversation grouping
            reply_to: Optional ID of message being replied to
            
        Returns:
            ChatResponse with delivery status
        """
        if not self._valid_user(to_email):
            logger.error(f"Invalid user: {to_email}")
            logger.info("Available users:")
            for user in self.list_available_users():
                logger.info(f"  - {user}")
            raise ValueError(f"User {to_email} not found or not available")
        
        # Create the message
        message = ChatMessage(
            msg_id=str(uuid.uuid4()),
            sender=self.client.email,
            content=content,
            timestamp=datetime.now(timezone.utc),
            thread_id=thread_id,
            reply_to=reply_to
        )
        
        # Create the request
        request = ChatRequest(message=message)
        
        logger.info(f"📤 SENDING: Message to {to_email}")
        start = time.time()
        
        future = rpc.send(
            url=f"syft://{to_email}/api_data/{self.app_name}/rpc/message",
            body=request,
            expiry="5m",
            cache=True,
            client=self.client,
        )

        try:
            response = future.wait(timeout=30)
            response.raise_for_status()
            model_response = response.model(ChatResponse)
            elapsed = time.time() - start
            logger.info(f"📥 RECEIVED: Delivery confirmation from {to_email}. Time: {elapsed:.2f}s")
            
            # Store the sent message locally too
            self.message_store[message.msg_id] = message
            
            # Notify listeners about the sent message
            for listener in self.message_listeners:
                try:
                    listener(message)
                except Exception as e:
                    logger.error(f"Error in message listener: {e}")
                    
            return model_response
        except Exception as e:
            logger.error(f"❌ CLIENT ERROR: {e}")
            raise
    
    def get_chat_history(self, with_user: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[ChatMessage]:
        """Get chat history, optionally filtered by user.
        
        Args:
            with_user: Optional email to filter messages by sender
            limit: Maximum number of messages to retrieve
            since: Retrieve messages since this time
            
        Returns:
            List of chat messages
        """
        # Filter messages from local store
        messages = list(self.message_store.values())
        
        # Filter by user if specified
        if with_user:
            messages = [m for m in messages if m.sender == with_user or (m.sender == self.client.email and m.metadata.get("recipient") == with_user)]
        
        # Filter by time if specified
        if since:
            messages = [m for m in messages if m.timestamp >= since]
        
        # Sort by timestamp
        messages.sort(key=lambda m: m.timestamp)
        
        # Apply limit
        if limit and len(messages) > limit:
            messages = messages[-limit:]
        
        return messages
    
    def request_history_from_user(self, from_email: str, limit: int = 50, since: Optional[datetime] = None) -> List[ChatMessage]:
        """Request chat history from another user.
        
        Args:
            from_email: Email of the user to request history from
            limit: Maximum number of messages to retrieve
            since: Retrieve messages since this time
            
        Returns:
            List of chat messages
        """
        if not self._valid_user(from_email):
            logger.error(f"Invalid user: {from_email}")
            return []
        
        # Create the request
        request = ChatHistoryRequest(
            limit=limit,
            since=since
        )
        
        logger.info(f"📤 REQUESTING: Chat history from {from_email}")
        start = time.time()
        
        future = rpc.send(
            url=f"syft://{from_email}/api_data/{self.app_name}/rpc/history",
            body=request,
            expiry="5m",
            cache=True,
            client=self.client,
        )

        try:
            response = future.wait(timeout=30)
            response.raise_for_status()
            model_response = response.model(ChatHistoryResponse)
            elapsed = time.time() - start
            logger.info(f"📥 RECEIVED: History from {from_email} ({model_response.count} messages). Time: {elapsed:.2f}s")
            
            # Store the received messages locally too
            for message in model_response.messages:
                self.message_store[message.msg_id] = message
            
            return model_response.messages
        except Exception as e:
            logger.error(f"❌ CLIENT ERROR: {e}")
            return []
    
    def list_available_users(self) -> List[str]:
        """Get a list of users with chat enabled.
        
        Returns:
            List of user emails
        """
        available_users = []
        for ds in self.list_all_users():
            # Check if the datasite has the chat RPC endpoint published
            rpc_path = self.client.datasites / ds / "api_data" / self.app_name / "rpc" / "rpc.schema.json"
            if rpc_path.exists():
                available_users.append(ds)
        return available_users
    
    def list_all_users(self) -> List[str]:
        """Get a list of all datasites/users.
        
        Returns:
            List of user emails
        """
        return sorted([ds.name for ds in self.client.datasites.glob("*") if "@" in ds.name])
    
    def _valid_user(self, email: str) -> bool:
        """Check if the user exists and has chat enabled."""
        return email in self.list_available_users()
    
    def add_message_listener(self, listener: Callable[[ChatMessage], None]):
        """Add a listener function that will be called for each new message.
        
        Args:
            listener: Function that takes a ChatMessage parameter
        """
        if listener not in self.message_listeners:
            self.message_listeners.append(listener)
    
    def remove_message_listener(self, listener: Callable[[ChatMessage], None]):
        """Remove a previously added message listener.
        
        Args:
            listener: The listener function to remove
        """
        if listener in self.message_listeners:
            self.message_listeners.remove(listener)
    
    def close(self):
        """Shut down the client."""
        logger.info(f"👋 Shutting down {self.app_name} client...")
        self.stop_event.set()
        if self.server_thread:
            self.server_thread.join(timeout=2)


# ----------------- API Functions -----------------

def client(config_path: Optional[str] = None) -> SyftChatClient:
    """Create and return a new Syft Chat client.
    
    Args:
        config_path: Optional path to a custom config.json file
        
    Returns:
        A SyftChatClient instance
    """
    return SyftChatClient(config_path=config_path)
