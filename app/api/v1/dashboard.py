from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import asyncio
import random
import logging

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...services.monitoring import get_system_metrics
from ...services.deployment import get_deployment_stats
from ...services.cluster import get_cluster_info
from ...database import get_db
from .auth_verify import get_current_user
from ...services.user_repository import get_user_repositories

logger = logging.getLogger(__name__)

router = APIRouter()


class RecentDeployment(BaseModel):
    """최근 배포 정보 모델"""
    name: str
    version: str
    status: str  # 'success', 'in-progress', 'failed'
    time: str
    message: str


class SystemHealth(BaseModel):
    """시스템 상태 모델"""
    service: str
    status: str  # 'healthy', 'warning', 'error'


class ConnectedRepository(BaseModel):
    """연결된 리포지토리 정보 모델"""
    id: str
    name: str
    fullName: str
    branch: str
    lastSync: str


class PullRequest(BaseModel):
    """Pull Request 정보 모델"""
    id: str
    number: int
    title: str
    author: str
    status: str
    createdAt: str
    htmlUrl: str


class DashboardData(BaseModel):
    """대시보드 데이터 모델"""
    clusters: int
    deployments: int
    pendingDeployments: int
    activeDeployments: int
    cpuUsage: int
    memoryUsage: int
    recentDeployments: List[RecentDeployment]
    systemHealth: List[SystemHealth]
    connectedRepositories: List[ConnectedRepository]
    pullRequests: List[PullRequest]


