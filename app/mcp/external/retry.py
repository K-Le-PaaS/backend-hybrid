from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Iterable

from .errors import MCPExternalError


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, MCPExternalError):
        return exc.code in {"rate_limited", "timeout", "unavailable", "internal"}
    return False


async def retry_async(
    op: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 5,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    jitter: float = 0.2,
) -> Any:
    """Exponential backoff with jitter for retryable errors.

    - attempts includes the first try
    - jitter is a fraction of delay (+/-)
    """
    attempt = 0
    while True:
        try:
            return await op()
        except BaseException as exc:  # noqa: BLE001 - deliberate to centralize policy
            attempt += 1
            if attempt >= attempts or not _is_retryable(exc):
                raise

            # Compute delay
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if jitter:
                delta = delay * jitter
                delay = max(0.0, delay + random.uniform(-delta, delta))

            # Honor server-provided retry-after if available
            if isinstance(exc, MCPExternalError) and exc.retry_after_seconds:
                delay = max(delay, float(exc.retry_after_seconds))

            await asyncio.sleep(delay)


