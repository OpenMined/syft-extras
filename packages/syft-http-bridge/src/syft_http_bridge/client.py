import time
import uuid
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import httpx
from httpx import BaseTransport, Request, Response
from loguru import logger
from syft_core import Client as SyftBoxClient

from syft_http_bridge.constants import (
    HTTP_DIR,
    REQUEST_ID_HEADER,
    REQUESTS_DIR,
    RESPONSES_DIR,
    USER_HEADER,
)
from syft_http_bridge.serde import deserialize_response, serialize_request


def _prepare_request(
    request: Request,
    request_id: UUID,
    requesting_user: Optional[str] = None,
) -> Request:
    """Prepare a request by adding headers."""
    request.headers[REQUEST_ID_HEADER] = str(request_id)
    if requesting_user:
        request.headers[USER_HEADER] = requesting_user
    return request


def send_request_file(
    request: Request, requests_dir: Path, requesting_user: Optional[str] = None
) -> UUID:
    """Serialize and save it to requests_dir."""
    request_id = uuid.uuid4()
    request = _prepare_request(request, request_id, requesting_user=requesting_user)

    serialized_request = serialize_request(request)
    request_path = requests_dir / f"{request_id}.request"

    # Ensure directory exists
    requests_dir.mkdir(parents=True, exist_ok=True)

    # Write request to filesystem
    request_path.write_bytes(serialized_request)

    return request_id


def get_response_file(
    request_id: UUID, responses_dir: Path, delete_response: bool = True
) -> Optional[Response]:
    """Get a response from response_dir if it exists."""
    response_path = responses_dir / f"{request_id}.response"

    if not response_path.exists():
        return None

    try:
        serialized_response = response_path.read_bytes()
        response = deserialize_response(serialized_response)

        if delete_response:
            response_path.unlink(missing_ok=True)

        return response

    except Exception as e:
        logger.warning(f"Error reading response file {response_path}: {str(e)}")
        return None


def wait_for_response_file(
    request_id: UUID,
    responses_dir: Path,
    timeout: float = 60.0,
    poll_interval: float = 0.1,
    delete_response: bool = True,
) -> Response:
    # Ensure directory exists
    responses_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.perf_counter()
    end_time = start_time + timeout

    logger.debug(f"Waiting for response to request {request_id} in {responses_dir}")

    while time.perf_counter() < end_time:
        response = get_response_file(request_id, responses_dir, delete_response)

        if response is not None:
            return response

        time.sleep(poll_interval)

    error_msg = f"Timed out waiting for response to request {request_id}"
    raise TimeoutError(error_msg)


class FileSystemTransport(BaseTransport):
    def __init__(
        self,
        requests_dir: Path,
        responses_dir: Path,
        requesting_user: Optional[str] = None,
        timeout: float = 60.0,
        poll_interval: float = 0.1,
        delete_response: bool = True,
        auto_create_dirs: bool = True,
    ) -> None:
        self.requesting_user = requesting_user
        self.requests_dir = Path(requests_dir)
        self.responses_dir = Path(responses_dir)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.delete_response = delete_response

        if auto_create_dirs:
            self.requests_dir.mkdir(parents=True, exist_ok=True)
            self.responses_dir.mkdir(parents=True, exist_ok=True)

    def handle_request(self, request: Request) -> Response:
        request_id = send_request_file(
            request, self.requests_dir, requesting_user=self.requesting_user
        )
        return wait_for_response_file(
            request_id,
            self.responses_dir,
            self.timeout,
            self.poll_interval,
            self.delete_response,
        )

    def close(self) -> None:
        pass


class SyftFileTransport(FileSystemTransport):
    """
    An HTTP transport that uses the Syft filesystem structure for requests and responses.
    """

    def __init__(
        self,
        app_name: str,
        host: str,
        syftbox_client: Optional[SyftBoxClient] = None,
        timeout: float = 60.0,
        poll_interval: float = 0.1,
        delete_response: bool = True,
        auto_create_dirs: bool = True,
    ) -> None:
        """
        Creates a transport that uses Syft filesystem for HTTP requests/responses.

        Args:
            app_name (str): Name of the app to use
            host (Optional[str], optional): Host datasite to use. Defaults to None.
            syftbox_client (Optional[SyftBoxClient], optional): SyftBoxClient to use. Defaults to None.
            timeout (float, optional): Timeout in seconds. Defaults to 60.0.
            poll_interval (float, optional): Poll interval in seconds. Defaults to 0.1.
            delete_response (bool, optional): Whether to delete response files. Defaults to True.
            auto_create_dirs (bool, optional): Create directories if needed. Defaults to True.
        """
        self.syftbox_client = syftbox_client or SyftBoxClient.load()
        self.host = host
        self.app_name = app_name
        self.app_dir = self.syftbox_client.app_data(app_name, datasite=self.host)

        if auto_create_dirs:
            self.app_dir.mkdir(parents=True, exist_ok=True)

        http_dir = self.app_dir / HTTP_DIR
        requests_dir = http_dir / REQUESTS_DIR
        responses_dir = http_dir / RESPONSES_DIR

        super().__init__(
            requests_dir=requests_dir,
            responses_dir=responses_dir,
            requesting_user=self.syftbox_client.email,
            timeout=timeout,
            poll_interval=poll_interval,
            delete_response=delete_response,
            auto_create_dirs=auto_create_dirs,
        )

    @property
    def app_url(self) -> str:
        return self.syftbox_client.to_syft_url(self.app_dir)


def create_syft_http_client(
    app_name: str,
    host: str,
    syftbox_client: Optional[SyftBoxClient] = None,
    **client_kwargs: Any,
) -> httpx.Client:
    """
    Create an httpx.Client that communicates via Syft filesystem.
    """
    transport = SyftFileTransport(
        app_name=app_name,
        host=host,
        syftbox_client=syftbox_client,
        timeout=client_kwargs.pop("timeout", 60.0),
    )

    # Remove the transport if it was provided, as we're using our custom one
    client_kwargs.pop("transport", None)

    if "base_url" not in client_kwargs:
        client_kwargs["base_url"] = "http://syft"

    return httpx.Client(transport=transport, **client_kwargs)
