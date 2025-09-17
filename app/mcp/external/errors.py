from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


# Normalized error codes for external MCP interactions
ErrorCode = Literal[
    "unauthorized",
    "forbidden",
    "not_found",
    "rate_limited",
    "timeout",
    "unavailable",
    "bad_request",
    "conflict",
    "internal",
]


@dataclass(slots=True)
class MCPExternalError(Exception):
    code: ErrorCode
    message: str
    retry_after_seconds: float | None = None
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retry_after_seconds": self.retry_after_seconds,
            "details": dict(self.details or {}),
        }


