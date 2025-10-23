from __future__ import annotations

from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from ..models.user_slack_config import UserSlackConfig


def get_user_slack_config(db: Session, user_id: str) -> Optional[UserSlackConfig]:
    return (
        db.query(UserSlackConfig)
        .filter(UserSlackConfig.user_id == user_id)
        .order_by(UserSlackConfig.id.desc())
        .first()
    )


def upsert_user_slack_config(
    db: Session,
    *,
    user_id: str,
    integration_type: str,
    access_token: Optional[str] = None,
    webhook_url: Optional[str] = None,
    default_channel: Optional[str] = None,
    deployment_channel: Optional[str] = None,
    error_channel: Optional[str] = None,
    dm_enabled: Optional[bool] = None,
    dm_user_id: Optional[str] = None,
) -> UserSlackConfig:
    cfg = get_user_slack_config(db, user_id)
    if cfg is None:
        cfg = UserSlackConfig(
            user_id=user_id,
            integration_type=integration_type,
        )
        db.add(cfg)

    # 업데이트 필드
    cfg.integration_type = integration_type
    cfg.access_token = access_token
    cfg.webhook_url = webhook_url
    cfg.default_channel = default_channel
    cfg.deployment_channel = deployment_channel
    cfg.error_channel = error_channel
    if dm_enabled is not None:
        cfg.dm_enabled = dm_enabled
    if dm_user_id is not None:
        cfg.dm_user_id = dm_user_id

    db.commit()
    db.refresh(cfg)
    return cfg


def to_public_dict(cfg: UserSlackConfig) -> Dict[str, Any]:
    return {
        "user_id": cfg.user_id,
        "integration_type": cfg.integration_type,
        "default_channel": cfg.default_channel,
        "deployment_channel": cfg.deployment_channel,
        "error_channel": cfg.error_channel,
        # access_token/webhook_url은 민감정보이므로 미노출
    }


