from __future__ import annotations

from datetime import datetime, timezone
import argparse as arg_parser

from loguru import logger
from pydantic import BaseModel, Field
from syft_event import SyftEvents
from syft_event.types import Request
from syft_core import Client

# We'll initialize the box later after parsing args


class PingRequest(BaseModel):
    """Request to send a ping."""

    msg: str = Field(description="Ping request string")
    ts: datetime = Field(description="Timestamp of the ping request.")


class PongResponse(BaseModel):
    """Response to a ping request."""

    msg: str = Field(description="Ping response string")
    ts: datetime = Field(description="Timestamp of the pong response.")


def create_server(client=None):
    """Create and return the SyftEvents server with the given client."""
    if client is None:
        client = Client.load()
    return SyftEvents("pingpong", client=client)


def pong(ping: PingRequest, ctx: Request, box) -> PongResponse:
    """Respond to a ping request."""

    logger.info(f"Got ping request - {ping}")
    return PongResponse(
        msg=f"Pong from {box.client.email}",
        ts=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    # Parse command line arguments
    parser = arg_parser.ArgumentParser(description="Pong Server")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    args = parser.parse_args()
    
    # Initialize client and server
    client = Client.load(args.config)
    box = create_server(client)
    print(f"Running as user: {client.email}")
    
    # Register the handler
    @box.on_request("/ping")
    def ping_handler(ping: PingRequest, ctx: Request) -> PongResponse:
        return pong(ping, ctx, box)

    try:
        print("Running rpc server for", box.app_rpc_dir)
        box.run_forever()
    except Exception as e:
        print(e)
