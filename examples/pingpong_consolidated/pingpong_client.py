from __future__ import annotations

import sys
import time
import threading
import argparse as arg_parser
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


# ----------------- Server Component -----------------

def create_server(client=None):
    """Create and return the SyftEvents server with the given client."""
    if client is None:
        client = Client.load()
    return SyftEvents("pingpong", client=client)


def pong(ping: PingRequest, ctx: Request, box) -> PongResponse:
    """Respond to a ping request."""
    logger.info(f"🔔 RECEIVED: Ping request - {ping}")
    return PongResponse(
        msg=f"Pong from {box.client.email}",
        ts=datetime.now(timezone.utc),
    )


def run_server(client, stop_event):
    """Run the pong server in the background."""
    box = create_server(client)
    logger.info(f"🚀 SERVER: Running pong server as {client.email}")
    
    @box.on_request("/ping")
    def ping_handler(ping: PingRequest, ctx: Request) -> PongResponse:
        return pong(ping, ctx, box)

    try:
        logger.info(f"📡 SERVER: Listening for pings at {box.app_rpc_dir}")
        
        # Start the server
        box.start()
        
        # The original code uses run_forever() which would block
        # For the integrated client, we'll use a loop and check the stop_event
        while not stop_event.is_set():
            # Process any pending requests
            box.process_pending_requests()
            time.sleep(0.1)
    except Exception as e:
        logger.error(f"❌ SERVER ERROR: {e}")
    finally:
        # Ensure we stop the observer when exiting
        box.stop()


# ----------------- Client Component -----------------

def send_ping(email, client=None):
    """Send a ping request to the specified datasite."""
    if client is None:
        client = Client.load()
    
    logger.info(f"📤 SENDING: Ping to {email}")
    start = time.time()
    future = rpc.send(
        url=f"syft://{email}/api_data/pingpong/rpc/ping",
        body=PingRequest(
            msg=f"Hello from {client.email}!",
            ts=datetime.now(timezone.utc)
        ),
        expiry="5m",
        cache=True,
        client=client,
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


def get_datasites(client: Client) -> List[str]:
    """Get a list of available datasites."""
    return sorted([ds.name for ds in client.datasites.glob("*") if "@" in ds.name])


def valid_datasite(ds: str, client) -> bool:
    """Check if the given datasite is valid."""
    return ds in get_datasites(client)


def prompt_input(client: Client) -> Optional[str]:
    """Prompt the user to enter a datasite."""
    while True:
        datasites = get_datasites(client)
        print("\nAvailable datasites:")
        for d in datasites:
            print(f"  - {d}")
        
        ds = input("\nEnter datasite to ping (or 'q' to quit): ")
        
        if ds.lower() == 'q':
            return None
        if valid_datasite(ds, client):
            return ds
        else:
            print(f"Invalid datasite: {ds}. Please try again.")


# ----------------- Main Program -----------------

def main():
    """Main function to handle both ping and pong functionality."""
    parser = arg_parser.ArgumentParser(
        description="Integrated PingPong Client - Send and receive pings"
    )
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--server-only", 
        action="store_true",
        help="Run in server mode only (respond to pings)"
    )
    parser.add_argument(
        "--client-only", 
        action="store_true",
        help="Run in client mode only (send pings)"
    )
    parser.add_argument(
        "--ping", "-p",
        type=str,
        help="Immediately ping the specified datasite and exit"
    )
    args = parser.parse_args()

    # Initialize client
    client = Client.load(args.config)
    logger.info(f"🔑 Connected as: {client.email}")

    # Run only as client if specified
    if args.client_only or args.ping:
        if args.ping:
            if valid_datasite(args.ping, client):
                send_ping(args.ping, client)
            else:
                logger.error(f"Invalid datasite: {args.ping}")
                print("Available datasites:")
                for d in get_datasites(client):
                    print(f"  - {d}")
                sys.exit(1)
        else:
            logger.info("🔍 Running in client mode (send pings only)")
            try:
                while True:
                    ds = prompt_input(client)
                    if ds is None:
                        break
                    send_ping(ds, client)
            except KeyboardInterrupt:
                logger.info("👋 Goodbye!")
        return

    # Run only as server if specified
    if args.server_only:
        logger.info("🔔 Running in server mode (respond to pings only)")
        stop_event = threading.Event()
        try:
            run_server(client, stop_event)
        except KeyboardInterrupt:
            logger.info("👋 Stopping server...")
            stop_event.set()
        return

    # Run as both client and server
    logger.info("🔄 Running in dual mode (send and respond to pings)")
    stop_event = threading.Event()

    # Start server in a separate thread
    server_thread = threading.Thread(
        target=run_server,
        args=(client, stop_event),
        daemon=True
    )
    server_thread.start()

    # Run client in the main thread
    try:
        while True:
            print("\n=== PingPong Client ===")
            print("1. Send ping")
            print("2. Quit")
            choice = input("Enter choice: ")
            
            if choice == '1':
                ds = prompt_input(client)
                if ds is not None:
                    send_ping(ds, client)
            elif choice == '2':
                break
            else:
                print("Invalid choice. Please try again.")
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("👋 Shutting down...")
        stop_event.set()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    main()
