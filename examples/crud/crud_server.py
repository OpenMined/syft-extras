import argparse
from typing import Dict, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from syft_event import EventRouter, SyftEvents
from syft_core import Client


class User(BaseModel):
    uid: UUID = Field(default_factory=uuid4)
    name: str


# NOTE using a pydantic model for our /list endpoint to hande serde
class UserList(BaseModel):
    users: List[User]


user_router = EventRouter()


@user_router.on_request("/create")
def create_user(user: User, app: SyftEvents) -> User:
    store = app.state["store"]
    store[user.uid] = user
    return user


@user_router.on_request("/get")
def get_user(uid: UUID, app: SyftEvents) -> User:
    store = app.state["store"]
    return store.get(uid)


@user_router.on_request("/delete")
def delete_user(uid: UUID, app: SyftEvents) -> User:
    store = app.state["store"]
    return store.pop(uid)


@user_router.on_request("/list")
def list_users(app: SyftEvents) -> UserList:
    store = app.state["store"]
    return UserList(users=list(store.values()))


def create_app(client=None) -> SyftEvents:
    """
    Implementation note: By isolating the app and dependencies in a function,
    we can create multiple instances of the app with different states.

    This is useful for testing and running multiple instances of the app,
    without having to worry about global state.
    """
    if client is None:
        client = Client.load()
        
    app = SyftEvents("my-crud-app", client=client)

    store: Dict[UUID, User] = {}
    app.state["store"] = store
    app.include_router(user_router, prefix="/user")
    return app


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="CRUD Server")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    args = parser.parse_args()
    
    # Initialize client with config if provided
    client = Client.load(args.config)
    print(f"Running as user: {client.email}")
    
    app = create_app(client)
    
    try:
        print("Running CRUD server:", app.app_rpc_dir)
        app.run_forever()
    except KeyboardInterrupt:
        print("Server stopped.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
