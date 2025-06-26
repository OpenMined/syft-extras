import shutil
from pathlib import Path

import typer
from syft_core import Client as SyftBoxClient
from syft_core import SyftClientConfig

from syft_high_low.rsync import (
    RsyncConfig,
    RsyncEntry,
    SSHConnection,
    get_rsync_config_path,
)

app = typer.Typer(
    name="syft-high-low",
    help="CLI for managing high and low datasites in SyftBox",
    no_args_is_help=True,
)


@app.command()
def init_high_datasite(
    email: str = typer.Option(..., help="Email address for the client"),
    dir: Path | None = typer.Option(
        None,
        help="Directory for the datasite data. Defaults to ~/.syftbox/high-datasites/<email>",
    ),
    force_overwrite: bool = typer.Option(
        False, help="Overwrite existing config if present"
    ),
) -> None:
    dir = dir or Path.home() / ".syftbox" / "high-datasites" / email

    if dir.exists() and not force_overwrite:
        typer.echo(
            f"Directory {dir} already exists. Use --force-overwrite to reset your high datasite."
        )
        raise typer.Exit(code=1)

    if force_overwrite and dir.exists():
        typer.echo(f"Removing existing directory {dir}")
        shutil.rmtree(dir)

    dir.mkdir(parents=True, exist_ok=True)
    config_path = dir / "config.json"
    data_dir = dir / "SyftBox"

    syft_config = SyftClientConfig(
        email=email,
        client_url="http://testserver:5000",  # Mock placeholder, not used for high datasites
        path=config_path,
        data_dir=data_dir,
    )
    syft_config.save()

    # Ensure the datasite exists without SyftBox running
    client = SyftBoxClient(conf=syft_config)
    client.datasite_path.mkdir(parents=True, exist_ok=True)

    typer.echo(f"High datasite initialized at {data_dir}")
    typer.echo(f"Configuration saved to {config_path}")


@app.command()
def init_sync_config(
    remote_datasite_path: Path = typer.Option(..., help="Path to the remote datasite"),
    ssh_host: str = typer.Option(None, help="SSH hostname (if using SSH)"),
    ssh_user: str = typer.Option(None, help="SSH username"),
    ssh_port: int = typer.Option(22, help="SSH port"),
    ssh_key_path: Path = typer.Option(None, help="Path to SSH private key"),
    force_overwrite: bool = typer.Option(False, help="Overwrite existing sync config"),
    syftbox_config_path: Path | None = typer.Option(
        None, help="Path to SyftBox config file"
    ),
) -> None:
    """Initialize sync configuration for a high datasite."""
    syftbox_client = SyftBoxClient.load(filepath=syftbox_config_path)
    sync_config_path = get_rsync_config_path(syftbox_client)

    if sync_config_path.exists() and not force_overwrite:
        typer.echo(
            f"Sync config already exists at {sync_config_path}. Use --force-overwrite to replace."
        )
        raise typer.Exit(code=1)

    # Build connection settings
    connection_settings = None
    if ssh_host:
        if not ssh_user:
            typer.echo("SSH user is required when using SSH")
            raise typer.Exit(code=1)
        connection_settings = SSHConnection(
            host=ssh_host, user=ssh_user, port=ssh_port, ssh_key_path=ssh_key_path
        )

    rsync_config = RsyncConfig(
        remote_datasite_path=remote_datasite_path,
        connection_settings=connection_settings,
        entries=[],
    )
    rsync_config.save(syftbox_client)

    typer.echo(f"Sync config initialized at {sync_config_path}")


@app.command()
def add_sync_entry(
    local_dir: Path = typer.Option(..., help="Local directory path"),
    remote_dir: Path = typer.Option(
        ..., help="Remote directory path (relative to remote datasite)"
    ),
    direction: str = typer.Option("pull", help="Sync direction: pull or push"),
    allow_overwrite: bool = typer.Option(
        False, help="Allow overwriting existing files"
    ),
    syftbox_config_path: Path | None = typer.Option(
        None, help="Path to SyftBox config file"
    ),
) -> None:
    """Add a sync entry to the configuration."""
    syftbox_client = SyftBoxClient.load(filepath=syftbox_config_path)
    rsync_config = RsyncConfig.load(syftbox_client)

    entry = RsyncEntry(
        local_dir=local_dir,
        remote_dir=remote_dir,
        direction=direction,
        allow_overwrite=allow_overwrite,
    )
    rsync_config.entries.append(entry)
    rsync_config.save(syftbox_client)

    typer.echo(f"Added sync entry: {local_dir} <-> {remote_dir} ({direction})")


if __name__ == "__main__":
    app()
