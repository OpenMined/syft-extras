"""
Shared test fixtures for syft-crypto tests
"""

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from syft_core import Client
from syft_core.config import SyftClientConfig
from syft_crypto.x3dh_bootstrap import bootstrap_user


def create_temp_client(email: str, workspace_dir: Path) -> Client:
    """Create a temporary Client instance for testing"""
    config: SyftClientConfig = SyftClientConfig(
        email=email,
        data_dir=workspace_dir,
        server_url="http://localhost:8080",
        client_url="http://127.0.0.1:8082",
        path=workspace_dir.parent / ".syftbox" / "config.yaml",
    )
    return Client(config)


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Create isolated temporary workspace for each test"""
    # Create a unique temp directory for this test
    temp_dir: str = tempfile.mkdtemp()
    workspace: Path = Path(temp_dir) / "SyftBox"
    workspace.mkdir(parents=True, exist_ok=True)

    dot_syftbox_dir: Path = workspace.parent / ".syftbox"
    dot_syftbox_dir.mkdir(parents=True, exist_ok=True)

    yield workspace

    # Clean up after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def alice_client(temp_workspace: Path) -> Client:
    """Create Alice client with bootstrapped keys"""
    client: Client = create_temp_client("alice@example.com", temp_workspace)
    bootstrap_user(client)
    return client


@pytest.fixture
def bob_client(temp_workspace: Path) -> Client:
    """Create Bob client with bootstrapped keys"""
    client: Client = create_temp_client("bob@example.com", temp_workspace)
    bootstrap_user(client)
    return client


@pytest.fixture
def unbootstrapped_client(temp_workspace: Path) -> Client:
    """Create client without bootstrapped keys"""
    return create_temp_client("charlie@example.com", temp_workspace)
