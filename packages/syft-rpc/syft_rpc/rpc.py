from __future__ import annotations

import json
import warnings
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from syft_core.client_shim import Client
from syft_core.url import SyftBoxURL
from syft_crypto import encrypt_message
from syft_crypto.x3dh_bootstrap import ensure_bootstrap
from typing_extensions import Any, Dict, List, Optional, Union

from syft_rpc.protocol import (
    SyftBulkFuture,
    SyftError,
    SyftFuture,
    SyftMethod,
    SyftRequest,
    SyftResponse,
    SyftStatus,
)
from syft_rpc.util import parse_duration

DEFAULT_EXPIRY = "15m"

BodyType = Union[str, bytes, dict, list, tuple, float, int, BaseModel, None]
HeaderType = Optional[Dict[str, str]]


class EncryptionParams(BaseModel):
    """Parameters for message encryption in RPC calls."""

    encrypt: bool = False
    recipient: Optional[str] = None
    client: Optional[Client] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)  # Allow Client type

    def validate_for_encryption(self) -> None:
        """Validate parameters are sufficient for encryption."""
        if self.encrypt and not self.recipient:
            raise ValueError("recipient required for encryption")


class GenericModel(BaseModel):
    model_config = ConfigDict(extra="allow")


def make_url(datasite: str, app_name: str, endpoint: str) -> SyftBoxURL:
    """Create a Syft Box URL from a datasite, app name, and RPC endpoint."""

    return SyftBoxURL(
        f"syft://{datasite}/app_data/{app_name}/rpc/" + endpoint.lstrip("/")
    )


def serialize(obj: Any, **kwargs: Any) -> Optional[bytes]:
    """Serialize an object to bytes for sending over the network.

    Args:
        obj: The object to serialize
        **kwargs: Additional serialization options including:
            encrypt (bool): Whether to encrypt the serialized data
            recipient (str): Email address of the encryption recipient (required if encrypt=True)
            client (Client): Syft client for encryption (auto-loaded if not provided)
            Other kwargs are passed to the underlying serialization methods

    Returns:
        Serialized (and optionally encrypted) bytes, or None if obj is None

    Raises:
        ValueError: If encrypt=True but recipient is not provided
    """

    if obj is None:
        return None

    # Extract and validate encryption parameters
    enc_params = EncryptionParams(
        encrypt=kwargs.pop("encrypt", False),
        recipient=kwargs.pop("recipient", None),
        client=kwargs.pop("client", None),
    )
    enc_params.validate_for_encryption()

    # Standard serialization
    if isinstance(obj, bytes):
        data = obj
    elif isinstance(obj, str):
        data = obj.encode()
    elif isinstance(obj, BaseModel):
        data = obj.model_dump_json(**kwargs).encode()
    elif is_dataclass(obj) and not isinstance(obj, type):
        data = GenericModel(**asdict(obj)).model_dump_json(**kwargs).encode()
    elif isinstance(obj, dict):
        data = GenericModel(**obj).model_dump_json(**kwargs).encode()
    else:
        # list, tuple, float, int
        data = json.dumps(obj).encode()

    # Apply encryption if requested
    if enc_params.encrypt:
        if not enc_params.client:
            enc_params.client = Client.load()

        # Ensure client has encryption keys
        enc_params.client = ensure_bootstrap(enc_params.client)

        encrypted_payload = encrypt_message(
            message=data.decode(),
            to=enc_params.recipient,
            client=enc_params.client,
            verbose=True,
        )
        return encrypted_payload.model_dump_json().encode()

    return data


