from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import argparse as arg_parser

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


def send_ping(email, client=None):
    if client is None:
        client = Client.load()
    start = time.time()
    future = rpc.send(
        url=rpc.make_url(datasite=email, app_name="pingpong", endpoint="ping"),
        body=PingRequest(msg="hello!"),
        expiry="5m",
        cache=True,
        client=client,
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


def get_datasites(client: Client) -> List[str]:
    return sorted([ds.name for ds in client.datasites.glob("*") if "@" in ds.name])


def valid_datasite(ds: str, client) -> bool:
    return ds in get_datasites(client)


def prompt_input(client: Client) -> Optional[str]:
    while True:
        datasites = get_datasites(client)
        ds = input("Enter datasite (they must have a pong server running): ")
        if valid_datasite(ds, client):
            return ds
        else:
            print(f"Invalid datasite: {ds}.")
            for d in datasites:
                print("-", d)


def main():
    """Main function to handle the ping request process."""
    # Parse command line arguments
    parser = arg_parser.ArgumentParser(description="Ping Request Client")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "datasite", 
        nargs="?",  # Make this argument optional
        help="Email of the datasite to ping"
    )
    args = parser.parse_args()

    try:
        # Initialize client with config if provided
        client = Client.load(args.config)
        print(f"Connected as: {client.email}")

        ds = args.datasite

        if ds and not valid_datasite(ds, client):
            print(f"Invalid ds: {ds}")
            for d in get_datasites(client):
                print("-", d)
            sys.exit(1)
        elif not ds:
            ds = prompt_input(client)

        send_ping(ds, client)
    except KeyboardInterrupt:
        logger.info("bye!")


if __name__ == "__main__":
    main()
