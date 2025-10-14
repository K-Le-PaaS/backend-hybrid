"""
Deployment Histories API

CI/CD 파이프라인의 배포 히스토리를 조회하는 API 엔드포인트입니다.
실시간 배포 진행률 표시를 위한 데이터를 제공합니다.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from ...database import get_db
from ...models.deployment_history import DeploymentHistory
from .auth_verify import get_current_user

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
        deployment_list = []
        for deployment in deployments:
            deployment_list.append(deployment.to_dict())
        
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
        # Explicitly disable caching
        from fastapi import Response
        resp = Response(content=None)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return data
        
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
        deployment_list = []
        for deployment in deployments:
            deployment_list.append(deployment.to_dict())
        
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
        
        # 통계 계산
        total_deployments = query.count()
        successful_deployments = query.filter(DeploymentHistory.status == "success").count()
        failed_deployments = query.filter(DeploymentHistory.status == "failed").count()
        running_deployments = query.filter(DeploymentHistory.status == "running").count()
        
        # 성공률 계산
        success_rate = (successful_deployments / total_deployments * 100) if total_deployments > 0 else 0
        
        # 평균 소요 시간 계산
        completed_deployments = query.filter(
            DeploymentHistory.status.in_(["success", "failed"]),
            DeploymentHistory.total_duration.isnot(None)
        ).all()
        
        avg_duration = 0
        if completed_deployments:
            total_duration = sum(d.total_duration for d in completed_deployments)
            avg_duration = total_duration / len(completed_deployments)
        
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
