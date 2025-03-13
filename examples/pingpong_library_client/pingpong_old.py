from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request
from syft_core import Client
from syft_rpc import rpc


# ----------------- Models -----------------

class PingRequest(BaseModel):
    """Request to send a ping."""
    msg: str = Field(description="Ping request string")
    ts: datetime = Field(description="Timestamp of the ping request.")


class PongResponse(BaseModel):
    """Response to a ping request."""
    msg: str = Field(description="Ping response string")
    ts: datetime = Field(description="Timestamp of the pong response.")


# ----------------- PingPong Client -----------------

class PingPongClient:
    """A client that can both send and receive pings."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the PingPong client.
        
        Args:
            config_path: Optional path to a custom config.json file
        """
        self.client = Client.load(config_path)
        self.server = None
        self.stop_event = threading.Event()
        self.server_thread = None
        
        logger.info(f"🔑 Connected as: {self.client.email}")
        
        # Start server in background thread
        self._start_server()
    
    def _start_server(self):
        """Start the pong server in the background."""
        self.stop_event.clear()
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True
        )
        self.server_thread.start()
        logger.info(f"🔔 PingPong server started for {self.client.email}")
    
    def _run_server(self):
        """Run the pong server in a background thread."""
        box = self._create_server()
        logger.info(f"🚀 SERVER: Running pong server as {self.client.email}")
        
        @box.on_request("/ping")
        def ping_handler(ping: PingRequest, ctx: Request) -> PongResponse:
            return self._pong(ping, ctx, box)

        try:
            logger.info(f"📡 SERVER: Listening for pings at {box.app_rpc_dir}")
            
            # Start the server with error handling
            try:
                box.start()
            except RuntimeError as e:
                if "already scheduled" in str(e):
                    logger.warning(f"Watch already exists: {e}. Continuing anyway.")
                else:
                    raise
            
            # For the integrated client, we'll use a loop and check the stop_event
            while not self.stop_event.is_set():
                # Process any pending requests
                box.process_pending_requests()
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ SERVER ERROR: {e}")
        finally:
            # Ensure we stop the observer when exiting
            try:
                box.stop()
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
    
    def _create_server(self):
        """Create and return the SyftEvents server."""
        return SyftEvents("pingpong", client=self.client)
    
    def _pong(self, ping: PingRequest, ctx: Request, box) -> PongResponse:
        """Respond to a ping request."""
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
        if not self._valid_datasite(email):
            logger.error(f"Invalid datasite: {email}")
            logger.info("Available datasites:")
            for d in self.list_datasites():
                logger.info(f"  - {d}")
            return None
        
        logger.info(f"📤 SENDING: Ping to {email}")
        start = time.time()
        future = rpc.send(
            url=rpc.make_url(email, "pingpong", "ping"),
            body=PingRequest(
                msg=f"Hello from {self.client.email}!",
                ts=datetime.now(timezone.utc)
            ),
            expiry="5m",
            cache=True,
            client=self.client,
        )

        try:
            response = future.wait(timeout=30)
            response.raise_for_status()
            pong_response = response.model(PongResponse)
            elapsed = time.time() - start
            logger.info(f"📥 RECEIVED: {pong_response.msg}. Time: {elapsed:.2f}s")
            return pong_response
        except Exception as e:
            logger.error(f"❌ CLIENT ERROR: {e}")
            return None
    
    def list_datasites(self) -> List[str]:
        """Get a list of available datasites.
        
        Returns:
            List of datasite emails
        """
        return sorted([ds.name for ds in self.client.datasites.glob("*") if "@" in ds.name])
    
    def _valid_datasite(self, ds: str) -> bool:
        """Check if the given datasite is valid."""
        return ds in self.list_datasites()
    
    def close(self):
        """Shut down the PingPong client."""
        logger.info("👋 Shutting down PingPong client...")
        self.stop_event.set()
        if self.server_thread:
            self.server_thread.join(timeout=2)


# ----------------- API Functions -----------------

def client(config_path: Optional[str] = None) -> PingPongClient:
    """Create and return a new PingPong client.
    
    Args:
        config_path: Optional path to a custom config.json file
        
    Returns:
        A PingPongClient instance
    """
    return PingPongClient(config_path)