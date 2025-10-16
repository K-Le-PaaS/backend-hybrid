"""
사용자별 Slack 연동 설정 모델

OAuth 또는 Webhook 기반의 Slack 설정을 사용자 단위로 저장합니다.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean

from .base import Base


class UserSlackConfig(Base):
    """사용자별 Slack 설정 테이블"""

    __tablename__ = "user_slack_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)

    # integration type: "oauth" | "webhook"
    integration_type = Column(String(20), nullable=False, default="oauth")

    # OAuth: Bot Access Token (xoxb-)
    access_token = Column(Text, nullable=True)

    # Webhook: Incoming Webhook URL
    webhook_url = Column(Text, nullable=True)

    # Channels
    default_channel = Column(String(255), nullable=True)
    deployment_channel = Column(String(255), nullable=True)
    error_channel = Column(String(255), nullable=True)

    # Personal DM preferences
    dm_enabled = Column(Boolean, nullable=False, default=True)
    dm_user_id = Column(String(255), nullable=True)  # Slack user id for DM (e.g., U123...)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 헬퍼
        return (
            f"<UserSlackConfig(user_id={self.user_id}, type={self.integration_type}, "
            f"default_channel={self.default_channel})>"
        )


