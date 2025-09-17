from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...services.deployments import DeployApplicationInput, perform_deploy, perform_rollback


router = APIRouter()


class RollbackRequest(BaseModel):
    app_name: str = Field(min_length=1)
    environment: Environment


@router.post("/deploy", response_model=dict)
async def deploy_application(body: DeployApplicationInput) -> Dict[str, Any]:
    return perform_deploy(body)


@router.post("/deployments/rollback", response_model=dict)
async def rollback(body: RollbackRequest) -> Dict[str, Any]:
    return perform_rollback(app_name=body.app_name, environment=body.environment)


