import concurrent.futures
import textwrap
import threading
from pathlib import Path
from typing import Callable, Optional
from uuid import UUID

import httpx
from loguru import logger
from syft_core import Client as SyftBoxClient
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from syft_http_bridge.constants import (
    DEFAULT_MAX_WORKERS,
    HTTP_DIR,
    REQUESTS_DIR,
    RESPONSES_DIR,
)
from syft_http_bridge.serde import (
    deserialize_request,
    serialize_response,
)

DEFAULT_HTTP_APP_SYFTPERM = """
- path: 'syftperm.yaml'
  user: '*'
  permissions:
    - read
- path: 'openapi.json'
  user: '*'
  permissions:
    - read
- path: 'http/requests/*.request'
  user: '*'
  permissions:
    - admin
- path: 'http/responses/*.response'
  user: '*'
  permissions:
    - admin
"""


class EndpointNotAllowed(Exception):
    """Exception raised when an endpoint is not allowed."""


class SerializedHttpProxy:
    """Base class for a proxy that processes serialized HTTP requests and responses."""

    def __init__(
        self,
        response_handler: Callable[[UUID, bytes], None],
        http_client: httpx.Client,
        max_workers: int = DEFAULT_MAX_WORKERS,
        allowed_endpoints: Optional[list[str]] = None,
        disallowed_endpoints: Optional[list[str]] = None,
    ):
        self.response_handler = response_handler
        self.http_client = http_client
        self.allowed_endpoints = allowed_endpoints
        self.disallowed_endpoints = disallowed_endpoints

        self.use_thread_pool = max_workers > 0
        self.max_workers = max_workers
        if self.use_thread_pool:
            self.thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="proxy-worker",
            )
        else:
            self.thread_pool = None

    def _prepare_headers(self, headers: httpx.Headers) -> httpx.Headers:
        headers_to_remove = ["Host", "host"]
        for h in headers_to_remove:
            try:
                del headers[h]
            except KeyError:
                pass
        return headers

    def _prepare_request(
        self,
        request: httpx.Request,
    ) -> httpx.Request:
        return self.http_client.build_request(
            method=request.method,
            url=request.url.path,
            params=request.url.params,
            headers=self._prepare_headers(request.headers),
            content=request.content,
            extensions=request.extensions,
        )

    def _validate_request(self, request: httpx.Request) -> None:
        """Validate a request based on the allow/disallow lists."""
        url = request.url.path
        if self.allowed_endpoints and url not in self.allowed_endpoints:
            raise EndpointNotAllowed(f"Endpoint {url} is not in allowed_endpoints")
        if self.disallowed_endpoints and url in self.disallowed_endpoints:
            raise EndpointNotAllowed(f"Endpoint {url} is in disallowed_endpoints")

    def handle_request(self, request_id: UUID, serialized_request: bytes) -> None:
        """Handle a serialized HTTP request and pass the response to the handler."""
        try:
            request = deserialize_request(serialized_request)
            self._validate_request(request)

            forwarded_request = self._prepare_request(request)
            logger.debug(f"Sending request {request_id} to {forwarded_request.url}")
            response = self.http_client.send(forwarded_request)
            serialized_response = serialize_response(response)
        except EndpointNotAllowed as e:
            logger.warning(f"Skipping request {request_id}: {str(e)}")
            error_response = httpx.Response(
                status_code=403,
                json={"request_id": str(request_id), "error": "Forbidden"},
            )
            serialized_response = serialize_response(error_response)
        except Exception as e:
            logger.exception(f"Error processing request {request_id}: {str(e)}")
            error_response = httpx.Response(
                status_code=500, json={"error": str(e), "request_id": str(request_id)}
            )
            serialized_response = serialize_response(error_response)

        self.response_handler(request_id, serialized_response)

    def submit_request(self, request_id: UUID, serialized_request: bytes) -> None:
        """Submit a request to be processed by the thread pool."""
        if self.use_thread_pool:
            self.thread_pool.submit(self.handle_request, request_id, serialized_request)
        else:
            self.handle_request(request_id, serialized_request)

    def stop(self) -> None:
        """Shutdown the thread pool."""
        if self.thread_pool is not None:
            self.thread_pool.shutdown(
                wait=True,
                cancel_futures=True,
            )


class RequestFileHandler(FileSystemEventHandler):
    """Watchdog event handler that processes request files."""

    def __init__(self, proxy):
        self.proxy = proxy

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory and isinstance(event, FileCreatedEvent):
            request_path = Path(event.src_path)
            if request_path.suffix == ".request":
                self.proxy.process_request_file(request_path)


