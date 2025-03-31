from __future__ import annotations

import threading
import time
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Callable, Type
import uuid

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents, EventRouter
from syft_event.types import Request
from syft_core import Client
from syft_rpc import rpc

# SQLAlchemy imports
from sqlalchemy import create_engine, Column, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Create SQLAlchemy Base class for models
Base = declarative_base()

# ----------------- Database Models -----------------

class MessageModel(Base):
    """SQLAlchemy model for chat messages"""
    __tablename__ = "messages"
    
    msg_id = Column(String, primary_key=True)
    sender = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    thread_id = Column(String, nullable=True)
    reply_to = Column(String, nullable=True)
    meta_data = Column(Text, nullable=True)  # JSON serialized - renamed from metadata


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
    with_user: Optional[str] = Field(default=None, description="Filter by user email")


class ChatHistoryResponse(BaseModel):
    """Response containing chat history."""
    messages: List[ChatMessage] = Field(description="List of chat messages")
    count: int = Field(description="Number of messages returned")


# ----------------- Chat Router -----------------

chat_router = EventRouter()

@chat_router.on_request("/message")
def message_handler(request: ChatRequest, app: SyftEvents) -> ChatResponse:
    """Handle incoming chat messages"""
    session = app.state["db_session"]
    message = request.message
    
    logger.info(f"📨 RECEIVED: Message from {message.sender}: {message.content[:50]}...")
    
    # Convert to JSON serializable format for metadata
    metadata_str = str(message.metadata) if message.metadata else "{}"
    
    # Check if message already exists in database
    existing_message = session.query(MessageModel).filter(MessageModel.msg_id == message.msg_id).first()
    
    if not existing_message:
        # Create db model from message only if it doesn't exist
        db_message = MessageModel(
            msg_id=message.msg_id,
            sender=message.sender,
            content=message.content,
            timestamp=message.timestamp,
            thread_id=message.thread_id,
            reply_to=message.reply_to,
            meta_data=metadata_str
        )
        
        # Save to database
        session.add(db_message)
        try:
            session.commit()
        except Exception as e:
            # Rollback on error
            session.rollback()
            logger.error(f"Error saving message: {e}")
            # Continue processing even if save fails
    else:
        logger.info(f"Message with ID {message.msg_id} already exists, skipping database insert")
    
    # Check if this is a self-stored message (where sender == current user)
    is_self_stored = message.sender == app.state["client_email"]
    
    # Notify any registered message listeners, but only if not a self-stored message
    if "message_listeners" in app.state and not is_self_stored:
        for listener in app.state["message_listeners"]:
            try:
                listener(message)
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
    
    return ChatResponse(
        status="delivered",
        message_id=message.msg_id,
        timestamp=datetime.now(timezone.utc)
    )


@chat_router.on_request("/history")
def history_handler(request: ChatHistoryRequest, app: SyftEvents) -> ChatHistoryResponse:
    """Handle requests for chat history"""
    session = app.state["db_session"]
    
    # Start with a base query for all messages
    query = session.query(MessageModel)
    
    # Apply filters based on request
    if request.thread_id:
        query = query.filter(MessageModel.thread_id == request.thread_id)
    
    if request.since:
        query = query.filter(MessageModel.timestamp >= request.since)
    
    # Filter by user if specified
    if request.with_user:
        current_user = app.state["client_email"]
        query = query.filter(
            ((MessageModel.sender == request.with_user) & (MessageModel.meta_data.like(f"%'recipient': '{current_user}'%"))) |
            ((MessageModel.sender == current_user) & (MessageModel.meta_data.like(f"%'recipient': '{request.with_user}'%")))
        )
    
    # Order by timestamp and limit results
    query = query.order_by(MessageModel.timestamp)
    
    if request.limit:
        query = query.limit(request.limit)
    
    # Execute query
    db_messages = query.all()
    
    # Convert SQLAlchemy models to Pydantic models
    messages = []
    for db_msg in db_messages:
        # Parse metadata from string
        try:
            metadata = eval(db_msg.meta_data) if db_msg.meta_data else {}
        except:
            metadata = {}
            
        messages.append(ChatMessage(
            msg_id=db_msg.msg_id,
            sender=db_msg.sender,
            content=db_msg.content,
            timestamp=db_msg.timestamp,
            thread_id=db_msg.thread_id,
            reply_to=db_msg.reply_to,
            metadata=metadata
        ))
    
    return ChatHistoryResponse(
        messages=messages,
        count=len(messages)
    )


# ----------------- Server App Creation -----------------

def init_database(engine):
    """Initialize the SQLite database schema."""
    # Create tables if they don't exist
    Base.metadata.create_all(engine)


def create_chat_app(client=None, db_path="chat_messages.db") -> SyftEvents:
    """Create the SyftEvents application with SQLAlchemy database connection."""
    if client is None:
        client = Client.load()
        
    app = SyftEvents("syft_chat", client=client)
    
    # Create database directory if it doesn't exist
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    # Initialize SQLAlchemy engine and session
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Initialize database schema
    init_database(engine)
    
    # Store session and client email in app state
    app.state["db_session"] = session
    app.state["db_engine"] = engine
    app.state["client_email"] = client.email
    app.state["message_listeners"] = []
    
    # Include the chat router
    app.include_router(chat_router)
    
    return app