@router.get("/dashboard/overview", response_model=DashboardData)
async def get_dashboard_overview(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> DashboardData:
    """대시보드 개요 데이터를 반환합니다."""
    try:
        # 실제 서비스에서 데이터를 가져오는 로직
        # 현재는 목업 데이터를 반환하지만, 실제 구현에서는 서비스들을 호출
        
        # 클러스터 정보 가져오기
        cluster_info = await get_cluster_info()
        clusters = cluster_info.get('total_clusters', 3)
        
        # 배포 통계 가져오기
        deployment_stats = await get_deployment_stats()
        total_deployments = deployment_stats.get('total', 12)
        pending_deployments = deployment_stats.get('pending', 4)
        active_deployments = deployment_stats.get('active', 8)
        
        # 시스템 메트릭 가져오기
        metrics = get_system_metrics()
        cpu_usage = int(metrics.get('cpu_usage', 68))
        memory_usage = int(metrics.get('memory_usage', 45))
        
        # 최근 배포 이력 (실제 데이터 조회)
        recent_deployments = []
        try:
            from .deployment_histories import get_repositories_latest_deployments
            deployment_response = await get_repositories_latest_deployments(db=db, current_user=current_user)
            if deployment_response.get("status") == "success":
                deployments = deployment_response.get("repositories", [])
                for deployment in deployments[:3]:  # 최대 3개만
                    recent_deployments.append(RecentDeployment(
                        name=deployment.get("full_name", ""),
                        version=deployment.get("latest_deployment", {}).get("image", {}).get("tag", ""),
                        status=deployment.get("latest_deployment", {}).get("status", "unknown"),
                        time=deployment.get("latest_deployment", {}).get("created_at", ""),
                        message=f"Deployed {deployment.get('latest_deployment', {}).get('created_at', '')}"
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch recent deployments: {e}")
            # 데이터가 없으면 빈 배열 반환
            recent_deployments = []
        
        # 시스템 상태
        system_health = [
            SystemHealth(service="NCP Connection", status="healthy"),
            SystemHealth(service="Kubernetes API", status="healthy"),
            SystemHealth(service="GitHub Integration", status="warning"),
            SystemHealth(service="Monitoring", status="healthy")
        ]
        
        # 연결된 리포지토리 정보 가져오기 (사용자별)
        connected_repositories = []
        try:
            user_repos = await get_user_repositories(db, str(current_user.get("id", "")))
            # 최대 3개만 표시
            for repo in user_repos[:3]:
                connected_repositories.append(ConnectedRepository(
                    id=repo.get("id", ""),
                    name=repo.get("name", ""),
                    fullName=repo.get("fullName", ""),
                    branch=repo.get("branch", "main"),
                    lastSync=repo.get("lastSync", "")
                ))
        except Exception as e:
            logger.warning(f"Failed to fetch user repositories: {e}")
            # 데이터가 없으면 빈 배열 반환
            connected_repositories = []
        
        # Pull Request 정보 가져오기 (사용자 리포지토리에서만) - 병렬 처리로 최적화
        pull_requests = []
        try:
            # 사용자 리포지토리 목록 가져오기
            user_repos = await get_user_repositories(db, str(current_user.get("id", "")))
            
            if not user_repos:
                pull_requests = []
            else:
                # GitHub App 토큰 가져오기
                from ...services.github_app import github_app_auth
                installations = await github_app_auth.get_app_installations()
                
                if installations:
                    installation_id = installations[0]["id"]
                    token = await github_app_auth.get_installation_token(str(installation_id))
                    
                    import httpx
                    import asyncio
                    async with httpx.AsyncClient(timeout=10.0) as client:  # 타임아웃 설정
                        # 병렬로 모든 리포지토리의 PR 조회
                        async def fetch_repo_prs(repo_name):
                            try:
                                response = await client.get(
                                    f"https://api.github.com/repos/{repo_name}/pulls",
                                    headers={
                                        "Authorization": f"Bearer {token}",
                                        "Accept": "application/vnd.github+json",
                                        "X-GitHub-Api-Version": "2022-11-28"
                                    },
                                    params={"state": "open", "per_page": 3}  # 최대 3개로 제한
                                )
                                if response.status_code == 200:
                                    return response.json()
                                return []
                            except Exception as e:
                                logger.warning(f"Failed to fetch PRs for {repo_name}: {e}")
                                return []
                        
                        # 모든 리포지토리의 PR을 병렬로 조회
                        repo_names = [repo.get("fullName") for repo in user_repos if repo.get("fullName")]
                        pr_responses = await asyncio.gather(*[fetch_repo_prs(name) for name in repo_names], return_exceptions=True)
                        
                        # 결과 수집
                        all_prs = []
                        for prs_data in pr_responses:
                            if isinstance(prs_data, list):
                                for pr in prs_data:
                                    all_prs.append({
                                        "id": str(pr["id"]),
                                        "number": pr["number"],
                                        "title": pr["title"],
                                        "author": pr["user"]["login"],
                                        "status": pr["state"],
                                        "createdAt": pr["created_at"],
                                        "htmlUrl": pr["html_url"]
                                    })
                        
                        # 생성일 기준으로 정렬하고 최신 3개만 선택
                        all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
                        for pr in all_prs[:3]:
                            pull_requests.append(PullRequest(
                                id=pr.get("id", ""),
                                number=pr.get("number", 0),
                                title=pr.get("title", ""),
                                author=pr.get("author", ""),
                                status=pr.get("status", "open"),
                                createdAt=pr.get("createdAt", ""),
                                htmlUrl=pr.get("htmlUrl", "")
                            ))
        except Exception as e:
            logger.warning(f"Failed to fetch pull requests: {e}")
            # 데이터가 없으면 빈 배열 반환
            pull_requests = []
        
        return DashboardData(
            clusters=clusters,
            deployments=total_deployments,
            pendingDeployments=pending_deployments,
            activeDeployments=active_deployments,
            cpuUsage=cpu_usage,
            memoryUsage=memory_usage,
            recentDeployments=recent_deployments,
            systemHealth=system_health,
            connectedRepositories=connected_repositories,
            pullRequests=pull_requests
        )
        
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve dashboard data: {str(e)}"
        )


@router.get("/dashboard/metrics")
async def get_dashboard_metrics(request: Request) -> Dict[str, Any]:
    """대시보드 메트릭 데이터를 반환합니다."""
    try:
        # 실제 메트릭 데이터를 가져오는 로직
        metrics = get_system_metrics()
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Failed to get dashboard metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve dashboard metrics: {str(e)}"
        )


@router.get("/dashboard/health")
async def get_dashboard_health(request: Request) -> Dict[str, Any]:
    """대시보드 헬스 체크 데이터를 반환합니다."""
    try:
        # 시스템 상태 확인
        health_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": "healthy",
            "components": [
                {"name": "API Server", "status": "healthy"},
                {"name": "Database", "status": "healthy"},
                {"name": "MCP Server", "status": "healthy"},
                {"name": "Monitoring", "status": "healthy"}
            ]
        }
        
        return health_data
        
    except Exception as e:
        logger.error(f"Failed to get dashboard health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve dashboard health: {str(e)}"
        )
