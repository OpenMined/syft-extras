import asyncio
import hashlib
import signal
import uuid
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Optional,
    Self,
    Tuple,
    Union,
)

import httpx
import nats
from httpx import AsyncBaseTransport, Request, Response
from loguru import logger
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js.client import JetStreamContext

from syft_http_bridge.serde import deserialize_response, serialize_request


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def email_to_nats_subject(email: str) -> str:
    """Replace all reserved characters in an email address with safe alternatives"""
    return email.replace(".", ":").replace(" ", "-").replace("*", "+").replace(">", "}")


def nats_subject_to_email(segment: str) -> str:
    return (
        segment.replace(":", ".").replace("-", " ").replace("+", "*").replace("}", ">")
    )


def _is_wildcard(segment: str) -> bool:
    return segment == "*" or segment == ">"


def make_request_subject(requester: str, responder: str, app_name: str) -> str:
    if not _is_wildcard(requester):
        requester = email_to_nats_subject(requester)
    if not _is_wildcard(responder):
        responder = email_to_nats_subject(responder)
    return f"requests.{requester}.{responder}.{app_name}"


def parse_subject(subject: str) -> Tuple[str, ...]:
    split = subject.split(".")
    for i, s in enumerate(split):
        if not _is_wildcard(s):
            split[i] = nats_subject_to_email(s)
    return tuple(split)


def make_response_subject(
    requester: str, responder: str, app_name: str, request_id: Union[str, uuid.UUID]
) -> str:
    requester = email_to_nats_subject(requester)
    responder = email_to_nats_subject(responder)
    return f"responses.{requester}.{responder}.{app_name}.{request_id}"


