"""
CI/CD 설정 서비스 (임시 인메모리 구현)

프로덕션에서는 DB/ConfigMap 등 영속 저장소를 사용하세요.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.cicd_settings import CICDSettingsModel
from ..core.config import get_settings

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # cryptography가 없을 수 있는 테스트 환경 대비
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore


class CicdSettings(BaseModel):
    build_enabled: bool = Field(default=True, description="빌드 단계 실행 여부")
    test_enabled: bool = Field(default=True, description="테스트 단계 실행 여부")
    deploy_enabled: bool = Field(default=True, description="배포 단계 실행 여부")
    env_vars: Dict[str, str] = Field(default_factory=dict)
    secrets: Dict[str, str] = Field(default_factory=dict)


def _get_fernet() -> Optional[Fernet]:  # type: ignore
    settings = get_settings()
    key = getattr(settings, "secrets_encryption_key", None)
    if not key or Fernet is None:
        return None
    try:
        return Fernet(key.encode("utf-8"))  # type: ignore
    except Exception:
        return None


def _encrypt_map(data: Dict[str, str]) -> Dict[str, str]:
    f = _get_fernet()
    if not f:
        return data
    result: Dict[str, str] = {}
    for k, v in (data or {}).items():
        token = f.encrypt(v.encode("utf-8"))  # type: ignore
        result[k] = token.decode("utf-8")
    return result


def _decrypt_map(data: Dict[str, str]) -> Dict[str, str]:
    f = _get_fernet()
    if not f:
        return data
    result: Dict[str, str] = {}
    for k, v in (data or {}).items():
        try:
            plain = f.decrypt(v.encode("utf-8")).decode("utf-8")  # type: ignore
            result[k] = plain
        except InvalidToken:  # type: ignore
            result[k] = v
    return result


def _load(db: Session) -> CicdSettings:
    model = db.get(CICDSettingsModel, "default")
    if not model:
        model = CICDSettingsModel(id="default")
        db.add(model)
        db.commit()
        db.refresh(model)
    return CicdSettings(
        build_enabled=model.build_enabled,
        test_enabled=model.test_enabled,
        deploy_enabled=model.deploy_enabled,
        env_vars=model.env_vars or {},
        secrets=_decrypt_map(model.secrets_encrypted or {}),
    )


def get_cicd_settings() -> CicdSettings:
    db = next(get_db())
    try:
        return _load(db)
    finally:
        db.close()


def set_cicd_settings(new_settings: CicdSettings) -> CicdSettings:
    db = next(get_db())
    try:
        model = db.get(CICDSettingsModel, "default") or CICDSettingsModel(id="default")
        model.build_enabled = new_settings.build_enabled
        model.test_enabled = new_settings.test_enabled
        model.deploy_enabled = new_settings.deploy_enabled
        model.env_vars = new_settings.env_vars
        model.secrets_encrypted = _encrypt_map(new_settings.secrets)
        db.add(model)
        db.commit()
        db.refresh(model)
        return _load(db)
    finally:
        db.close()


def patch_cicd_settings(patch: Dict[str, Any]) -> CicdSettings:
    db = next(get_db())
    try:
        model = db.get(CICDSettingsModel, "default") or CICDSettingsModel(id="default")
        if "build_enabled" in patch and patch["build_enabled"] is not None:
            model.build_enabled = bool(patch["build_enabled"])  # type: ignore
        if "test_enabled" in patch and patch["test_enabled"] is not None:
            model.test_enabled = bool(patch["test_enabled"])  # type: ignore
        if "deploy_enabled" in patch and patch["deploy_enabled"] is not None:
            model.deploy_enabled = bool(patch["deploy_enabled"])  # type: ignore
        if "env_vars" in patch and patch["env_vars"] is not None:
            current = model.env_vars or {}
            current.update(dict(patch["env_vars"]))
            model.env_vars = current
        if "secrets" in patch and patch["secrets"] is not None:
            current_plain = _decrypt_map(model.secrets_encrypted or {})
            current_plain.update(dict(patch["secrets"]))
            model.secrets_encrypted = _encrypt_map(current_plain)
        db.add(model)
        db.commit()
        db.refresh(model)
        return _load(db)
    finally:
        db.close()


