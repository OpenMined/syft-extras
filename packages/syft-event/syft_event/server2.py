from __future__ import annotations

import asyncio
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any
import traceback

from loguru import logger
from syft_core import Client
from syft_rpc import rpc
from syft_rpc.protocol import SyftRequest, SyftStatus
from typing_extensions import Callable, List, Optional, Type, Union
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEvent
from watchdog.observers import Observer

from syft_event.deps import func_args_from_request
from syft_event.handlers import AnyPatternHandler, RpcRequestHandler
from syft_event.router import EventRouter
from syft_event.schema import generate_schema
from syft_event.types import Response

DEFAULT_WATCH_EVENTS: List[Type[FileSystemEvent]] = [
    FileCreatedEvent,
    FileModifiedEvent,
]

PERMS = """
rules:
- pattern: rpc.schema.json
  access:
    read:
    - '*'
- pattern: '**/*.request'
  access:
    read:
    - '*'
    write:
    - '*'
- pattern: '**/*.response'
  access:
    read:
    - '*'
    write:
    - '*'
"""


class SyftEvents:
    """
    SyftEvents server for handling RPC requests and file system events.

    This class provides a framework for creating event-driven applications that can:
    - Handle RPC requests via file system events
    - Watch for file changes and trigger handlers
    - Generate and publish API schemas
    - Provide configurable error handling with security considerations

    Error Handling Strategy:
    - **Client Errors** (request loading, schema validation): Always shown to help clients understand what they did wrong
    - **Server Errors** (function execution):
      - Production mode: Generic error message for security
      - Debug mode: Full error details including traceback for debugging
    """

    def __init__(
        self,
        app_name: str,
        publish_schema: bool = True,
        client: Optional[Client] = None,
        debug_mode: bool = False,
    ):
        self.app_name = app_name
        self.schema = publish_schema
        self.state: dict[str, Any] = {}
        self.client = client or Client.load()
        self.app_dir = self.client.app_data(self.app_name)
        self.app_rpc_dir = self.app_dir / "rpc"
        self.obs = Observer()
        self.__rpc: dict[Path, Callable] = {}
        self._stop_event = Event()
        self._thread_pool = ThreadPoolExecutor()

        # Debug mode configuration - explicit boolean
        self.debug_mode = debug_mode

    def set_debug_mode(self, enabled: bool) -> None:
        """
        Enable or disable debug mode at runtime.

        Args:
            enabled: True to enable debug mode, False to disable
        """
        self.debug_mode = enabled
        logger.info(f"Debug mode {'enabled' if enabled else 'disabled'}")

    def init(self) -> None:
        # setup dirs
        self.app_dir.mkdir(exist_ok=True, parents=True)
        self.app_rpc_dir.mkdir(exist_ok=True, parents=True)

        # write perms
        perms = self.app_rpc_dir / "syft.pub.yaml"
        perms.write_text(PERMS)

        # publish schema
        if self.schema:
            self.publish_schema()

    def start(self, process_pending_requests: bool = True) -> None:
        self.init()
        # process pending requests
        try:
            if process_pending_requests:
                self.process_pending_requests()
        except Exception as e:
            print("Error processing pending requests", e)
            raise

        # start Observer
        self.obs.start()

    def publish_schema(self) -> None:
        schema = {}
        for endpoint, handler in self.__rpc.items():
            handler_schema = generate_schema(handler)
            ep_name = endpoint.relative_to(self.app_rpc_dir)
            ep_name = "/" + str(ep_name).replace("\\", "/")
            schema[ep_name] = handler_schema

        schema_path = self.app_rpc_dir / "rpc.schema.json"
        schema_path.write_text(json.dumps(schema, indent=2))
        logger.info(f"Published schema to {schema_path}")

    def process_pending_requests(self) -> None:
        # process all pending requests
        for path in self.app_rpc_dir.glob("**/*.request"):
            if path.with_suffix(".response").exists():
                continue
            if path.parent in self.__rpc:
                handler = self.__rpc[path.parent]
                logger.debug(f"Processing pending request {path.name}")
                self.__handle_rpc(path, handler)

    def run_forever(self) -> None:
        logger.info(f"Started watching for files. RPC Directory = {self.app_rpc_dir}")
        self.start()
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=5)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Error in event loop: {e}")
            raise
        finally:
            self.stop()

    def stop(self) -> None:
        logger.debug("Stopping event loop")
        self._stop_event.set()
        self.obs.stop()
        self.obs.join()
        self._thread_pool.shutdown(wait=True)

    def include_router(self, router: EventRouter, *, prefix: str = "") -> None:
        """Include all routes from a router with an optional prefix."""
        for endpoint, func in router.routes.items():
            endpoint_with_prefix = f"{prefix}{endpoint}"
            _ = self.on_request(endpoint_with_prefix)(func)

    def on_request(self, endpoint: str) -> Callable:
        """Bind function to RPC requests at an endpoint"""

        def register_rpc(func):
            epath = self.__to_endpoint_path(endpoint)
            self.__register_rpc(epath, func)
            logger.info(f"Register RPC: {endpoint}")
            return func

        return register_rpc

    def watch(
        self,
        glob_path: Union[str, List[str]],
        event_filter: List[Type[FileSystemEvent]] = DEFAULT_WATCH_EVENTS,
    ):
        """Invoke the handler if any file changes in the glob path"""

        if not isinstance(glob_path, list):
            glob_path = [glob_path]

        globs = [self.__format_glob(path) for path in glob_path]

        def register_watch(func):
            def watch_cb(event):
                return func(event)

            self.obs.schedule(
                # use raw path for glob which will be convert to path/*.request
                AnyPatternHandler(globs, watch_cb),
                path=str(self.client.datasites),
                recursive=True,
                event_filter=event_filter,
            )
            logger.info(f"Register Watch: {globs}")
            return watch_cb

        return register_watch

    def __handle_rpc(self, path: Path, func: Callable):
        req = None
        try:
            # may happen =)
            if not path.exists():
                return
            try:
                req = SyftRequest.load(path)
            except Exception as e:
                logger.error(f"Error loading request {path}", e)
                # Request loading errors are safe to show in production
                rpc.write_response(
                    path,
                    body=f"Error loading request: {repr(e)}",
                    status_code=SyftStatus.SYFT_400_BAD_REQUEST,
                    client=self.client,
                )
                return

            if req.is_expired:
                logger.debug(f"Request expired: {req}")
                rpc.reply_to(
                    req,
                    body="Request expired",
                    status_code=SyftStatus.SYFT_419_EXPIRED,
                    client=self.client,
                )
                return

            try:
                kwargs = func_args_from_request(func, req, self)
            except Exception as e:
                logger.warning(f"Invalid request body schema {req.url}: {e}")
                # Schema validation errors are safe to show in production
                rpc.reply_to(
                    req,
                    body=f"Invalid request schema: {str(e)}",
                    status_code=SyftStatus.SYFT_400_BAD_REQUEST,
                    client=self.client,
                )
                return

            # call the function

            # check if the function is a coroutine
            try:
                if inspect.iscoroutinefunction(func):
                    # if it is, run it in a new event loop in a separate thread
                    future = self._thread_pool.submit(asyncio.run, func(**kwargs))
                    resp = future.result()
                else:
                    # if it is not, call it directly
                    resp = func(**kwargs)
            except Exception as e:
                logger.error(f"Error calling function {func.__name__}: {e}")
                logger.error(traceback.format_exc())

                # Function execution errors are potentially dangerous
                # use debug mode logic to show full error details
                # in production mode, return generic error message
                if self.debug_mode:
                    resp = Response(
                        body=json.dumps(
                            {
                                "error_type": type(e).__name__,
                                "error_message": str(e),
                                "function_name": func.__name__,
                                "traceback": traceback.format_exc(),
                            },
                            indent=2,
                        ),
                        status_code=SyftStatus.SYFT_500_SERVER_ERROR,
                        headers={"Content-Type": "application/json"},
                    )
                else:
                    # In production mode, return generic error message
                    resp = Response(
                        body="Internal server error. Please try again later.",
                        status_code=SyftStatus.SYFT_500_SERVER_ERROR,
                    )

            if isinstance(resp, Response):
                resp_data = resp.body
                resp_code = SyftStatus(resp.status_code)
                resp_headers = resp.headers
            else:
                resp_data = resp
                resp_code = SyftStatus.SYFT_200_OK
                resp_headers = {}

            rpc.reply_to(
                req,
                body=resp_data,
                headers=resp_headers,
                status_code=resp_code,
                client=self.client,
            )
        except Exception as e:
            raise e

    def __register_rpc(self, endpoint: Path, handler: Callable) -> Callable:
        def rpc_callback(event: FileSystemEvent):
            return self.__handle_rpc(Path(event.src_path), handler)

        # make sure dir exists
        endpoint.mkdir(exist_ok=True, parents=True)
        # touch the keep file
        (endpoint / ".syftkeep").touch()

        self.obs.schedule(
            RpcRequestHandler(rpc_callback),
            path=str(endpoint),
            recursive=True,
            event_filter=[FileCreatedEvent],
        )
        # this is used for processing pending requests + generating schema
        self.__rpc[endpoint] = handler
        return rpc_callback

    def __to_endpoint_path(self, endpoint: str) -> Path:
        if "*" in endpoint or "?" in endpoint:
            raise ValueError("wildcards are not allowed in path")

        # this path must exist so that watch can emit events
        return self.app_rpc_dir / endpoint.lstrip("/").rstrip("/")

    def __format_glob(self, path: str) -> str:
        # replace placeholders with actual values
        path = path.format(
            email=self.client.email,
            datasite=self.client.email,
            app_data=self.client.app_data(self.app_name),
        )
        if not path.startswith("**/"):
            path = f"**/{path}"
        return path