class NatsClient:
    MAX_PAYLOAD_SIZE = 1024 * 1024 * 8  # 8 MB, recommended limit

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url: str = nats_url
        self.nc: Optional[Client] = None
        self.js: Optional[JetStreamContext] = None

    async def connect(self) -> None:
        if not self.nc or self.nc.is_closed:
            del self.nc
            del self.js

            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            try:
                # Set up persistent streams for requests and responses
                await self.js.add_stream(name="requests", subjects=["requests.>"])
                await self.js.add_stream(name="responses", subjects=["responses.>"])
            except Exception:
                # Stream already exists
                pass

    def is_message_expired(self, msg: Msg) -> bool:
        expires_at = msg.headers.get("expires_at")
        if expires_at:
            expires_at = datetime.fromisoformat(expires_at)
            return _utcnow() > expires_at
        return False

    async def publish(
        self,
        subject: str,
        payload: bytes,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> None:
        if len(payload) > self.MAX_PAYLOAD_SIZE:
            raise ValueError(
                f"Payload size exceeds maximum of {self.MAX_PAYLOAD_SIZE} bytes"
            )

        if headers is None:
            headers = {}

        if timeout:
            headers["expires_at"] = (_utcnow() + timedelta(seconds=timeout)).isoformat()

        await self.connect()
        await self.js.publish(
            subject,
            payload,
            headers=headers,
        )

    def make_default_durable_name(self, subject: str) -> str:
        """
        NATS needs a durable name for pull subscriptions
        in order to keep track of messages received and acknowledged.

        use 16byte blake2, which is unique and deterministic
        """
        return hashlib.blake2b(subject.encode(), digest_size=16).hexdigest()

    async def subscribe_with_callback(
        self, subject: str, callback: Callable[[Msg], Any]
    ) -> None:
        await self.connect()
        durable = self.make_default_durable_name(subject)
        await self.js.subscribe(subject, cb=callback, durable=durable)

    async def subscribe_iter(self, subject: str) -> AsyncIterator[Msg]:
        await self.connect()
        durable = self.make_default_durable_name(subject)
        async for msg in self.js.subscribe(subject, durable=durable):
            yield msg

    async def wait_for_message(
        self,
        subject: str,
        timeout: float = 10.0,
        ack: bool = True,
        exclude_expired: bool = True,
    ) -> Optional[bytes]:
        await self.connect()

        durable = self.make_default_durable_name(subject)
        sub = await self.js.pull_subscribe(subject, durable=durable)
        msgs = await sub.fetch(1, timeout=timeout)

        if msgs:
            msg = msgs[0]
            data = msg.data
            if ack:
                await msg.ack()
            if exclude_expired and self.is_message_expired(msg):
                raise ValueError(f"Message with subject {subject} has expired")
            return data
        raise ValueError(f"Message with subject {subject} not found or timed out")

    async def close(self) -> None:
        if self.nc:
            await self.nc.close()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


class SyftNatsClient(NatsClient):
    async def send_request(
        self,
        requester: str,
        responder: str,
        app_name: str,
        payload: bytes,
        timeout: Optional[float] = None,
    ) -> str:
        """Send a request and return the request ID"""
        await self.connect()
        request_id = str(uuid.uuid4())
        subject = make_request_subject(requester, responder, app_name)
        headers = {
            "request_id": request_id,
        }

        logger.debug(f"Sending request to {subject} with ID {request_id}")
        await self.publish(
            subject,
            payload,
            headers=headers,
            timeout=timeout,
        )
        return request_id

    async def wait_for_response(
        self,
        requester: str,
        responder: str,
        app_name: str,
        request_id: str,
        timeout: float = 10.0,
    ) -> Optional[bytes]:
        """Wait for a response to a specific request"""
        await self.connect()
        subject = make_response_subject(requester, responder, app_name, request_id)
        logger.debug(f"{requester} waiting for response with request_id {request_id}")
        return await self.wait_for_message(subject, timeout=timeout)

    async def send_response(
        self,
        requester: str,
        responder: str,
        app_name: str,
        request_id: str | uuid.UUID,
        payload: bytes,
        timeout: Optional[float] = None,
    ) -> None:
        await self.connect()

        request_id = str(request_id)
        subject = make_response_subject(requester, responder, app_name, request_id)
        headers = {
            "request_id": request_id,
        }
        logger.debug(f"Sending response to {subject} with ID {request_id}")
        await self.publish(
            subject,
            payload,
            headers=headers,
            timeout=timeout,
        )

    async def subscribe_to_app(
        self,
        responder: str,
        app_name: str,
        callback: Callable[[Msg], Awaitable[None]],
    ) -> None:
        subject = make_request_subject("*", responder, app_name)
        await self.subscribe_with_callback(subject, callback)


class NatsTransport(AsyncBaseTransport):
    def __init__(
        self,
        requester: str,
        responder: str,
        app_name: str,
        nats_url: str = "nats://localhost:4222",
    ):
        self.requester = requester
        self.responder = responder
        self.app_name = app_name
        self.nats_client = SyftNatsClient(nats_url=nats_url)

    async def handle_async_request(self, request: Request) -> Response:
        print("Handling async request")
        request_id = await self.nats_client.send_request(
            requester=self.requester,
            responder=self.responder,
            app_name=self.app_name,
            payload=serialize_request(request),
        )

        response = await self.nats_client.wait_for_response(
            requester=self.requester,
            responder=self.responder,
            app_name=self.app_name,
            request_id=request_id,
            timeout=3,
        )
        response = deserialize_response(response)
        return response

    def handle_request(self, request: Request) -> Response:
        print("Handling sync request")
        is_asyncio_event_loop_running = False
        try:
            is_asyncio_event_loop_running = asyncio.get_event_loop().is_running()
        except RuntimeError:
            pass
        if is_asyncio_event_loop_running:
            future = asyncio.ensure_future(self.handle_async_request(request))
            import time

            time_waited = 0
            while not future.done():
                time_waited += 0.1
                time.sleep(0.1)
                if time_waited > 3:
                    raise TimeoutError("Request timed out")

            response = future.result()
        else:
            response = asyncio.run(self.handle_async_request(request))
        return response

    async def __aenter__(self) -> Self:
        await self.nats_client.connect()
        return self

    async def aclose(self) -> None:
        await self.nats_client.close()


def create_nats_httpx_client(
    requester: str,
    responder: str,
    app_name: str,
    nats_url: str = "nats://localhost:4222",
    **client_kwargs: Any,
) -> httpx.AsyncClient:
    transport = NatsTransport(
        requester,
        responder,
        app_name,
        nats_url=nats_url,
    )

    return httpx.Client(
        transport=transport,
        base_url="http://syft",
        **client_kwargs,
    )