# ----------------- Syft Chat Client -----------------

class SyftChatClient:
    """Client for sending and receiving chat messages over Syft with SQLite persistence."""
    
    def __init__(self, 
                 config_path: Optional[str] = None,
                 app_name: str = "syft_chat",
                 db_path: str = "chat_messages.db"):
        """Initialize the Syft Chat client.
        
        Args:
            config_path: Optional path to a custom config.json file
            app_name: Name of your application (determines RPC directory)
            db_path: Path to SQLite database file
        """
        self.client = Client.load(config_path)
        self.app_name = app_name
        self.db_path = db_path
        self.stop_event = threading.Event()
        self.server_thread = None
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
        app = create_chat_app(client=self.client, db_path=self.db_path)
        
        # Add our message listeners to the app state
        app.state["message_listeners"] = self.message_listeners
        
        logger.info(f"🚀 SERVER: Running {self.app_name} server as {self.client.email}")
        logger.info(f"📡 SERVER: Listening for requests at {app.app_rpc_dir}")
        
        try:
            # Start the server with error handling
            try:
                app.start()
            except RuntimeError as e:
                if "already scheduled" in str(e):
                    logger.warning(f"Watch already exists: {e}. Continuing anyway.")
                else:
                    raise
            
            # Process requests in a loop
            while not self.stop_event.is_set():
                app.process_pending_requests()
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ SERVER ERROR: {e}")
        finally:
            try:
                app.stop()
                # Close the database session
                if "db_session" in app.state:
                    app.state["db_session"].close()
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
    
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
            reply_to=reply_to,
            metadata={"recipient": to_email}  # Track recipient in metadata
        )
        
        # Create the request
        request = ChatRequest(message=message)
        
        logger.info(f"📤 SENDING: Message to {to_email}")
        start = time.time()
        
        # Send to recipient
        future = rpc.send(
            url=rpc.make_url(to_email, self.app_name, "message"),
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
            
            # Also store the sent message in our own database for history
            self_request = ChatRequest(message=message)
            self_future = rpc.send(
                url=rpc.make_url(self.client.email, self.app_name, "message"),
                body=self_request,
                expiry="5m",
                cache=True,
                client=self.client,
            )
            
            self_response = self_future.wait(timeout=10)
            self_response.raise_for_status()
                    
            return model_response
        except Exception as e:
            logger.error(f"❌ CLIENT ERROR: {e}")
            raise
    
    def get_chat_history(self, with_user: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[ChatMessage]:
        """Get chat history from local database, optionally filtered by user.
        
        Args:
            with_user: Optional email to filter messages by sender
            limit: Maximum number of messages to retrieve
            since: Retrieve messages since this time
            
        Returns:
            List of chat messages
        """
        request = ChatHistoryRequest(
            limit=limit,
            with_user=with_user,
            since=since
        )
        
        future = rpc.send(
            url=rpc.make_url(self.client.email, self.app_name, "history"),
            body=request,
            expiry="5m",
            cache=True,
            client=self.client,
        )
        
        try:
            response = future.wait(timeout=10)
            response.raise_for_status()
            history_response = response.model(ChatHistoryResponse)
            return history_response.messages
        except Exception as e:
            logger.error(f"❌ Error retrieving chat history: {e}")
            return []
    
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
            with_user=self.client.email,  # Filter to messages involving us
            since=since
        )
        
        logger.info(f"📤 REQUESTING: Chat history from {from_email}")
        start = time.time()
        
        future = rpc.send(
            url=rpc.make_url(from_email, self.app_name, "history"),
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
            
            # Also store the received messages in our local database
            for message in model_response.messages:
                # Only store messages we don't already have
                self_request = ChatRequest(message=message)
                self_future = rpc.send(
                    url=rpc.make_url(self.client.email, self.app_name, "message"),
                    body=self_request,
                    expiry="5m",
                    cache=True,
                    client=self.client,
                )
                
                self_response = self_future.wait(timeout=10)
                
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
            rpc_path = self.client.datasites / ds / "app_data" / self.app_name / "rpc" / "rpc.schema.json"
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

def client(config_path: Optional[str] = None, db_path: str = "chat_messages.db") -> SyftChatClient:
    """Create and return a new Syft Chat client.
    
    Args:
        config_path: Optional path to a custom config.json file
        db_path: Path to SQLite database file
        
    Returns:
        A SyftChatClient instance
    """
    return SyftChatClient(config_path=config_path, db_path=db_path)


# ----------------- Run as standalone server -----------------

def main():
    """Run as a standalone server (useful for debugging)"""
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Stateful Syft Chat Server")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--db", "-d",
        type=str,
        default="chat_messages.db",
        help="Path to SQLite database file"
    )
    args = parser.parse_args()
    
    # Initialize client with config if provided
    client = Client.load(args.config)
    print(f"Running as user: {client.email}")
    
    app = create_chat_app(client, args.db)
    
    try:
        print("Running Stateful Syft Chat server:", app.app_rpc_dir)
        app.run_forever()
    except KeyboardInterrupt:
        print("Server stopped.")
        # Close the database session
        if "db_session" in app.state:
            app.state["db_session"].close()
    except Exception as e:
        print(f"Error: {e}")
        # Close the database session
        if "db_session" in app.state:
            app.state["db_session"].close()


if __name__ == "__main__":
    main()