if __name__ == "__main__":
    box = SyftEvents("test_app")

    # requests are always bound to the app
    # root path = {datasite}/app_data/{app_name}/rpc
    @box.on_request("/endpoint")
    def endpoint_request(req):
        print("rpc /endpoint:", req)

    # requests are always bound to the app
    # root path = {datasite}/app_data/{app_name}/rpc
    @box.on_request("/another")
    def another_request(req):
        print("rpc /another: ", req)

    # root path = ~/SyftBox/datasites/
    @box.watch("{datasite}/**/*.json")
    def all_json_on_my_datasite(event):
        print("watch {datasite}/**/*.json:".format(datasite=box.client.email), event)

    # root path = ~/SyftBox/datasites/
    @box.watch("test@openined.org/*.json")
    def jsons_in_some_datasite(event):
        print("watch test@openined.org/*.json:", event)

    # root path = ~/SyftBox/datasites/
    @box.watch("**/*.json")
    def all_jsons_everywhere(event):
        print("watch **/*.json:", event)

    print("Running rpc server for", box.app_rpc_dir)
    box.publish_schema()
    box.run_forever()


# if __name__ == "__main__":
#     box = SyftEvents("vector_store")

#     # requests are always bound to the app
#     # root path = {datasite}/app_data/{app_name}/rpc
#     @box.on_request("/doc_query")
#     def query(query: str) -> list[str]:
#         """Return similar documents for a given query"""
#         return []

#     @box.on_request("/doc_similarity")
#     def query_embedding(embedding: np.array) -> np.array:
#         """Return similar documents for a given embedding"""
#         return []

#     print("Running rpc server for", box.app_rpc_dir)
#     box.publish_schema()
#     box.run_forever()
