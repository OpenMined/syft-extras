import asyncio
from typing import Awaitable, Callable, Optional, Self, Union
from uuid import UUID

import httpx
from loguru import logger
from nats.aio.msg import Msg
from syft_core import Client as SyftBoxClient

from syft_http_bridge.nats_client import (
    NatsRPCClient,
    make_request_subject,
    nats_subject_to_email,
)
from syft_http_bridge.serde import deserialize_request, serialize_response

DEFAULT_MAX_WORKERS = 10


class EndpointNotAllowed(Exception):
    """Exception raised when an endpoint is not allowed."""


class AsyncHttpProxy:
    """Async version of AsyncHttpProxy that processes HTTP requests asynchronously."""

    def __init__(
        self,
        response_handler: Union[
            Callable[[UUID, bytes, str], None],
            Callable[[UUID, bytes, str], Awaitable[None]],
        ],
        http_client: Union[httpx.AsyncClient, httpx.Client],
        max_workers: int = DEFAULT_MAX_WORKERS,
        allowed_endpoints: Optional[list[str]] = None,
        disallowed_endpoints: Optional[list[str]] = None,
    ):
        self.response_handler = response_handler
        self.http_client = http_client
        self.allowed_endpoints = allowed_endpoints
        self.disallowed_endpoints = disallowed_endpoints

        # Always use semaphore for concurrency control
        self.max_workers = max(1, max_workers)  # Ensure at least 1 worker
        self.semaphore = asyncio.Semaphore(self.max_workers)

    @property
    def is_async_client(self) -> bool:
        return isinstance(self.http_client, httpx.AsyncClient)

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

    async def _send_to_client(self, request: httpx.Request) -> httpx.Response:
        """Send a request using the appropriate client type."""
        if self.is_async_client:
            return await self.http_client.send(request)
        else:
            # For non-async client, run in a thread pool
            return await asyncio.to_thread(self.http_client.send, request)

    async def _call_response_handler(
        self, request_id: UUID, serialized_response: bytes, requester: str
    ) -> None:
        """Call the response handler with proper async/sync handling."""
        try:
            if asyncio.iscoroutinefunction(self.response_handler):
                await self.response_handler(request_id, serialized_response, requester)
            else:
                await asyncio.to_thread(
                    self.response_handler, request_id, serialized_response, requester
                )
        except Exception as e:
            logger.exception(f"Error calling response handler: {str(e)}")

    async def handle_request(
        self, request_id: UUID, serialized_request: bytes, requester: str
    ) -> None:
        """Handle a serialized HTTP request and pass the response to the handler."""
        async with self.semaphore:
            try:
                request = deserialize_request(serialized_request)
                self._validate_request(request)

                forwarded_request = self._prepare_request(request)
                logger.debug(f"Sending request {request_id} to {forwarded_request.url}")
                response = await self._send_to_client(forwarded_request)
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
                    status_code=500,
                    json={"error": str(e), "request_id": str(request_id)},
                )
                serialized_response = serialize_response(error_response)

            await self._call_response_handler(
                request_id, serialized_response, requester
            )

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


class SyftNatsBridge(AsyncHttpProxy):
    """Bridge that connects Syft's filesystem with HTTP requests/responses."""

    def __init__(
        self,
        app_name: str,
        http_client: httpx.Client | httpx.AsyncClient,
        responder: Optional[str] = None,
        syftbox_client: Optional[SyftBoxClient] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        allowed_endpoints: Optional[list[str]] = None,
        disallowed_endpoints: Optional[list[str]] = None,
        nats_url: str = "nats://localhost:4222",
    ):
        self.syftbox_client = syftbox_client or SyftBoxClient.load()
        self.responder = responder or self.syftbox_client.email
        self.app_name = app_name
        self.app_dir = self.syftbox_client.api_data(app_name, datasite=self.responder)

        self.rpc_client = NatsRPCClient(nats_url)

        super().__init__(
            response_handler=self._handle_response,
            http_client=http_client,
            max_workers=max_workers,
            allowed_endpoints=allowed_endpoints,
            disallowed_endpoints=disallowed_endpoints,
        )

    async def _handle_response(
        self,
        request_id: UUID,
        response: bytes,
        requester: str,
    ) -> None:
        await self.rpc_client.send_response(
            requester=requester,
            responder=self.responder,
            app_name=self.app_name,
            request_id=str(request_id),
            payload=response,
        )

    async def _handle_nats_event(self, msg: Msg):
        logger.debug("Received message")
        try:
            await msg.ack()
            # Extract important information
            request_id = msg.headers.get("request_id") if msg.headers else None
            if not request_id:
                logger.error("Received request without request_id header")
                return
            request_id = UUID(request_id)

            if self.rpc_client.is_message_expired(msg):
                logger.warning(f"Received expired request {request_id}")
                return

            # Parse the subject to get the requester
            parts = msg.subject.split(".")
            if len(parts) == 4:  # requests.<requester>.<receiver>.<app_name>
                requester = nats_subject_to_email(parts[1])
            else:
                logger.error(f"Invalid subject format: {msg.subject}")
                return

            await self.handle_request(request_id, msg.data, requester)
        except Exception as e:
            logger.exception(f"Error handling message: {str(e)}")

    async def start(self) -> None:
        subj = make_request_subject("*", self.responder, self.app_name)
        await self.rpc_client.subscribe_with_callback(subj, self._handle_nats_event)

    async def close(self) -> None:
        await self.rpc_client.close()
