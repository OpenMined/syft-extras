from __future__ import annotations

from typing import Callable


class EventRouter:
    """Router for organizing RPC endpoints in logical groups."""

    def __init__(self):
        self.routes: dict[str, Callable] = {}

    def on_request(self, endpoint: str) -> Callable:
        """Register a function to handle requests at the specified endpoint."""

        def register_rpc(func: Callable) -> Callable:
            self.routes[endpoint] = func
            return func

        return register_rpc
