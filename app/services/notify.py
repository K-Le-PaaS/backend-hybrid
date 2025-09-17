from __future__ import annotations

from typing import Any, Dict

import httpx

from ..core.config import get_settings


async def slack_notify(text: str, blocks: list[dict[str, Any]] | None = None) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.slack_webhook_url:
        return {"status": "skipped", "reason": "no slack webhook configured"}
    payload: Dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(settings.slack_webhook_url, json=payload)
        return {"status": resp.status_code}


