from pathlib import Path

from pydantic import AnyHttpUrl
from syft_core.config import SyftClientConfig


def test_init(tmp_path: Path):
    config = SyftClientConfig(
        path=tmp_path / "config.json",
        data_dir=tmp_path / "data",
        email="dummy@openmined.org",
        server_url="https://syftbox.openmined.org",
        client_url="http://localhost:8080",
    )

    assert config.path.parent == tmp_path
    assert isinstance(config.server_url, AnyHttpUrl)
    assert isinstance(config.client_url, AnyHttpUrl)


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
