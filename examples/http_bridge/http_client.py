from pathlib import Path
from uuid import uuid4

import httpx
from loguru import logger
from syft_core import Client as SyftboxClient
from syft_http_bridge import create_syft_http_client

BASE_DIR = Path(__file__).parent

"""
syft-http-bridge allows you to create a bridge between SyftBox and any http 1.1 server.

This example demonstrates how to create a simple FastAPI application, that uses the bridge to
expose the HTTP API over SyftBox.

Internally:
- The bridge listens to serialized HTTP requests in the `<app_dir>/http/requests` directory.
- The bridge returns responses in the `<app_dir>/http/responses` directory.
"""


def client_example():
    # Must match the app_name and host user of the server
    syftbox_client = SyftboxClient.load()
    host = syftbox_client.email
    app_client: httpx.Client = create_syft_http_client(
        app_name="my-http-app",
        host=host,
    )

    # Create a user
    response = app_client.post("/users", json={"uid": str(uuid4()), "name": "Alice"})
    response.raise_for_status()
    created_user = response.json()
    logger.info(f"Created user: {created_user}")

    # List all users
    response = app_client.get("/users")
    response.raise_for_status()
    user_list = response.json()
    logger.info(f"All users: {user_list}")

    # Cause a 404, user not found
    non_existent_user_id = uuid4()
    response = app_client.get(f"/users/{non_existent_user_id}")
    assert response.status_code == 404
    logger.info(f"{response.status_code} {response.json()}")

    app_client.close()


if __name__ == "__main__":
    client_example()
