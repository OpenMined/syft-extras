from pathlib import Path
from typing import Dict, List
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from loguru import logger
from pydantic import BaseModel, Field
from syft_http_bridge import SyftHttpBridge

BASE_DIR = Path(__file__).parent


# Define data models
class User(BaseModel):
    uid: UUID = Field(default_factory=uuid4)
    name: str


# Create FastAPI app with CRUD endpoints
app = FastAPI(title="User CRUD API")
user_store: Dict[UUID, User] = {}


@app.post("/users", response_model=User)
def create_user(user: User):
    user_store[user.uid] = user
    return user


@app.get("/users/{uid}", response_model=User)
def get_user(uid: UUID):
    if uid not in user_store:
        raise HTTPException(status_code=404, detail="User not found")
    return user_store[uid]


@app.get("/users", response_model=List[User])
def list_users():
    return list(user_store.values())


def run_server():
    """Run the server with TestClient over SyftBox."""
    http_client: httpx.Client = TestClient(app)

    # OR:
    # uvicorn.run(app, port=8000)
    # http_client = httpx.Client(base_url="http://localhost:8000")

    bridge_app = SyftHttpBridge(
        app_name="my-http-app",
        http_client=http_client,
    )

    logger.info(f"Server started - watching for requests in {bridge_app.requests_dir}")
    bridge_app.run_forever()


if __name__ == "__main__":
    run_server()