def send(
    url: Union[SyftBoxURL, str],
    method: Union[SyftMethod, str] = SyftMethod.GET,
    body: Optional[BodyType] = None,
    headers: Optional[HeaderType] = None,
    expiry: str = DEFAULT_EXPIRY,
    cache: Optional[bool] = None,
    client: Optional[Client] = None,
    encrypt: bool = False,
) -> SyftFuture:
    """Send an asynchronous request to a SyftBox endpoint and return a future for tracking the response.

    This function creates a SyftRequest, writes it to the local filesystem under the client's workspace,
    and returns a SyftFuture object that can be used to track and retrieve the response.

    Args:
        method: The HTTP method to use. Can be a SyftMethod enum or a string
            (e.g., 'GET', 'POST').
        url: The destination URL. Can be a SyftBoxURL instance or a string in the
            format 'syft://user@domain.com/path'.
        headers: Optional dictionary of HTTP headers to include with the request.
            Defaults to None.
        body: Optional request body. Can be either a string (will be encoded to bytes)
            or raw bytes. Defaults to None.
        client: A Syft Client instance used to send the request. If not provided,
            the default client will be loaded.
        expiry: Duration string specifying how long the request is valid for.
            Defaults to DEFAULT_EXPIRY.
        cache: Optional[bool]. If True, cache the request for reuse. If None,
            defaults to False when encrypt=True, True otherwise.
            NOTE: Caching encrypted requests is ineffective as each encryption
            uses different ephemeral keys, creating unique cache entries.
        encrypt: If True, encrypt the request body using X3DH protocol.
            Recipient is automatically extracted from the URL.

    Returns:
        SyftFuture: A future object that can be used to track and retrieve the response.

    Examples:
        Basic request:
        >>> future = send(
        ...     url="syft://data@domain.com/dataset1",
        ...     expiry="30s"
        ... )
        >>> response = future.result()  # Wait for response

        Encrypted request:
        >>> future = send(
        ...     url="syft://user@domain.com/app_data/myapp/rpc/compute",
        ...     body={"data": "sensitive"},
        ...     encrypt=True
        ... )

        Cached request (not recommended with encryption):
        >>> future = send(
        ...     url="syft://user@domain.com/app_data/myapp/rpc/public",
        ...     body={"query": "status"},
        ...     cache=True
        ... )

    Warning:
        Using cache=True with encrypt=True is ineffective. Each encrypted request
        uses different ephemeral keys, preventing cache hits and creating multiple
        cache entries for identical requests.
    """

    # If client is not provided, load the default client
    client = Client.load() if client is None else client

    # Smart cache defaults: disable caching for encrypted requests unless explicitly enabled
    if cache is None:
        cache = not encrypt  # Default to False when encrypting, True otherwise

    # Warn when caching encrypted requests
    if cache and encrypt:
        warnings.warn(
            "Caching encrypted requests is ineffective due to ephemeral keys. "
            "Each encrypted request will generate a unique cache entry. "
            "Consider cache=False for encrypted requests.",
            UserWarning,
            stacklevel=2,
        )

    method = SyftMethod(method) if isinstance(method, str) else method

    url_obj = url if isinstance(url, SyftBoxURL) else SyftBoxURL(url)
    recipient = url_obj.host

    if encrypt:
        serialized_body = serialize(
            body, encrypt=True, recipient=recipient, client=client
        )
    else:
        serialized_body = serialize(body)

    syft_request = SyftRequest(
        sender=client.email,
        method=method,
        url=url_obj,
        headers=headers or {},
        body=serialized_body,
        expires=datetime.now(timezone.utc) + parse_duration(expiry),
    )
    local_path = syft_request.url.to_local_path(client.workspace.datasites)
    local_path.mkdir(parents=True, exist_ok=True)

    # caching is enabled, generate a new request
    if cache:
        # generate a predictable id from message components
        id = syft_request.get_message_id()
        syft_request.id = id

    req_path = local_path / f"{syft_request.id}.request"

    # Handle cached request scenario
    if cache and req_path.exists():
        cached_request = SyftRequest.load(req_path)
        if cached_request.is_expired:
            print(f"Cached request expired, removing: {req_path}")
            req_path.unlink()
        else:
            return SyftFuture(
                id=cached_request.id,
                path=local_path,
                expires=cached_request.expires,
                request=cached_request,
            )

    # Create new request file if needed
    if not req_path.exists():
        try:
            syft_request.dump(req_path)
        except OSError as e:
            raise SyftError(f"Request persistence failed: {req_path} - {e}")

    return SyftFuture(
        id=syft_request.id,
        path=local_path,
        expires=syft_request.expires,
        request=syft_request,
    )


