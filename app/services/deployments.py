from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator
from .history import record_deploy, get_history


class Environment(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class DeployApplicationInput(BaseModel):
    app_name: str = Field(min_length=1)
    environment: Environment
    image: str = Field(min_length=3, description="OCI image reference, e.g., repo/app:tag")
    replicas: int = Field(default=2, ge=1, le=50)

    @field_validator("app_name")
    @classmethod
    def validate_app_name(cls, v: str) -> str:
        if " " in v:
            raise ValueError("app_name must not contain spaces")
        return v


def perform_deploy(payload: DeployApplicationInput) -> Dict[str, Any]:
    """Stub deployment implementation.

    In Phase 1, we only validate and echo a plan. Later phases will
    integrate with k8s/agents and CI/CD.
    """
    plan = {
        "action": "deploy",
        "app_name": payload.app_name,
        "environment": payload.environment.value,
        "image": payload.image,
        "replicas": payload.replicas,
        "status": "planned",
    }
    # record into in-memory history (Phase 1)
    record_deploy(
        app_name=payload.app_name,
        environment=payload.environment.value,
        image=payload.image,
        replicas=payload.replicas,
    )
    plan["history"] = get_history(payload.app_name, payload.environment.value)
    return plan


def perform_rollback(app_name: str, environment: str) -> Dict[str, Any]:
    from .history import get_previous

    prev = get_previous(app_name, environment)
    if not prev:
        return {"status": "skipped", "reason": "no previous version"}
    # Re-deploy previous image/replicas (still Phase 1: return plan)
    payload = DeployApplicationInput(
        app_name=app_name,
        environment=Environment(environment),
        image=prev.image,
        replicas=prev.replicas,
    )
    result = perform_deploy(payload)
    return {"status": "rolled_back", "to": {"image": prev.image, "replicas": prev.replicas}, "result": result}


