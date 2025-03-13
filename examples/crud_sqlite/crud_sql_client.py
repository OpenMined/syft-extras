from __future__ import annotations

import argparse
from typing import List
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, Field
from syft_core import Client
from syft_rpc import rpc


class User(BaseModel):
    uid: UUID = Field(default_factory=uuid4)
    name: str


class UserList(BaseModel):
    users: List[User]


def client_example(client=None):
    if client is None:
        client = Client.load()
    
    logger.info(f"Connected as: {client.email}")

    # Create 3 users
    for name in ["Alice", "Bob", "Charlie"]:
        create_future = rpc.send(
            url=rpc.make_url(client.email, "my-crud-sql-app", "user/create"),
            body=User(name=name),
            expiry="5m",
        )

        response = create_future.wait(timeout=5)
        response.raise_for_status()
        user = response.model(User)
        logger.info(f"Created user: {user}")

    # List all users
    list_future = rpc.send(
        url=rpc.make_url(client.email, "my-crud-sql-app", "user/list"),
        body={},
        expiry="5m",
    )

    response = list_future.wait(timeout=5)
    response.raise_for_status()
    user_list = response.model(UserList)
    logger.info(f"All users: {user_list.users}")

    # Get the first user
    if user_list.users:
        first_user_id = user_list.users[0].uid
        get_future = rpc.send(
            url=rpc.make_url(client.email, "my-crud-sql-app", "user/get"),
            body=first_user_id,
            expiry="5m",
        )

        response = get_future.wait(timeout=5)
        response.raise_for_status()
        user = response.model(User)
        logger.info(f"Retrieved user: {user}")

        # Delete the first user
        delete_future = rpc.send(
            url=rpc.make_url(client.email, "my-crud-sql-app", "user/delete"),
            body=first_user_id,
            expiry="5m",
        )

        response = delete_future.wait(timeout=5)
        response.raise_for_status()
        deleted_user = response.model(User)
        logger.info(f"Deleted user: {deleted_user}")

        # List users again to show deletion
        list_future = rpc.send(
            url=rpc.make_url(client.email, "my-crud-sql-app", "user/list"),
            body={},
            expiry="5m",
        )

        response = list_future.wait(timeout=5)
        response.raise_for_status()
        user_list = response.model(UserList)
        logger.info(f"Remaining users: {user_list.users}")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SQLite CRUD Client")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    args = parser.parse_args()

    # Initialize client with config if provided
    client = Client.load(args.config)
    client_example(client)


if __name__ == "__main__":
    main()
