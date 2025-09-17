from typing import Any, Dict

from fastapi import APIRouter

from ...services.deployments import DeployApplicationInput, perform_deploy, perform_rollback


router = APIRouter()


@router.post("/deploy", response_model=dict)
async def deploy_application(body: DeployApplicationInput) -> Dict[str, Any]:
    return perform_deploy(body)


@router.post("/deployments/rollback", response_model=dict)
async def rollback(app_name: str, environment: str) -> Dict[str, Any]:
    return perform_rollback(app_name=app_name, environment=environment)


