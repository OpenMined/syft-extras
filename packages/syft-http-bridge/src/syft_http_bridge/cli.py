import sys
from pathlib import Path
from typing import Annotated, List, Optional

import httpx
import typer
from loguru import logger
from rich.console import Console
from syft_core import Client as SyftBoxClient
from typer import Option

from syft_http_bridge.bridge import SyftHttpBridge
from syft_http_bridge.constants import DEFAULT_MAX_WORKERS

cli = typer.Typer(no_args_is_help=True)
console = Console()


@cli.command()
def run(
    app_name: Annotated[str, Option()],
    base_url: Annotated[str, Option()],
    host: Annotated[Optional[str], Option()] = None,
    client_path: Annotated[Optional[Path], Option()] = None,
    workers: Annotated[int, Option()] = DEFAULT_MAX_WORKERS,
    openapi_url: Annotated[Optional[str], Option()] = None,
    allowed_endpoints: Annotated[Optional[List[str]], Option()] = None,
    disallowed_endpoints: Annotated[Optional[List[str]], Option()] = None,
    verbose: Annotated[bool, Option(is_flag=True)] = False,
):
    """
    Run the Syft HTTP Bridge.

    This command will start the bridge and forward incoming requests to the provided base_url."""
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")

    try:
        http_client = httpx.Client(base_url=base_url)
        syftbox_client = None
        if client_path:
            syftbox_client = SyftBoxClient.load(client_path)

        bridge = SyftHttpBridge(
            app_name=app_name,
            http_client=http_client,
            host=host,
            syftbox_client=syftbox_client,
            max_workers=workers,
            openapi_json_url=openapi_url,
            allowed_endpoints=allowed_endpoints,
            disallowed_endpoints=disallowed_endpoints,
        )
        bridge.run_forever()
    except KeyboardInterrupt:
        console.print("[yellow]Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
