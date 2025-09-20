from __future__ import annotations

from typing import Any, Dict

import httpx
from jinja2 import Environment, StrictUndefined

from ..core.config import get_settings


async def slack_notify(
    text: str | None = None,
    *,
    channel: str | None = None,
    template: str | None = None,
    context: Dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.slack_webhook_url:
        return {"status": "skipped", "reason": "no slack webhook configured"}
    # Render text from template if provided
    if template:
        env = Environment(undefined=StrictUndefined, autoescape=False)
        text = env.from_string(template).render(**(context or {}))
    payload: Dict[str, Any] = {"text": text or ""}
    if blocks:
        payload["blocks"] = blocks
    if channel or settings.slack_alert_channel_default:
        payload["channel"] = channel or settings.slack_alert_channel_default
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(settings.slack_webhook_url, json=payload)
        return {"status": resp.status_code}


