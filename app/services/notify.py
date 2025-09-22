from __future__ import annotations

from typing import Any, Dict

import httpx
from jinja2 import Environment, StrictUndefined

from ..core.config import get_settings
from .slack_notification_service import get_slack_notification_service
from .slack_client import get_slack_client
from ..models.slack_events import SlackEventType


async def slack_notify(
    text: str | None = None,
    *,
    channel: str | None = None,
    template: str | None = None,
    context: Dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """기존 호환성을 위한 Slack 알림 함수 (레거시)"""
    settings = get_settings()
    if not settings.slack_webhook_url:
        return {"status": "skipped", "reason": "no slack webhook configured"}
    
    try:
        # 새로운 알림 서비스 사용
        notification_service = get_slack_notification_service()
        
        # 템플릿 렌더링
        if template:
            env = Environment(undefined=StrictUndefined, autoescape=False)
            text = env.from_string(template).render(**(context or {}))
        
        # 기본 알림으로 전송
        response = await notification_service.send_custom_notification(
            event_type=SlackEventType.API_ERROR,  # 기본 이벤트 타입
            title="알림",
            message=text or "",
            context=context or {},
            channel=channel
        )
        
        return {
            "status": 200 if response.success else 500,
            "message_ts": response.message_ts,
            "error": response.error
        }
        
    except Exception as e:
        # 폴백: 기존 방식 사용
        return await _legacy_slack_notify(text, channel, template, context, blocks)


async def _legacy_slack_notify(
    text: str | None = None,
    *,
    channel: str | None = None,
    template: str | None = None,
    context: Dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """레거시 Slack 알림 함수"""
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


