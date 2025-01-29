from functools import lru_cache
from typing import Optional

from syft_core.client_shim import Client
from tinydb import TinyDB, where

from syft_rpc.protocol import SyftFuture


@lru_cache(typed=True)
def __future_db_path(app_name: str, client: Client) -> str:
    rpc_dir = client.api_data(app_name) / "rpc"
    rpc_dir.mkdir(exist_ok=True, parents=True)
    return str(rpc_dir / ".futures.json")


@lru_cache(typed=True)
def __future_db(app_name: str, client: Client) -> TinyDB:
    return TinyDB(__future_db_path(app_name, client))


def save_future(future: SyftFuture, app_name: str, client: Client = None):
    client = client or Client.load()
    db = __future_db(app_name, client)
    return db.insert(future.model_dump(mode="json"))


def load_future(
    future_id: str, app_name: str, client: Client = None
) -> Optional[SyftFuture]:
    client = client or Client.load()
    db = __future_db(app_name, client)
    data = db.get(where("ulid") == future_id)
    if not data:
        return None
    return SyftFuture(**data)
