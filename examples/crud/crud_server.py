from typing import Dict, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from syft_event import EventRouter, SyftEvents


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


def create_app() -> SyftEvents:
    """
    Implementation note: By isolating the app and dependencies in a function,
    we can create multiple instances of the app with different states.

    This is useful for testing and running multiple instances of the app,
    without having to worry about global state.
    """
    app = SyftEvents("my-crud-app")

    store: Dict[UUID, User] = {}
    app.state["store"] = store
    app.include_router(user_router, prefix="/user")
    return app


if __name__ == "__main__":
    app = create_app()
    app.run_forever()
