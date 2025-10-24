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
from ...services.deployment_config import DeploymentConfigService
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


class DeploymentConfigResponse(BaseModel):
    """Response model for deployment configuration"""
    owner: str
    repo: str
    replica_count: int
    last_scaled_at: Optional[str] = None
    last_scaled_by: Optional[str] = None
    created_at: str
    updated_at: str


class UpdateConfigRequest(BaseModel):
    """Request model for updating deployment configuration"""
    replica_count: int = Field(..., ge=0, le=10, description="Desired number of replicas (0-10)")
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


# === Deployment Configuration Endpoints ===

@router.get("/deployments/{owner}/{repo}/config", response_model=dict)
async def get_deployment_config(
    owner: str,
    repo: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get current deployment configuration including replica count.

    This endpoint returns the desired state configuration stored in the database,
    which persists across deployments and rollbacks.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        db: Database session

    Returns:
        Deployment configuration with replica count and audit information

    Example:
        GET /api/v1/deployments/K-Le-PaaS/test01/config

        Response:
        {
            "owner": "K-Le-PaaS",
            "repo": "test01",
            "replica_count": 3,
            "last_scaled_at": "2025-01-24T10:30:00Z",
            "last_scaled_by": "user123",
            "created_at": "2025-01-20T08:00:00Z",
            "updated_at": "2025-01-24T10:30:00Z"
        }
    """
    try:
        import structlog
        logger = structlog.get_logger(__name__)

        logger.info(
            "get_deployment_config_start",
            owner=owner,
            repo=repo
        )

        config_service = DeploymentConfigService()
        config = config_service.get_config(db, owner, repo)

        if not config:
            # Return default configuration if not found
            logger.info(
                "get_deployment_config_not_found",
                owner=owner,
                repo=repo,
                returning_default=True
            )
            return {
                "owner": owner,
                "repo": repo,
                "replica_count": 1,
                "last_scaled_at": None,
                "last_scaled_by": None,
                "created_at": None,
                "updated_at": None,
                "is_default": True
            }

        logger.info(
            "get_deployment_config_success",
            owner=owner,
            repo=repo,
            replicas=config.replica_count
        )

        return {
            "owner": config.github_owner,
            "repo": config.github_repo,
            "replica_count": config.replica_count,
            "last_scaled_at": config.last_scaled_at.isoformat() if config.last_scaled_at else None,
            "last_scaled_by": config.last_scaled_by,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            "is_default": False
        }

    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error(
            "get_deployment_config_error",
            error=str(e),
            owner=owner,
            repo=repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch deployment config: {str(e)}"
        )


@router.put("/deployments/{owner}/{repo}/config", response_model=dict)
async def update_deployment_config(
    owner: str,
    repo: str,
    body: UpdateConfigRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update deployment configuration (replica count).

    This endpoint allows manual updates to the desired replica count
    without triggering an actual deployment. The new value will be used
    in the next deployment or rollback operation.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        body: Configuration update request
        db: Database session

    Returns:
        Updated deployment configuration

    Example:
        PUT /api/v1/deployments/K-Le-PaaS/test01/config
        {
            "replica_count": 5,
            "user_id": "user123"
        }

        Response:
        {
            "owner": "K-Le-PaaS",
            "repo": "test01",
            "replica_count": 5,
            "last_scaled_at": "2025-01-24T11:00:00Z",
            "last_scaled_by": "user123",
            "message": "Configuration updated successfully"
        }
    """
    try:
        import structlog
        logger = structlog.get_logger(__name__)

        logger.info(
            "update_deployment_config_start",
            owner=owner,
            repo=repo,
            new_replicas=body.replica_count,
            user_id=body.user_id
        )

        # Validate replica count
        if body.replica_count < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Replica count must be non-negative: {body.replica_count}"
            )

        if body.replica_count > 10:
            raise HTTPException(
                status_code=400,
                detail=f"Replica count cannot exceed 10: {body.replica_count}"
            )

        config_service = DeploymentConfigService()
        config = config_service.set_replica_count(
            db, owner, repo, body.replica_count, body.user_id
        )

        logger.info(
            "update_deployment_config_success",
            owner=owner,
            repo=repo,
            new_replicas=body.replica_count,
            user_id=body.user_id
        )

        return {
            "owner": config.github_owner,
            "repo": config.github_repo,
            "replica_count": config.replica_count,
            "last_scaled_at": config.last_scaled_at.isoformat() if config.last_scaled_at else None,
            "last_scaled_by": config.last_scaled_by,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            "message": "Configuration updated successfully. Changes will take effect on next deployment."
        }

    except HTTPException:
        raise
    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error(
            "update_deployment_config_error",
            error=str(e),
            owner=owner,
            repo=repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update deployment config: {str(e)}"
        )


@router.get("/deployments/{owner}/{repo}/scaling-history", response_model=dict)
async def get_scaling_history(
    owner: str,
    repo: str,
    limit: int = 20,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get scaling history for a deployment.

    This endpoint returns the deployment history filtered to show
    scaling operations and their replica counts over time.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        limit: Maximum number of history entries to return (default: 20)
        db: Database session

    Returns:
        Scaling history with replica counts and timestamps

    Example:
        GET /api/v1/deployments/K-Le-PaaS/test01/scaling-history?limit=10

        Response:
        {
            "owner": "K-Le-PaaS",
            "repo": "test01",
            "current_replicas": 3,
            "history": [
                {
                    "id": 123,
                    "replica_count": 3,
                    "action": "scale",
                    "status": "success",
                    "image_tag": "abc1234",
                    "deployed_at": "2025-01-24T10:30:00Z",
                    "user_id": "user123"
                },
                ...
            ],
            "total": 10
        }
    """
    try:
        import structlog
        from ...models.deployment_history import DeploymentHistory

        logger = structlog.get_logger(__name__)

        logger.info(
            "get_scaling_history_start",
            owner=owner,
            repo=repo,
            limit=limit
        )

        # Get current config
        config_service = DeploymentConfigService()
        config = config_service.get_config(db, owner, repo)
        current_replicas = config.replica_count if config else 1

        # Get deployment history with replica information
        history_records = db.query(DeploymentHistory).filter(
            DeploymentHistory.github_owner == owner,
            DeploymentHistory.github_repo == repo,
            DeploymentHistory.status == "success"
        ).order_by(
            DeploymentHistory.deployed_at.desc()
        ).limit(limit).all()

        # Format history
        history = []
        for record in history_records:
            history.append({
                "id": record.id,
                "replica_count": record.replica_count or 1,
                "action": "rollback" if record.is_rollback else "deploy",
                "status": record.status,
                "image_tag": record.github_commit_sha[:7] if record.github_commit_sha else None,
                "deployed_at": record.deployed_at.isoformat() if record.deployed_at else None,
                "user_id": record.user_id
            })

        logger.info(
            "get_scaling_history_success",
            owner=owner,
            repo=repo,
            current_replicas=current_replicas,
            history_count=len(history)
        )

        return {
            "owner": owner,
            "repo": repo,
            "current_replicas": current_replicas,
            "history": history,
            "total": len(history)
        }

    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error(
            "get_scaling_history_error",
            error=str(e),
            owner=owner,
            repo=repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch scaling history: {str(e)}"
        )

