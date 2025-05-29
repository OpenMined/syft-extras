from __future__ import annotations

import inspect
import json
from dataclasses import is_dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel
from syft_rpc.protocol import SyftRequest
from typing_extensions import Any, Callable, Dict, Type, get_type_hints

from syft_event.types import Request

if TYPE_CHECKING:
    from syft_event.server2 import SyftEvents


def func_args_from_request(
    func: Callable, request: SyftRequest, app: SyftEvents
) -> Dict[str, Any]:
    """Extract dependencies based on function type hints"""

    type_hints = get_type_hints(func)
    sig = inspect.signature(func)
    kwargs = {}

    for pname, _ in sig.parameters.items():
        ptype = type_hints.get(pname, Any)
        kwargs[pname] = _resolve_parameter(pname, ptype, request, app)

    return kwargs


def _resolve_parameter(
    pname: str, ptype: Type, request: SyftRequest, app: SyftEvents
) -> Any:
    """Resolve a parameter value based on its type"""
    from syft_event.server2 import SyftEvents

    if inspect.isclass(ptype) and ptype is Request:
        return Request(
            id=str(request.id),
            sender=request.sender,
            url=request.url,
            headers=request.headers,
            body=request.body,
            method=request.method,
        )

    elif inspect.isclass(ptype) and ptype is SyftEvents:
        return app
    elif is_dataclass(ptype):
        return ptype(**request.json())
    elif inspect.isclass(ptype) and issubclass(ptype, BaseModel):
        return request.model(ptype)
    elif ptype is dict:
        val = json.loads(request.body.decode()) if request.body else None
        return val
    elif ptype is str:
        return request.text()
    else:
        raise ValueError(f"Unknown type {ptype} for parameter {pname}")
