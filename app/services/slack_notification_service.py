"""
DEPRECATED: 이 모듈은 더 이상 사용되지 않습니다.
대신 app.services.notification 모듈을 사용하세요.

이전 호환성을 위해 import redirect를 제공합니다.
"""

import warnings
from .notification import (
    SlackNotificationService,
    get_slack_notification_service,
    init_slack_notification_service,
    NotificationPriority,
)

# 경고 메시지 출력
warnings.warn(
    "slack_notification_service 모듈은 deprecated 되었습니다. "
    "대신 'from app.services.notification import SlackNotificationService'를 사용하세요.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    "SlackNotificationService",
    "get_slack_notification_service",
    "init_slack_notification_service",
    "NotificationPriority",
]
