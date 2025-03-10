from pathlib import Path
import pytest
from syft_core.client_shim import Client
from syft_rpc import rpc
from syft_core.config import SyftClientConfig
from syft_rpc.protocol import SyftError


def test_write_permission(tmp_path: Path):
    config = SyftClientConfig(
        email="client@openmined.org",
        path=tmp_path,
        data_dir=tmp_path / "data",
        client_url="http://unused_url:0",
    )
    client = Client(config)

    # TODO should raise once we validate permissions instead of just logging
    # with pytest.raises(SyftError):
    rpc.send(
        url="syft://server@openmined.org/api_data/pingpong/rpc/ping",
        body="hello",
        expiry="5m",
        cache=True,
        client=client,
    )
