import time
from pathlib import Path
from typing import Generator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from syft_core import Client as SyftboxClient
from syft_core.config import SyftClientConfig
from syft_http_bridge.bridge import SyftHttpBridge
from syft_http_bridge.client import create_syft_http_client


@pytest.fixture
def test_app():
    app = FastAPI()

    @app.get("/hello")
    def hello():
        return {"message": "Hello World"}

    return app


@pytest.fixture
def http_client(test_app: FastAPI) -> Generator[httpx.Client, None, None]:
    with TestClient(test_app) as client:
        yield client


@pytest.fixture
def syftbox_client(tmp_path: Path) -> SyftboxClient:
    config = SyftClientConfig(
        data_dir=tmp_path,
        email="test@openmined.org",
        server_url="http://testserver",
        client_url="http://testclient",
        path=tmp_path / "config.json",
    )
    return SyftboxClient(config)


@pytest.fixture
def bridge_app(
    http_client: httpx.Client, syftbox_client: SyftboxClient
) -> Generator[SyftHttpBridge, None, None]:
    bridge = SyftHttpBridge(
        app_name="test",
        http_client=http_client,
        syftbox_client=syftbox_client,
    )

    bridge.start()
    time.sleep(0.2)  # wait for watchdog

    yield bridge

    bridge.stop()


def test_syft_http_bridge(
    syftbox_client: SyftboxClient,
    bridge_app: SyftHttpBridge,
):
    # Proxied client that communicates over syftbox via file.
    # Under the hood: syft_http_client -> <uid>.request -> bridge -> test_client -> app -> bridge -> <uid>.response -> syft_http_client
    syft_http_client = create_syft_http_client(
        app_name=bridge_app.app_name,
        host=bridge_app.host,
        syftbox_client=syftbox_client,
    )

    perm_file = bridge_app.app_dir / "syftperm.yaml"
    openapi_json = bridge_app.app_dir / "openapi.json"
    assert perm_file.exists()
    assert openapi_json.exists()

    response = syft_http_client.get("/hello")
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Hello World"}
