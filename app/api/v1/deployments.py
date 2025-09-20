from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...services.deployments_enhanced import (
    DeployApplicationInput,
    perform_deploy,
    perform_rollback,
    Environment,
    get_deploy_status,
    list_recent_versions,
)


router = APIRouter()


class RollbackRequest(BaseModel):
    app_name: str = Field(min_length=1)
    environment: Environment
    target_image: str | None = None


@router.post("/deploy", response_model=dict)
async def deploy_application(body: DeployApplicationInput) -> Dict[str, Any]:
    return perform_deploy(body)


@router.post("/deployments/rollback", response_model=dict)
async def rollback(body: RollbackRequest) -> Dict[str, Any]:
    return perform_rollback(app_name=body.app_name, environment=body.environment, target_image=body.target_image)


@router.get("/deployments/{app_name}/status", response_model=dict)
async def get_status(app_name: str, env: Environment) -> Dict[str, Any]:
    return get_deploy_status(app_name, env.value)


@router.get("/deployments/{app_name}/versions", response_model=dict)
async def get_versions(app_name: str, env: Environment) -> Dict[str, Any]:
    return list_recent_versions(app_name, env.value)