class FileSystemProxy(SerializedHttpProxy):
    """Proxy that watches a directory for request files and writes responses to files."""

    def __init__(
        self,
        requests_dir: Path,
        responses_dir: Path,
        http_client: httpx.Client,
        max_workers: int = DEFAULT_MAX_WORKERS,
        allowed_endpoints: Optional[list[str]] = None,
        disallowed_endpoints: Optional[list[str]] = None,
    ):
        self.requests_dir = requests_dir
        self.responses_dir = responses_dir

        # Initialize with a custom response handler that writes to files
        super().__init__(
            response_handler=self._write_response_to_file,
            http_client=http_client,
            max_workers=max_workers,
            allowed_endpoints=allowed_endpoints,
            disallowed_endpoints=disallowed_endpoints,
        )

        self.event_handler = RequestFileHandler(self)
        self.observer = Observer()
        self._stop_event = threading.Event()

    def _write_response_to_file(
        self, request_id: UUID, serialized_response: bytes
    ) -> None:
        """Write serialized response to a file in the responses directory."""
        response_path = self.responses_dir / f"{request_id}.response"
        response_path.write_bytes(serialized_response)
        logger.debug(f"Wrote response to {response_path}")

    def process_request_file(self, request_path: Path) -> None:
        """Process a single request file."""
        try:
            request_id = UUID(request_path.stem)

            # Skip if response already exists
            if (self.responses_dir / f"{request_id}.response").exists():
                request_path.unlink()
                logger.warning("Skipping request {request_id}, response already exists")
                return

            serialized_request = request_path.read_bytes()
            self.submit_request(request_id, serialized_request)
            request_path.unlink()
        except Exception as e:
            logger.error(f"Error processing request file {request_path}: {str(e)}")

    def process_pending_requests(self) -> None:
        """Process all existing request files in the requests directory."""
        for request_path in self.requests_dir.glob("*.request"):
            self.process_request_file(request_path)

    def _init_app(self) -> None:
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start watching the requests directory for new request files."""
        self._init_app()

        logger.info(f"Watching {self.requests_dir} for request files")
        self.observer.schedule(
            self.event_handler,
            str(self.requests_dir),
            recursive=False,
        )
        self.observer.start()

        logger.info("Processing existing request files")
        self.process_pending_requests()

    def run_forever(self):
        """Start watching and wait until stopped."""
        self.start()
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=1)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, stopping...")
        except Exception as e:
            logger.error(f"Error while watching directory: {e}")
            raise
        finally:
            # Only stop if not already stopped
            if not self._stop_event.is_set():
                self.stop()

    def stop(self):
        """Stop watching the directory and clean up resources."""
        logger.debug("Stopping file system proxy")
        self._stop_event.set()

        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()

        if self.use_thread_pool:
            self.thread_pool.shutdown(wait=True)


class SyftHttpBridge(FileSystemProxy):
    """Bridge that connects Syft's filesystem with HTTP requests/responses."""

    def __init__(
        self,
        app_name: str,
        http_client: httpx.Client,
        host: Optional[str] = None,
        syftbox_client: Optional[SyftBoxClient] = None,
        auto_create_dirs: bool = True,
        max_workers: int = DEFAULT_MAX_WORKERS,
        openapi_json_url: Optional[str] = None,
        allowed_endpoints: Optional[list[str]] = None,
        disallowed_endpoints: Optional[list[str]] = None,
    ):
        """
        Creates a syftbox to HTTP adapter.
        - Watches for requests in the `http/requests` directory.
        - Sends requests to the specified app via the `http_client`.
        - Writes responses to the `http/responses` directory
        """
        self.syftbox_client = syftbox_client or SyftBoxClient.load()
        self.host = host or self.syftbox_client.email
        self.app_name = app_name
        self.app_dir = self.syftbox_client.api_data(app_name, datasite=self.host)
        self.openapi_json_url = openapi_json_url

        if auto_create_dirs:
            self.app_dir.mkdir(parents=True, exist_ok=True)

        http_dir = self.app_dir / HTTP_DIR
        requests_dir = http_dir / REQUESTS_DIR
        responses_dir = http_dir / RESPONSES_DIR

        super().__init__(
            requests_dir=requests_dir,
            responses_dir=responses_dir,
            http_client=http_client,
            max_workers=max_workers,
            allowed_endpoints=allowed_endpoints,
            disallowed_endpoints=disallowed_endpoints,
        )
        self._display_settings()

    def _display_settings(self):
        settings_str = f"""
        SyftBox HTTP Bridge Settings:
        app name: {self.app_name}
        base URL: {self.http_client.base_url}
        host: {self.host}
        app dir: {self.app_dir}
        num workers: {self.max_workers}
        allowed endpoints: {self.allowed_endpoints}
        disallowed endpoints: {self.disallowed_endpoints}
        """

        logger.info(textwrap.dedent(settings_str))

    def _create_syftperm(self):
        syftperm_path = self.app_dir / "syftperm.yaml"
        syftperm_path.write_text(DEFAULT_HTTP_APP_SYFTPERM)

    def _create_openapi_json(self):
        if not self.openapi_json_url:
            return

        logger.debug("Fetching OpenAPI JSON")
        openapi_path = self.app_dir / "openapi.json"
        response = self.http_client.get(self.openapi_json_url)
        if response.status_code == 200:
            openapi_path.write_text(response.text)
        else:
            logger.error(
                f"Failed to fetch OpenAPI JSON: {response.status_code} {response.text}"
            )

    def _init_app(self):
        """Initialize the app directory with default permissions."""
        super()._init_app()
        self._create_syftperm()
        self._create_openapi_json()