def broadcast(
    urls: Union[List[SyftBoxURL], List[str]],
    body: Optional[BodyType] = None,
    headers: Optional[HeaderType] = None,
    expiry: str = DEFAULT_EXPIRY,
    cache: Optional[bool] = None,
    client: Optional[Client] = None,
    encrypt: bool = False,
) -> SyftBulkFuture:
    """Broadcast an asynchronous request to multiple Syft Box endpoints and return a bulk future.

    This function creates a SyftRequest for each URL in the list,
    writes them to the local filesystem under the client's workspace, and
    returns a SyftBulkFuture object that can be used to track and retrieve multiple responses.

    Args:
        method: The HTTP method to use. Can be a SyftMethod enum or a string
            (e.g., 'GET', 'POST').
        urls: List of destination URLs. Each can be a SyftBoxURL instance or a string in
            the format 'syft://user@domain.com/path'.
        headers: Optional dictionary of HTTP headers to include with the requests.
            Defaults to None.
        body: Optional request body. Can be either a string (will be encoded to bytes)
            or raw bytes. Defaults to None.
        client: A Syft Client instance used to send the requests. If not provided,
            the default client will be loaded.
        expiry: Duration string specifying how long the request is valid for.
            Defaults to '24h' (24 hours).
        cache: If True, cache the request on the local filesystem for future use.

    Returns:
        SyftBulkFuture: A bulk future object that can be used to track and retrieve multiple responses.

    Example:
        >>> future = broadcast(
        ...     urls=["syft://user1@domain.com/app_data/app_name/rpc/endpoint",
        ...           "syft://user2@domain.com/app_data/app_name/rpc/endpoint"],
        ...     expiry="1d",
        ... )
        >>> responses = future.gather_completed()  # Wait for all responses
    """

    # If client is not provided, load the default client
    client = Client.load() if client is None else client

    bulk_future = SyftBulkFuture(
        futures=[
            send(
                url=url,
                headers=headers,
                body=body,
                client=client,
                expiry=expiry,
                cache=cache,
                encrypt=encrypt,
            )
            for url in urls
        ]
    )
    return bulk_future


def reply_to(
    request: SyftRequest,
    body: Optional[BodyType] = None,
    headers: Optional[HeaderType] = None,
    status_code: SyftStatus = SyftStatus.SYFT_200_OK,
    client: Optional[Client] = None,
    encrypt: bool = False,
) -> SyftResponse:
    """Create and store a response to a Syft request.

    This function creates a SyftResponse object corresponding to a given SyftRequest,
    writes it to the local filesystem in the client's workspace, and returns the response object.

    Args:
        request: The original SyftRequest to respond to.
        client: A Syft Client instance used to send the response.
        body: Optional response body. Can be either a string (will be encoded to bytes)
            or raw bytes. Defaults to None.
        headers: Optional dictionary of HTTP headers to include with the response.
            Defaults to None.
        client: A Syft Client instance used to send the response. If not provided,
            the default client will be loaded.
        status_code: HTTP status code for the response. Should be a SyftStatus enum value.
            Defaults to SyftStatus.SYFT_200_OK.
        encrypt: If True, encrypt the response body using X3DH protocol.
            Recipient is automatically extracted from the request sender.

    Returns:
        SyftResponse: The created response object containing all response details.

    Example:
        >>> # Assuming we have a request
        >>> response = reply_to(
        ...     request=incoming_request,
        ...     body="Request processed successfully",
        ...     status_code=SyftStatus.SYFT_200_OK
        ... )

        Encrypted response:
        >>> response = reply_to(
        ...     request=incoming_request,
        ...     body={"sensitive": "data"},
        ...     encrypt=True
        ... )
    """

    # If client is not provided, load the default client
    client = Client.load() if client is None else client

    # Handle encryption of response body
    if encrypt:
        recipient = request.sender  # Reply to the original request sender
        serialized_body = serialize(
            body, encrypt=True, recipient=recipient, client=client
        )
    else:
        serialized_body = serialize(body)

    response = SyftResponse(
        id=request.id,
        sender=client.email,
        url=request.url,
        headers=headers or {},
        body=serialized_body,
        expires=request.expires,
        status_code=status_code,
    )

    local_path = response.url.to_local_path(client.workspace.datasites)
    file_path = local_path / f"{response.id}.response"
    local_path.mkdir(parents=True, exist_ok=True)
    response.dump(file_path)

    return response


def write_response(
    request_path: Union[Path, str],
    body: Optional[BodyType] = None,
    headers: Optional[HeaderType] = None,
    status_code: SyftStatus = SyftStatus.SYFT_200_OK,
    client: Optional[Client] = None,
):
    """Write a response to a request file on the local filesystem.
    Useful when request could not be parsed."""

    request_path = Path(request_path)

    client = client or Client.load()

    _id = request_path.stem
    response = SyftResponse(
        id=UUID(_id),
        sender=client.email,
        url=client.to_syft_url(request_path.parent),
        headers=headers or {},
        body=serialize(body),
        status_code=status_code,
    )
    response.dump(request_path.with_suffix(".response"))
