from __future__ import annotations

from typing import Any, Dict

from ..core.config import get_settings
from .notification import get_slack_notification_service
from ..models.slack_events import SlackEventType


async def slack_notify(
    text: str | None = None,
    *,
    channel: str | None = None,
    template: str | None = None,
    context: Dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Slack 알림 함수 - 통합 터미널 스타일 서비스 사용"""
    settings = get_settings()
    if not settings.slack_webhook_url:
        return {"status": "skipped", "reason": "no slack webhook configured"}

    try:
        # 통합 알림 서비스 사용 (터미널 스타일)
        notification_service = get_slack_notification_service()

        # 템플릿 렌더링
        if template:
            from jinja2 import Environment, StrictUndefined
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
        return {"status": "error", "message": str(e)}
