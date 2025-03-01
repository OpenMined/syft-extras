from __future__ import annotations

import time
import argparse as arg_parser
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger
from pydantic import BaseModel
from syft_core import Client
from syft_rpc import rpc


@dataclass
class PingRequest:
    msg: str
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PongResponse(BaseModel):
    msg: str
    ts: datetime


def send_ping(recipient=None, config_path=None):
    print("config path:" + str(config_path))
    client = Client.load(config_path)
    
    # Use provided recipient or fall back to client's own email
    target_email = recipient if recipient else client.email
    
    start = time.time()
    future = rpc.send(
        url=f"syft://{target_email}/api_data/pingpong/rpc/ping",
        body=PingRequest(msg="hello from "+client.email+"!"),
        expiry="5m",
        cache=True,
        client=client
    )
    logger.debug(f"Request: {future.request}")

    try:
        response = future.wait(timeout=300)
        response.raise_for_status()
        pong_response = response.model(PongResponse)
        logger.info(f"Response: {pong_response}. Time taken: {time.time() - start}")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    # Parse command line arguments
    parser = arg_parser.ArgumentParser(description="Send ping request with custom configuration")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--recipient", "-r",
        type=str,
        help="Email address of the recipient (defaults to your own email)"
    )
    args = parser.parse_args()
    
    print(f"Using config: {args.config if args.config else 'default'}")
    print(f"Sending to: {args.recipient if args.recipient else 'self'}")
    send_ping(args.recipient, args.config)
