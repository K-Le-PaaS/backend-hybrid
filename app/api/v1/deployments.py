from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...services.deployments_enhanced import (
    DeployApplicationInput,
    perform_deploy,
    perform_rollback,
    Environment,
    get_deploy_status,
    list_recent_versions,
)
from ...services.deployment_history import get_deployment_history_service
from ...services.rollback import get_rollback_list as get_rollback_list_service
from ...database import get_db


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


# === NLP-Based Operation Endpoints ===
# These endpoints integrate with the existing NLP command processor
# to leverage the already-implemented natural language functionality

class ScaleRequest(BaseModel):
    """Request model for scaling deployments"""
    replicas: int = Field(..., ge=0, le=10, description="Target number of replicas (0-10)")
    user_id: Optional[str] = Field(default="api_user", description="User ID for audit")


class RestartRequest(BaseModel):
    """Request model for restarting deployments"""
    user_id: Optional[str] = Field(default="api_user", description="User ID for audit")


@router.post("/deployments/{owner}/{repo}/scale", response_model=dict)
async def scale_deployment(
    owner: str,
    repo: str,
    body: ScaleRequest
) -> Dict[str, Any]:
    """
    Scale deployment by adjusting replica count.
    Uses NLP command processor for consistent behavior with natural language commands.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        body: Scale request with target replicas

    Returns:
        Result of the scaling operation

    Example:
        POST /api/v1/deployments/K-Le-PaaS/test01/scale
        {
            "replicas": 3,
            "user_id": "user123"
        }
    """
    try:
        from ...services.commands import CommandRequest, plan_command, execute_command
        import structlog
        logger = structlog.get_logger(__name__)

        # Convert to NLP command format
        command_text = f"Scale {owner}/{repo} to {body.replicas} replicas"
        logger.info(f"Scale request: {command_text}")

        # Create command request
        req = CommandRequest(
            command="scale",
            deployment_name=repo,
            namespace="default",
            replicas=body.replicas,
            github_owner=owner,
            github_repo=repo
        )

        # Execute through NLP command processor
        plan = plan_command(req)
        if not plan.args:
            plan.args = {}
        plan.args["user_id"] = body.user_id

        result = await execute_command(plan)

        return {
            "success": True,
            "message": f"Scaled {owner}/{repo} to {body.replicas} replicas",
            "data": result
        }

    except Exception as e:
        logger.error(f"Scale operation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Scale operation failed: {str(e)}"
        )


@router.post("/deployments/{owner}/{repo}/restart", response_model=dict)
async def restart_deployment(
    owner: str,
    repo: str,
    body: RestartRequest
) -> Dict[str, Any]:
    """
    Restart deployment with same image.
    Uses NLP command processor for consistent behavior with natural language commands.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        body: Restart request with user_id

    Returns:
        Result of the restart operation

    Example:
        POST /api/v1/deployments/K-Le-PaaS/test01/restart
        {
            "user_id": "user123"
        }
    """
    try:
        from ...services.commands import CommandRequest, plan_command, execute_command
        import structlog
        logger = structlog.get_logger(__name__)

        # Convert to NLP command format
        command_text = f"Restart {owner}/{repo}"
        logger.info(f"Restart request: {command_text}")

        # Create command request (restart is typically a rolling restart)
        req = CommandRequest(
            command="restart",
            deployment_name=repo,
            namespace="default",
            github_owner=owner,
            github_repo=repo
        )

        # Execute through NLP command processor
        plan = plan_command(req)
        if not plan.args:
            plan.args = {}
        plan.args["user_id"] = body.user_id

        result = await execute_command(plan)

        return {
            "success": True,
            "message": f"Restarted {owner}/{repo}",
            "data": result
        }

    except Exception as e:
        logger.error(f"Restart operation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Restart operation failed: {str(e)}"
        )


@router.get("/deployments/{owner}/{repo}/rollback/list", response_model=dict)
async def get_rollback_list(
    owner: str,
    repo: str,
    user_id: Optional[str] = "api_user",
    limit: int = 10,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get list of rollback candidates for a deployment.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        user_id: User ID for audit (optional)
        limit: Maximum number of candidates to return
        db: Database session

    Returns:
        Rollback candidates list with current state and history

    Example:
        GET /api/v1/deployments/K-Le-PaaS/test01/rollback/list?user_id=user123&limit=10
    """
    try:
        import structlog
        logger = structlog.get_logger(__name__)

        logger.info(
            "get_rollback_list_start",
            owner=owner,
            repo=repo,
            user_id=user_id,
            limit=limit
        )

        # Use existing rollback service with proper function
        rollback_data = await get_rollback_list_service(
            owner=owner,
            repo=repo,
            db=db,
            limit=limit
        )

        logger.info(
            "get_rollback_list_success",
            owner=owner,
            repo=repo,
            count=rollback_data.get("total_available", 0)
        )

        return rollback_data

    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error(
            "get_rollback_list_error",
            error=str(e),
            owner=owner,
            repo=repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch rollback list: {str(e)}"
        )

