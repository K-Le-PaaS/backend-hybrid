from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class SupportsClose(Protocol):
    def close(self) -> None: ...


class ExternalMCPClient(ABC):
    """Common interface for external MCP server connectors.

    Minimal, transport-agnostic surface to standardize connect → call → close.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish underlying connection/session.

        Implementations must be idempotent and safe to call multiple times.
        """

    @abstractmethod
    async def list_tools(self) -> list[dict[str, Any]]:
        """Return server tools metadata in a normalized structure."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke a tool by name with structured arguments.

        Implementations should translate provider-specific responses to a
        normalized dict containing at minimum: {"ok": bool, "content": Any}.
        """

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Lightweight health probe for readiness/liveness checks."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources and close connections if applicable."""



