from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator
from syft_core import Client as SyftBoxClient
from syft_core import SyftClientConfig


class ConnectionType(StrEnum):
    SSH = "ssh"
    LOCAL = "local"


class SSHConnection(BaseModel):
    host: str
    port: int = 22
    user: str
    ssh_key_path: Path | None = None


class RsyncEntry(BaseModel):
    local_dir: Path
    remote_dir: Path
    direction: Literal["push", "pull"] = "push"
    ignore_existing: bool = True


class RsyncConfig(BaseModel):
    remote_datasite_path: Path
    connection_settings: SSHConnection | None = None
    entries: list[RsyncEntry] = []

    @property
    def connection_type(self) -> ConnectionType:
        if self.connection_settings is None:
            return ConnectionType.LOCAL
        return ConnectionType.SSH

    def save(self, syftbox_client: SyftBoxClient) -> None:
        config_path = get_rsync_config_path(syftbox_client)
        config_path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, syftbox_client: SyftBoxClient) -> "RsyncConfig":
        config_path = get_rsync_config_path(syftbox_client)
        if not config_path.exists():
            raise FileNotFoundError(
                f"High side sync config file not found at {config_path}"
            )

        return cls.model_validate_json(config_path.read_text())


def get_rsync_config_path(
    syftbox_client: SyftBoxClient,
) -> Path:
    return syftbox_client.datasite_path / "high_side_sync.json"


def generate_rsync_command(
    entry: RsyncEntry,
    connection: SSHConnection | None = None,
) -> str:
    # Base rsync flags
    flags = "-av"
    if entry.ignore_existing:
        flags += " --ignore-existing"

    if connection is None:
        # Local rsync
        if entry.direction == "pull":
            return f"rsync {flags} {entry.remote_dir}/ {entry.local_dir}/"
        else:
            return f"rsync {flags} {entry.local_dir}/ {entry.remote_dir}/"
    else:
        # SSH rsync
        ssh_opts = f"-p {connection.port}"
        if connection.ssh_key_path:
            ssh_opts += f" -i {connection.ssh_key_path}"

        remote_path = f"{connection.user}@{connection.host}:{entry.remote_dir}/"

        if entry.direction == "pull":
            return f"rsync {flags} -e 'ssh {ssh_opts}' {remote_path} {entry.local_dir}/"
        else:
            return f"rsync {flags} -e 'ssh {ssh_opts}' {entry.local_dir}/ {remote_path}"
