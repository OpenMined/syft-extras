from typing import Union

import httpx
import ormsgpack
from httpx import Request, Response


def _read_content(obj: Union[Request, Response]) -> bytes:
    """Read content from a request or response object safely."""
    try:
        return obj.content
    except (httpx.RequestNotRead, httpx.ResponseNotRead):
        return obj.read()


def _extract_serializable_extensions(extensions: dict) -> dict:
    """Extract only serializable values from extensions dictionary."""
    return {
        k: v
        for k, v in extensions.items()
        if isinstance(v, (str, int, float, bool, bytes, list, dict)) or v is None
    }


def serialize_request(request: Request) -> bytes:
    """Serialize an httpx.Request object to bytes."""
    content = _read_content(request)

    serializable_data = {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers.items()),
        "content": content,
        "extensions": _extract_serializable_extensions(request.extensions),
    }

    return ormsgpack.packb(serializable_data)


def deserialize_request(data: bytes) -> Request:
    """Deserialize bytes back into an httpx.Request object."""
    unpacked_data = ormsgpack.unpackb(data)

    request = httpx.Request(
        method=unpacked_data["method"],
        url=unpacked_data["url"],
        headers=unpacked_data["headers"],
        content=unpacked_data["content"],
    )

    request.extensions = unpacked_data.get("extensions", {})
    return request


def serialize_response(response: Response) -> bytes:
    """Serialize an httpx.Response object to bytes."""
    content = _read_content(response)

    serializable_data = {
        "status_code": response.status_code,
        "headers": dict(response.headers.items()),
        "content": content,
        "extensions": _extract_serializable_extensions(response.extensions),
    }

    return ormsgpack.packb(serializable_data)


def deserialize_response(data: bytes) -> Response:
    """Deserialize bytes back into an httpx.Response object."""
    unpacked_data = ormsgpack.unpackb(data)

    response = httpx.Response(
        status_code=unpacked_data["status_code"],
        headers=unpacked_data["headers"],
        content=unpacked_data["content"],
    )

    response.extensions = unpacked_data.get("extensions", {})
    return response
