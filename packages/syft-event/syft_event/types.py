from __future__ import annotations

from pydantic import BaseModel, Field
from syft_core.url import SyftBoxURL
from typing_extensions import Any, Dict, Optional


class Request(BaseModel):
    id: str
    sender: str
    url: SyftBoxURL
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[bytes]
    method: str


class Response(BaseModel):
    body: Any = None
    status_code: int = 200
    headers: Optional[Dict[str, str]] = None
