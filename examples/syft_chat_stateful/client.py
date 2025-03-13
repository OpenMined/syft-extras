from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Callable
from loguru import logger
from syft_core import Client
from syft_rpc import rpc

from .models import ChatMessage, ChatRequest, ChatResponse, ChatHistoryRequest, ChatHistoryResponse
from .server import create_chat_app

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

def client(config_path: Optional[str] = None, db_path: str = "chat_messages.db") -> SyftChatClient:
    """Create and return a new Syft Chat client.
    
    Args:
        config_path: Optional path to a custom config.json file
        db_path: Path to SQLite database file
        
    Returns:
        A SyftChatClient instance
    """
    return SyftChatClient(config_path=config_path, db_path=db_path) 