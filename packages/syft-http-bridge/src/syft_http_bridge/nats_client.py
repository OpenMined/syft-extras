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

import nats
from loguru import logger
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.js.client import JetStreamContext


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
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

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

    def _hash_subject(self, subject: str) -> str:
        return hashlib.blake2s(subject.encode(), digest_size=8).hexdigest()

    def make_default_durable_name(self, subject: str) -> str:
        """
        NATS needs a durable name for pull subscriptions,
        in order to keep track of messages received and acknowledged.
        """
        return f"default-{self._hash_subject(subject)}"

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

    def is_message_expired(self, msg: Msg) -> bool:
        expires_at = msg.headers.get("expires_at")
        if expires_at:
            expires_at = datetime.fromisoformat(expires_at)
            return _utcnow() > expires_at
        return False

    async def wait_for_message(
        self,
        subject: str,
        timeout: float = 10.0,
        ack: bool = True,
        exclude_expired: bool = True,
    ) -> Optional[bytes]:
        await self.connect()

        try:
            durable = self.make_default_durable_name(subject)
            sub = await self.js.pull_subscribe(subject, durable=durable)
            msgs = await sub.fetch(1, timeout=timeout)

            if msgs:
                msg = msgs[0]
                data = msg.data
                if ack:
                    await msg.ack()
                if exclude_expired and self.is_message_expired(msg):
                    return None
                return data
            return None
        except nats.errors.TimeoutError:
            return None

    async def close(self) -> None:
        if self.nc:
            await self.nc.close()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


class NatsRPCClient(NatsClient):
    def __init__(
        self,
        requester: str,
        responder: str,
        app_name: str,
        nats_url: str = "nats://localhost:4222",
    ):
        super().__init__(nats_url)
        self.requester: str = requester
        self.responder: str = responder
        self.app_name: str = app_name

    async def send_request(
        self,
        payload: bytes,
        timeout: Optional[float] = None,
    ) -> str:
        """Send a request and return the request ID"""
        await self.connect()
        request_id = str(uuid.uuid4())
        subject = make_request_subject(self.requester, self.responder, self.app_name)
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
        request_id: str,
        timeout: float = 10.0,
    ) -> Optional[bytes]:
        """Wait for a response to a specific request"""
        await self.connect()
        subject = make_response_subject(
            self.requester, self.responder, self.app_name, request_id
        )
        logger.debug(
            f"{self.requester} waiting for response with request_id {request_id}"
        )
        return await self.wait_for_message(subject, timeout=timeout)


class NatsRPCServer(NatsClient):
    def __init__(
        self,
        responder: str,
        app_name: str,
        # event_handler: Union[Callable[[Msg], bytes], Callable[[Msg], Awaitable[bytes]]],
        nats_url: str = "nats://localhost:4222",
    ):
        super().__init__(nats_url)
        self.responder: str = responder
        self.app_name: str = app_name
        # self.event_handler: Union[
        #     Callable[[Msg], bytes], Callable[[Msg], Awaitable[bytes]]
        # ] = event_handler

    # async def _event_handler(self, msg: Msg) -> None:
    #     logger.debug("Received message")
    #     try:
    #         await msg.ack()
    #         # Extract important information
    #         request_id = msg.headers.get("request_id") if msg.headers else None
    #         if not request_id:
    #             logger.error("Received request without request_id header")
    #             return

    #         if self.is_message_expired(msg):
    #             logger.warning(f"Received expired request {request_id}")
    #             return

    #         # Parse the subject to get the requester
    #         parts = msg.subject.split(".")
    #         if len(parts) >= 3:  # requests.<requester>.<receiver>.<app_name>
    #             requester = nats_subject_to_email(parts[1])
    #         else:
    #             logger.error(f"Invalid subject format: {msg.subject}")
    #             return

    #         # Call the user-provided handler
    #         if asyncio.iscoroutinefunction(self.event_handler):
    #             response_payload = await self.event_handler(msg)
    #         else:
    #             response_payload = self.event_handler(msg)

    #         # Send the response if the handler returned something
    #         if response_payload is not None:
    #             await self.send_response(requester, request_id, response_payload)

    #     except Exception as e:
    #         logger.exception(f"Error handling request: {e}")

    async def send_response(
        self,
        requester: str,
        request_id: str,
        payload: bytes,
        timeout: Optional[float] = None,
    ) -> None:
        await self.connect()
        subject = make_response_subject(
            requester, self.responder, self.app_name, request_id
        )
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

    # async def start(self) -> None:
    #     await self.connect()

    #     subj = make_request_subject("*", self.responder, self.app_name)
    #     logger.debug(f"Subscribing to {subj}")
    #     await self.subscribe_with_callback(subj, self._event_handler)

    # async def run_forever(self) -> None:
    #     stop_event = asyncio.Event()

    #     def signal_handler() -> None:
    #         logger.info("Shutdown signal received, stopping server...")
    #         stop_event.set()

    #     for sig in (signal.SIGINT, signal.SIGTERM):
    #         asyncio.get_event_loop().add_signal_handler(sig, signal_handler)

    #     await stop_event.wait()
    #     logger.info("Shutting down server...")
    #     await self.close()
    #     logger.info("Server shutdown complete")
