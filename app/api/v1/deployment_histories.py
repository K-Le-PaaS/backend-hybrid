"""
Deployment Histories API

CI/CD 파이프라인의 배포 히스토리를 조회하는 API 엔드포인트입니다.
실시간 배포 진행률 표시를 위한 데이터를 제공합니다.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from kubernetes.client.rest import ApiException

from ...database import get_db
from ...models.deployment_history import DeploymentHistory
from .auth_verify import get_current_user
from ...services.k8s_client import get_apps_v1_api

router = APIRouter()


@router.get("/deployment-histories")
async def get_deployment_histories(
    repository: Optional[str] = Query(None, description="Repository name (owner/repo)"),
    status: Optional[str] = Query(None, description="Deployment status (running, success, failed)"),
    limit: int = Query(20, ge=1, le=100, description="Number of deployments to return"),
    offset: int = Query(0, ge=0, description="Number of deployments to skip"),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    배포 히스토리 조회
    
    사용자의 배포 히스토리를 조회합니다. 특정 리포지토리나 상태로 필터링할 수 있습니다.
    """
    try:
        # 기본 쿼리 (사용자별 필터링)
        query = db.query(DeploymentHistory).filter(
            DeploymentHistory.user_id == current_user["id"]
        )
        
        # 리포지토리 필터링
        if repository:
            if "/" not in repository:
                raise HTTPException(
                    status_code=400, 
                    detail="Repository must be in format 'owner/repo'"
                )
            owner, repo = repository.split("/", 1)
            query = query.filter(
                and_(
                    DeploymentHistory.github_owner == owner,
                    DeploymentHistory.github_repo == repo
                )
            )
        
        # 상태 필터링
        if status:
            if status not in ["running", "success", "failed"]:
                raise HTTPException(
                    status_code=400,
                    detail="Status must be one of: running, success, failed"
                )
            query = query.filter(DeploymentHistory.status == status)
        
        # 정렬 및 페이징
        total_count = query.count()
        deployments = query.order_by(desc(DeploymentHistory.started_at)).offset(offset).limit(limit).all()
        
        # 응답 데이터 구성
        deployment_list = [deployment.to_dict() for deployment in deployments]
        
        data = {
            "deployments": deployment_list,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count
            },
            "filters": {
                "repository": repository,
                "status": status
            }
        }
        # Return with no-cache headers
        return JSONResponse(
            content=data,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch deployment histories: {str(e)}")


@router.get("/deployment-histories/{deployment_id}")
async def get_deployment_history(
    deployment_id: int,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    특정 배포 히스토리 상세 조회
    
    배포 ID로 특정 배포의 상세 정보를 조회합니다.
    """
    try:
        deployment = db.query(DeploymentHistory).filter(
            and_(
                DeploymentHistory.id == deployment_id,
                DeploymentHistory.user_id == current_user["id"]
            )
        ).first()
        
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        
        return {
            "deployment": deployment.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch deployment: {str(e)}")


@router.get("/deployment-histories/repository/{owner}/{repo}")
async def get_repository_deployment_histories(
    owner: str,
    repo: str,
    status: Optional[str] = Query(None, description="Deployment status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    특정 리포지토리의 배포 히스토리 조회
    
    특정 리포지토리의 모든 배포 히스토리를 조회합니다.
    """
    try:
        # 기본 쿼리
        query = db.query(DeploymentHistory).filter(
            and_(
                DeploymentHistory.user_id == current_user["id"],
                DeploymentHistory.github_owner == owner,
                DeploymentHistory.github_repo == repo
            )
        )
        
        # 상태 필터링
        if status:
            if status not in ["running", "success", "failed"]:
                raise HTTPException(
                    status_code=400,
                    detail="Status must be one of: running, success, failed"
                )
            query = query.filter(DeploymentHistory.status == status)
        
        # 정렬 및 페이징
        total_count = query.count()
        deployments = query.order_by(desc(DeploymentHistory.started_at)).offset(offset).limit(limit).all()
        
        # 응답 데이터 구성
        deployment_list = [deployment.to_dict() for deployment in deployments]
        
        return {
            "repository": f"{owner}/{repo}",
            "deployments": deployment_list,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count
            },
            "filters": {
                "status": status
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch repository deployments: {str(e)}")


@router.get("/deployment-histories/stats/summary")
async def get_deployment_stats(
    repository: Optional[str] = Query(None, description="Repository name (owner/repo)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    배포 통계 조회
    
    사용자의 배포 통계를 조회합니다.
    """
    try:
        from datetime import datetime, timedelta
        
        # 날짜 범위 설정
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # 기본 쿼리
        query = db.query(DeploymentHistory).filter(
            and_(
                DeploymentHistory.user_id == current_user["id"],
                DeploymentHistory.started_at >= start_date,
                DeploymentHistory.started_at <= end_date
            )
        )
        
        # 리포지토리 필터링
        if repository:
            if "/" not in repository:
                raise HTTPException(
                    status_code=400, 
                    detail="Repository must be in format 'owner/repo'"
                )
            owner, repo_name = repository.split("/", 1)
            query = query.filter(
                and_(
                    DeploymentHistory.github_owner == owner,
                    DeploymentHistory.github_repo == repo_name
                )
            )
        
        # 통계 계산(한 번의 쿼리로 집계)
        from sqlalchemy import func, case
        stats = query.with_entities(
            func.count().label("total"),
            func.sum(case((DeploymentHistory.status == "success", 1), else_=0)).label("successful"),
            func.sum(case((DeploymentHistory.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((DeploymentHistory.status == "running", 1), else_=0)).label("running")
        ).one()
        total_deployments = stats.total or 0
        successful_deployments = stats.successful or 0
        failed_deployments = stats.failed or 0
        running_deployments = stats.running or 0
        
        # 성공률 계산
        success_rate = (successful_deployments / total_deployments * 100) if total_deployments > 0 else 0
        
        # 평균 소요 시간 계산(DB 집계)
        avg_duration = query.filter(
            DeploymentHistory.status.in_(["success", "failed"]),
            DeploymentHistory.total_duration.isnot(None)
        ).with_entities(func.avg(DeploymentHistory.total_duration)).scalar() or 0
        
        # 최근 배포들
        recent_deployments = query.order_by(desc(DeploymentHistory.started_at)).limit(5).all()
        recent_deployment_list = [d.to_dict() for d in recent_deployments]
        
        return {
            "summary": {
                "total_deployments": total_deployments,
                "successful_deployments": successful_deployments,
                "failed_deployments": failed_deployments,
                "running_deployments": running_deployments,
                "success_rate": round(success_rate, 2),
                "average_duration": round(avg_duration, 2)
            },
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "recent_deployments": recent_deployment_list,
            "filters": {
                "repository": repository
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch deployment stats: {str(e)}")


@router.get("/deployment-histories/repositories/latest")
async def get_repositories_latest_deployments(
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    사용자의 모든 연동된 repository의 최신 배포 조회

    각 repository의 최신 배포 상태와 Kubernetes 워크로드 정보를 반환합니다.
    """
    try:
        from ...models.user_project_integration import UserProjectIntegration
        from sqlalchemy import func
        import random

        # 사용자의 모든 연동된 repository 조회
        integrations = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.user_id == current_user["id"]
        ).all()

        repositories = []

        for integration in integrations:
            # 각 repository의 최신 배포 조회
            latest_deployment = db.query(DeploymentHistory).filter(
                and_(
                    DeploymentHistory.user_id == current_user["id"],
                    DeploymentHistory.github_owner == integration.github_owner,
                    DeploymentHistory.github_repo == integration.github_repo
                )
            ).order_by(desc(DeploymentHistory.started_at)).first()

            if latest_deployment:
                # Kubernetes 워크로드 정보 (실제 K8s API 조회)
                k8s_info = await _get_kubernetes_deployment_info(
                    integration.github_owner,
                    integration.github_repo,
                    latest_deployment.namespace or "default"
                )

                # 배포 정보에 K8s 정보 추가
                deployment_dict = latest_deployment.to_dict()
                deployment_dict["cluster"] = k8s_info

                repositories.append({
                    "owner": integration.github_owner,
                    "repo": integration.github_repo,
                    "full_name": integration.github_full_name,
                    "branch": integration.branch or "main",
                    "latest_deployment": deployment_dict,
                    "auto_deploy_enabled": integration.auto_deploy_enabled
                })
            else:
                # 배포 이력이 없는 경우
                repositories.append({
                    "owner": integration.github_owner,
                    "repo": integration.github_repo,
                    "full_name": integration.github_full_name,
                    "branch": integration.branch or "main",
                    "latest_deployment": None,
                    "auto_deploy_enabled": integration.auto_deploy_enabled
                })

        return JSONResponse(
            content={"repositories": repositories},
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch repository deployments: {str(e)}"
        )


async def _get_kubernetes_deployment_info(owner: str, repo: str, namespace: str) -> dict:
    """
    Kubernetes API를 통해 실제 Deployment 정보를 조회합니다.
    
    Args:
        owner: GitHub repository owner
        repo: GitHub repository name  
        namespace: Kubernetes namespace
        
    Returns:
        dict: Kubernetes 워크로드 정보
    """
    try:
        # Kubernetes API 클라이언트 생성
        apps_v1 = get_apps_v1_api()
        
        # Deployment 이름 생성 (실제 패턴: k-le-paas-{repo}-deploy)
        deployment_name = f"k-le-paas-{repo}-deploy"
        
        # 실제 Deployment 조회
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )
        
        # 실제 레플리카 정보 추출
        k8s_info = {
            "namespace": namespace,
            "replicas": {
                "desired": deployment.spec.replicas,
                "ready": deployment.status.ready_replicas or 0,
                "current": deployment.status.replicas or 0,
                "available": deployment.status.available_replicas or 0,
                "unavailable": deployment.status.unavailable_replicas or 0
            },
            "resources": {
                "cpu": 0,  # TODO: 실제 메트릭 조회 필요
                "memory": 0  # TODO: 실제 메트릭 조회 필요
            },
            "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
        }
        
        return k8s_info
        
    except ApiException as e:
        if e.status == 404:
            # Deployment가 존재하지 않는 경우
            return {
                "namespace": namespace,
                "replicas": {
                    "desired": 0,
                    "ready": 0,
                    "current": 0,
                    "available": 0,
                    "unavailable": 0
                },
                "resources": {
                    "cpu": 0,
                    "memory": 0
                },
                "status": "NotFound"
            }
        else:
            # 다른 API 에러의 경우 기본값 반환
            return {
                "namespace": namespace,
                "replicas": {
                    "desired": 1,
                    "ready": 0,
                    "current": 0,
                    "available": 0,
                    "unavailable": 0
                },
                "resources": {
                    "cpu": 0,
                    "memory": 0
                },
                "status": "Error"
            }
    except Exception as e:
        # K8s API 연결 실패 등의 경우 기본값 반환
        return {
            "namespace": namespace,
            "replicas": {
                "desired": 1,
                "ready": 0,
                "current": 0,
                "available": 0,
                "unavailable": 0
            },
            "resources": {
                "cpu": 0,
                "memory": 0
            },
            "status": "Error"
        }


@router.get("/deployment-histories/websocket/status")
async def get_websocket_status(
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    WebSocket 연결 상태 조회

    현재 WebSocket 연결 상태를 조회합니다.
    """
    try:
        from ...websocket.deployment_monitor import deployment_monitor_manager

        stats = deployment_monitor_manager.get_connection_stats()

        return {
            "websocket_status": "active",
            "connection_stats": stats,
            "user_id": current_user["id"]
        }

    except Exception as e:
        return {
            "websocket_status": "inactive",
            "error": str(e),
            "user_id": current_user["id"]
        }
