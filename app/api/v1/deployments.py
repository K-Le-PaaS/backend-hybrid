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
from ...services.deployment_history import get_deployment_history_service


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


@router.get("/deployments", response_model=dict)
async def get_deployments() -> Dict[str, Any]:
    """모든 배포 파이프라인 목록을 조회합니다."""
    try:
        history_service = get_deployment_history_service()
        
        # 모든 배포 기록을 조회하여 고유한 앱별로 그룹화
        all_deployments = await history_service.get_all_deployments()
        
        # 앱별로 그룹화하여 최신 배포 정보만 추출
        app_deployments = {}
        for deployment in all_deployments:
            key = f"{deployment.app_name}_{deployment.environment}"
            if key not in app_deployments or deployment.deployed_at > app_deployments[key].deployed_at:
                app_deployments[key] = deployment
        
        # 프론트엔드 형식으로 변환
        deployments = []
        for deployment in app_deployments.values():
            deployments.append({
                "id": deployment.id,
                "name": deployment.app_name,
                "repository": f"https://github.com/example/{deployment.app_name}",  # 기본값
                "branch": "main",  # 기본값
                "environment": deployment.environment,
                "status": deployment.status,
                "image": deployment.image,
                "replicas": deployment.replicas,
                "ports": [{"containerPort": 8080, "servicePort": 8080}],  # 기본값
                "envVars": {},
                "secrets": {},
                "createdAt": deployment.deployed_at.isoformat() if deployment.deployed_at else None,
                "updatedAt": deployment.deployed_at.isoformat() if deployment.deployed_at else None
            })
        
        return {
            "deployments": deployments,
            "total": len(deployments)
        }
        
    except Exception as e:
        return {
            "deployments": [],
            "total": 0,
            "error": str(e)
        }

