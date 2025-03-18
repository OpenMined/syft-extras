import sys
from pathlib import Path
from typing import List, Optional

import httpx
import typer
import yaml
from loguru import logger
from rich.console import Console
from syft_core import Client as SyftBoxClient

from syft_http_bridge.bridge import SyftHttpBridge
from syft_http_bridge.constants import DEFAULT_MAX_WORKERS

cli = typer.Typer(no_args_is_help=True)
console = Console()


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file."""
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        console.print(f"Error loading config: {e}")
        raise typer.Exit(code=1)


@cli.command(
    help="Run the Syft HTTP Bridge, using a config file or command line args. This command will start the bridge and forward incoming requests to the provided base_url.",
    no_args_is_help=True,
)
def run(
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config yaml file. All options below can be set in the config file, and will be overridden by command line args.",
    ),
    app_name: str = typer.Option(None, "--app-name", "-a"),
    base_url: str = typer.Option(None, "--base-url", "-u"),
    host: Optional[str] = typer.Option(None, "--host", "-h"),
    syftbox_client_path: Optional[Path] = typer.Option(None, "--client-path"),
    max_workers: int = typer.Option(None),
    openapi_json_url: Optional[str] = typer.Option(None),
    allowed_endpoints: Optional[List[str]] = typer.Option(None),
    disallowed_endpoints: Optional[List[str]] = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """
    Run the Syft HTTP Bridge, using a config file or command line args.
    This CLI will start the bridge and forward incoming requests to the provided base_url.
    """
    # Set log level
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")

    args = {
        "app_name": app_name,
        "base_url": base_url,
        "host": host,
        "syftbox_client_path": syftbox_client_path,
        "max_workers": max_workers,
        "openapi_json_url": openapi_json_url,
        "allowed_endpoints": allowed_endpoints,
        "disallowed_endpoints": disallowed_endpoints,
    }

    # Update with config file if provided
    if config:
        yaml_config = load_config(config) if config.exists() else {}
        for k, v in yaml_config.items():
            if k in args and args[k] is None:
                args[k] = v

    if not args["app_name"] or not args["base_url"]:
        console.print("[bold red]Error:[/red bold] app_name and base_url are required.")
        raise typer.Exit(code=1)

    try:
        http_client = httpx.Client(base_url=args["base_url"])
        syftbox_client = None
        if args["syftbox_client_path"]:
            syftbox_client = SyftBoxClient.load(args["syftbox_client_path"])
        bridge = SyftHttpBridge(
            app_name=args["app_name"],
            http_client=http_client,
            host=args["host"],
            syftbox_client=syftbox_client,
            max_workers=args["max_workers"] or DEFAULT_MAX_WORKERS,
            openapi_json_url=args["openapi_json_url"],
            allowed_endpoints=args["allowed_endpoints"],
            disallowed_endpoints=args["disallowed_endpoints"],
        )
        bridge.run_forever()
    except Exception as e:
        console.print(f"Error: {e}")
        raise typer.Exit(code=1)
    finally:
        http_client.close()


if __name__ == "__main__":
    cli()
