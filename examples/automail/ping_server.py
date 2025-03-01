from __future__ import annotations

from datetime import datetime, timezone

# Fix the argparse import
import sys
import argparse as arg_parser
from loguru import logger
from pydantic import BaseModel, Field
from syft_core import Client
from syft_event import SyftEvents
from syft_event.types import Request

# Parse command line arguments
parser = arg_parser.ArgumentParser(description="Automail client with custom configuration")
parser.add_argument(
    "--config", "-c", 
    type=str, 
    help="Path to a custom config.json file"
)
args = parser.parse_args()

# Create custom client with optional config path
config_path = args.config if args.config else None
custom_client = Client.load(config_path)

box = SyftEvents("pingpong", client=custom_client)


class PingRequest(BaseModel):
    """Request to send a ping."""

    msg: str = Field(description="Ping request string")
    ts: datetime = Field(description="Timestamp of the ping request.")


class PongResponse(BaseModel):
    """Response to a ping request."""

    msg: str = Field(description="Ping response string")
    ts: datetime = Field(description="Timestamp of the pong response.")


@box.on_request("/ping")
def pong(ping: PingRequest, ctx: Request) -> PongResponse:
    """Respond to a ping request."""

    logger.info(f"Got ping request - {ping}")
    return PongResponse(
        msg=f"Pong from {box.client.email}",
        ts=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    try:
        print(f"Using config: {args.config if args.config else 'default'}")
        print("Running rpc server for", box.app_rpc_dir)
        box.run_forever()
    except Exception as e:
        print(e)
