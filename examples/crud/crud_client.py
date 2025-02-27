from __future__ import annotations

import time
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


def client_example():
    client = Client.load()

    # Create 3 users
    for name in ["Alice", "Bob", "Charlie"]:
        create_future = rpc.send(
            url=f"syft://{client.email}/api_data/my-crud-app/rpc/user/create",
            body=User(name=name),
            expiry="5m",
        )

        response = create_future.wait(timeout=5)
        response.raise_for_status()
        user = response.model(User)
        logger.info(f"Created user: {user}")

    # List all users
    list_future = rpc.send(
        url=f"syft://{client.email}/api_data/my-crud-app/rpc/user/list",
        body={},
        expiry="5m",
    )

    response = list_future.wait(timeout=5)
    response.raise_for_status()
    user_list = response.model(UserList)
    logger.info(f"All users: {user_list.users}")


if __name__ == "__main__":
    client_example()
