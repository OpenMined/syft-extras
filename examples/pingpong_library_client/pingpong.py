from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Callable, Type

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request
from syft_core import Client
from syft_rpc import rpc


# ----------------- Request/Response Models -----------------

class PingRequest(BaseModel):
    """Request to send a ping. Customize or extend for your application."""
    msg: str = Field(description="Ping request string")
    ts: datetime = Field(description="Timestamp of the ping request.")


class PongResponse(BaseModel):
    """Response to a ping request. Customize or extend for your application."""
    msg: str = Field(description="Ping response string")
    ts: datetime = Field(description="Timestamp of the pong response.")


# ----------------- Syft RPC Client -----------------

class SyftRPCClient:
    """A generic Syft RPC client that can be extended for various applications.
    
    This template demonstrates:
    1. Background server to handle incoming requests
    2. Client methods to send requests to other datasites
    3. Discovery of available datasites
    4. Error handling and resource management
    
    Extends this class to create your own custom RPC applications.
    """
    
    def __init__(self, 
                 config_path: Optional[str] = None,
                 app_name: str = "pingpong",
                 endpoint: str = "/ping",
                 request_model: Type[BaseModel] = PingRequest,
                 response_model: Type[BaseModel] = PongResponse):
        """Initialize the Syft RPC client.
        
        Args:
            config_path: Optional path to a custom config.json file
            app_name: Name of your application (determines RPC directory)
            endpoint: The RPC endpoint name
            request_model: Pydantic model for requests
            response_model: Pydantic model for responses
        """
        self.client = Client.load(config_path)
        self.app_name = app_name
        self.endpoint = endpoint
        self.request_model = request_model
        self.response_model = response_model
        self.stop_event = threading.Event()
        self.server_thread = None
        
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
        
        # Use a wrapper function that captures the self.request_model
        request_model = self.request_model
        response_model = self.response_model
        
        # Register the handler for the endpoint with the correct type annotation
        @box.on_request(self.endpoint)
        def request_handler(request_data: dict, ctx: Request) -> dict:
            # Convert the incoming data to the proper model type
            if not isinstance(request_data, request_model):
                try:
                    if isinstance(request_data, dict):
                        request_data = request_model(**request_data)
                    else:
                        request_data = request_model.model_validate(request_data)
                except Exception as e:
                    logger.error(f"Failed to convert request to {request_model.__name__}: {e}")
            
            # Call the handler and convert response to dict for proper serialization
            response = self._handle_request(request_data, ctx, box)
            return response.model_dump() if hasattr(response, "model_dump") else response

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
    
    def _handle_request(self, request_data: BaseModel, ctx: Request, box) -> BaseModel:
        """Handle incoming requests. Override this in your subclass."""
        logger.info(f"🔔 RECEIVED: Request - {request_data}")
        return self.response_model(
            msg=f"Response from {box.client.email}",
            ts=datetime.now(timezone.utc),
        )
    
    def send_request(self, to_email: str, request_data: Optional[BaseModel] = None) -> Optional[BaseModel]:
        """Send a request to the specified datasite.
        
        Args:
            to_email: The email/datasite to send to
            request_data: Optional custom request data (uses default if None)
            
        Returns:
            Response model if successful, None otherwise
        """
        if not self._valid_datasite(to_email):
            logger.error(f"Invalid datasite: {to_email}")
            logger.info("Available datasites:")
            for d in self.list_datasites():
                logger.info(f"  - {d}")
            return None
        
        # Use default request if none provided
        if request_data is None:
            request_data = self.request_model(
                msg=f"Hello from {self.client.email}!",
                ts=datetime.now(timezone.utc)
            )
        
        logger.info(f"📤 SENDING: Request to {to_email}")
        start = time.time()
        future = rpc.send(
            url=rpc.make_url(to_email, self.app_name, self.endpoint),
            body=request_data,
            expiry="5m",
            cache=True,
            client=self.client,
        )

        try:
            response = future.wait(timeout=30)
            response.raise_for_status()
            model_response = response.model(self.response_model)
            elapsed = time.time() - start
            logger.info(f"📥 RECEIVED: Response from {to_email}. Time: {elapsed:.2f}s")
            return model_response
        except Exception as e:
            logger.error(f"❌ CLIENT ERROR: {e}")
            return None
    
    def list_datasites(self) -> List[str]:
        """Get a list of available datasites.
        
        Returns:
            List of datasite emails
        """
        return sorted([ds.name for ds in self.client.datasites.glob("*") if "@" in ds.name])
    
    def list_available_servers(self) -> List[str]:
        """Get a list of datasites running this app's server.
        
        Returns:
            List of datasite emails with active servers
        """
        available_servers = []
        for ds in self.list_datasites():
            # Check if the datasite has the RPC endpoint published
            rpc_path = self.client.datasites / ds / "app_data" / self.app_name / "rpc" / "rpc.schema.json"
            if rpc_path.exists():
                available_servers.append(ds)
        return available_servers
    
    def _valid_datasite(self, ds: str) -> bool:
        """Check if the given datasite is valid."""
        return ds in self.list_datasites()
    
    def close(self):
        """Shut down the client."""
        logger.info(f"👋 Shutting down {self.app_name} client...")
        self.stop_event.set()
        if self.server_thread:
            self.server_thread.join(timeout=2)


# ----------------- PingPong Implementation -----------------

class PingPongClient(SyftRPCClient):
    """A concrete implementation of the generic SyftRPCClient for PingPong."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the PingPong client.
        
        Args:
            config_path: Optional path to a custom config.json file
        """
        super().__init__(
            config_path=config_path,
            app_name="pingpong",
            endpoint="/ping",
            request_model=PingRequest,
            response_model=PongResponse
        )
    
    def _handle_request(self, ping: PingRequest, ctx: Request, box) -> PongResponse:
        """Respond to a ping request with a pong."""
        logger.info(f"🔔 RECEIVED: Ping request - {ping}")
        return PongResponse(
            msg=f"Pong from {box.client.email}",
            ts=datetime.now(timezone.utc),
        )
    
    def ping(self, email: str) -> Optional[PongResponse]:
        """Send a ping request to the specified datasite.
        
        Args:
            email: The email/datasite to ping
            
        Returns:
            PongResponse if successful, None otherwise
        """
        return self.send_request(email)


# ----------------- API Functions -----------------

def client(config_path: Optional[str] = None) -> PingPongClient:
    """Create and return a new PingPong client.
    
    Args:
        config_path: Optional path to a custom config.json file
        
    Returns:
        A PingPongClient instance
    """
    return PingPongClient(config_path)
