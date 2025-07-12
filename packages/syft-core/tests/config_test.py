from pathlib import Path

from pydantic import AnyHttpUrl
from syft_core.config import SyftClientConfig


def test_simple(tmp_path: Path):
    config = SyftClientConfig(
        path=tmp_path / "config.json",
        data_dir=tmp_path / "data",
        email="dummy@openmined.org",
        server_url="https://syftbox.openmined.org",
    )

    assert config.path.parent == tmp_path
    assert isinstance(config.server_url, AnyHttpUrl)
    assert config.client_url is None
    assert config.client_token is None
    assert config.refresh_token is None


def test_control_plane(tmp_path: Path):
    config = SyftClientConfig(
        path=tmp_path / "config.json",
        data_dir=tmp_path / "data",
        email="dummy@openmined.org",
        server_url="https://syftbox.openmined.org",
        client_url="http://localhost:7938",
        client_token="dummy-token",
        refresh_token="dummy-refresh-token",
    )

    assert config.path.parent == tmp_path
    assert isinstance(config.server_url, AnyHttpUrl)
    assert config.client_url.host == "localhost"
    assert config.client_url.port == 7938
    assert config.client_token == "dummy-token"
    assert config.refresh_token == "dummy-refresh-token"


def test_serialize(tmp_path: Path):
    config = SyftClientConfig(
        path=tmp_path / "config.json",
        data_dir=tmp_path / "data",
        email="dummy@openmined.org",
        server_url="https://syftbox.openmined.org",
        client_url="http://localhost:8080",
    )

    serialized = config.model_dump(mode="json")
    assert isinstance(serialized["client_url"], str)
