from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...services.github_workflow import create_or_update_workflow, DEFAULT_CI_YAML
from ...services.github_app import github_app_auth
from ...services.user_repository import get_user_repositories, add_user_repository, remove_user_repository
from ...database import get_db
from ...models.user_project_integration import UserProjectIntegration
from ..v1.auth_verify import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class InstallWorkflowRequest(BaseModel):
    owner: str = Field(..., description="GitHub owner/organization")
    repo: str = Field(..., description="Repository name")
    installation_id: str = Field(..., description="GitHub App installation ID")
    branch: Optional[str] = Field(None, description="Target branch (use when default is protected)")
    path: str = Field(default=".github/workflows/ci.yml", description="Workflow file path")
    yaml_content: Optional[str] = Field(None, description="Custom workflow YAML (defaults to standard CI)")
    commit_message: str = Field(default="chore: add or update CI workflow")
    author_name: Optional[str] = None
    author_email: Optional[str] = None


@router.post("/github/workflows/install", response_model=Dict[str, Any])
async def install_default_workflow(body: InstallWorkflowRequest) -> Dict[str, Any]:
    try:
        result = await create_or_update_workflow(
            owner=body.owner,
            repo=body.repo,
            installation_id=body.installation_id,
            branch=body.branch,
            path=body.path,
            yaml_content=body.yaml_content or DEFAULT_CI_YAML,
            commit_message=body.commit_message,
            author_name=body.author_name,
            author_email=body.author_email,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=f"Workflow installation failed: {result}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/app/installations", response_model=Dict[str, Any])
async def get_github_installations() -> Dict[str, Any]:
    """GitHub App 설치 목록을 조회합니다."""
    try:
        installations = await github_app_auth.get_app_installations()
        return {
            "status": "success",
            "installations": installations,
            "count": len(installations)
        }
    except Exception as e:
        logger.error(f"Failed to get GitHub installations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get installations: {str(e)}")


@router.post("/github/app/installations/{installation_id}/token", response_model=Dict[str, Any])
async def get_installation_token(installation_id: str) -> Dict[str, Any]:
    """GitHub App 설치 토큰을 가져옵니다."""
    try:
        token = await github_app_auth.get_installation_token(installation_id)
        return {
            "status": "success",
            "installation_id": installation_id,
            "token": token[:10] + "..."  # 보안을 위해 일부만 반환
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get installation token: {str(e)}")


@router.get("/github/app/install-url", response_model=Dict[str, Any])
async def get_app_install_url() -> Dict[str, Any]:
    """GitHub App 설치 URL을 생성합니다."""
    try:
        from ...core.config import get_settings
        
        # GitHub App ID를 사용하여 설치 URL 생성
        settings = get_settings()
        app_id = settings.github_app_id
        
        if not app_id:
            raise HTTPException(status_code=500, detail="GitHub App ID not configured")
        
        # GitHub App 설치 URL - 직접 설치 페이지로 이동
        # K-Le-PaaS GitHub App의 직접 설치 링크 사용
        install_url = "https://github.com/apps/K-Le-PaaS/installations/new"
        
        return {
            "status": "success",
            "install_url": install_url,
            "app_id": app_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate install URL: {str(e)}")


@router.post("/github/repositories/check-installation", response_model=Dict[str, Any])
async def check_repository_installation(owner: str, repo: str) -> Dict[str, Any]:
    """리포지토리에 GitHub App이 설치되어 있는지 확인합니다."""
    try:
        # 먼저 설치된 GitHub App 목록을 가져와서 해당 리포지토리에 접근 가능한지 확인
        installations = await github_app_auth.get_app_installations()
        
        if not installations or len(installations) == 0:
            return {
                "status": "error",
                "installed": False,
                "repository": f"{owner}/{repo}",
                "message": "GitHub App이 설치되어 있지 않습니다."
            }
        
        # 조직/소유자별 설치를 우선 선택 (organization에 설치된 경우 정확한 installation 사용)
        selected_installation = None
        try:
            for inst in installations:
                account = inst.get("account") or {}
                if account.get("login") == owner:
                    selected_installation = inst
                    break
        except Exception:
            selected_installation = None

        # 기본은 첫 번째 설치 사용
        chosen = selected_installation or installations[0]
        installation_id = chosen["id"]
        logger.info(f"Using installation ID: {installation_id}")
        token = await github_app_auth.get_installation_token(str(installation_id))
        
        import httpx
        async with httpx.AsyncClient() as client:
            # GitHub App이 접근 가능한 리포지토리 목록 조회
            repos_response = await client.get(
                "https://api.github.com/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )
            
            if repos_response.status_code != 200:
                return {
                    "status": "error",
                    "installed": False,
                    "repository": f"{owner}/{repo}",
                    "message": f"리포지토리 목록 조회 실패: {repos_response.status_code}"
                }
            
            # 설치된 리포지토리 목록에서 해당 리포지토리 찾기
            repos_data = repos_response.json()
            target_repo = f"{owner}/{repo}"
            
            for repo_info in repos_data.get("repositories", []):
                if repo_info["full_name"] == target_repo:
                    return {
                        "status": "success",
                        "installed": True,
                        "repository": target_repo,
                        "message": "GitHub App이 설치되어 있습니다.",
                        "installation_id": str(installation_id)
                    }
            
            # 리포지토리를 찾지 못한 경우 (조직/사용자별 설치 안내 링크 포함)
            from ...core.config import get_settings
            settings = get_settings()
            install_url = settings.github_app_install_url or "https://github.com/apps/K-Le-PaaS/installations/new"
            return {
                "status": "error",
                "installed": False,
                "repository": f"{owner}/{repo}",
                "message": "GitHub App이 해당 리포지토리에 설치되어 있지 않습니다.",
                "install_url": install_url
            }
    except Exception as e:
        return {
            "status": "error",
            "installed": False,
            "repository": f"{owner}/{repo}",
            "message": f"설치 확인 중 오류가 발생했습니다: {str(e)}"
        }


@router.get("/github/repositories", response_model=Dict[str, Any])
async def get_connected_repositories() -> Dict[str, Any]:
    """연결된 리포지토리 목록을 조회합니다."""
    try:
        # 설치된 GitHub App 목록을 가져와서 첫 번째 앱 사용
        installations = await github_app_auth.get_app_installations()
        
        if not installations or len(installations) == 0:
            return {
                "status": "success",
                "repositories": [],
                "count": 0,
                "message": "GitHub App이 설치되어 있지 않습니다."
            }
        
        installation_id = installations[0]["id"]
        token = await github_app_auth.get_installation_token(str(installation_id))
        
        # GitHub API로 리포지토리 목록 조회
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"GitHub API error: {response.text}")
            
            data = response.json()
            repositories = []
            
            for repo in data.get("repositories", []):
                repositories.append({
                    "id": str(repo["id"]),
                    "name": repo["name"],
                    "fullName": repo["full_name"],
                    "connected": True,
                    "lastSync": repo["updated_at"],
                    "branch": repo.get("default_branch", "main"),
                    "status": "healthy" if not repo.get("archived", False) else "warning",
                    "autoDeployEnabled": True,
                    "webhookConfigured": True,
                })
            
            return {
                "status": "success",
                "repositories": repositories,
                "count": len(repositories)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get repositories: {str(e)}")


@router.get("/github/pull-requests", response_model=Dict[str, Any])
async def get_pull_requests(user_id: str = "default", db = Depends(get_db)) -> Dict[str, Any]:
    """Pull Request 목록을 조회합니다."""
    try:
        # 사용자별 연동된 리포지토리 조회
        user_repositories = await get_user_repositories(db, user_id)
        print(f"DEBUG: user_repositories = {user_repositories}")
        
        if not user_repositories or len(user_repositories) == 0:
            return {
                "status": "success",
                "repositories": [],
                "count": 0,
                "message": "연동된 리포지토리가 없습니다."
            }
        
        # 설치된 GitHub App 목록을 가져와서 첫 번째 앱 사용
        installations = await github_app_auth.get_app_installations()
        
        if not installations or len(installations) == 0:
            return {
                "status": "success",
                "repositories": [],
                "count": 0,
                "message": "GitHub App이 설치되어 있지 않습니다."
            }
        
        installation_id = installations[0]["id"]
        token = await github_app_auth.get_installation_token(str(installation_id))
        
        import httpx
        async with httpx.AsyncClient() as client:
            repositories_data = []
            
            # 각 연동된 리포지토리의 PR 조회
            for repo in user_repositories:
                full_name = repo.get("fullName")
                if not full_name:
                    continue
                    
                prs_response = await client.get(
                    f"https://api.github.com/repos/{full_name}/pulls",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"
                    }
                )
                
                pull_requests = []
                if prs_response.status_code == 200:
                    prs_data = prs_response.json()
                    for pr in prs_data:
                        pull_requests.append({
                            "id": str(pr["id"]),
                            "number": pr["number"],
                            "title": pr["title"],
                            "author": pr["user"]["login"],
                            "status": pr["state"],
                            "branch": pr["head"]["ref"],
                            "targetBranch": pr["base"]["ref"],
                            "createdAt": pr["created_at"],
                            "ciStatus": "success",
                            "deploymentStatus": None
                        })
                
                # 리포지토리별로 PR 데이터 그룹화
                repositories_data.append({
                    "repository": {
                        "id": repo.get("id"),
                        "name": repo.get("name"),
                        "fullName": repo.get("fullName"),
                        "branch": repo.get("branch"),
                        "status": repo.get("status"),
                        "lastSync": repo.get("lastSync")
                    },
                    "pullRequests": pull_requests,
                    "prCount": len(pull_requests)
                })
            
            # PR 개수로 정렬
            repositories_data.sort(key=lambda x: x["prCount"], reverse=True)
            
            total_prs = sum(repo["prCount"] for repo in repositories_data)
            
            return {
                "status": "success",
                "repositories": repositories_data,
                "count": total_prs
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get pull requests: {str(e)}")


@router.get("/github/pipelines", response_model=Dict[str, Any])
async def get_pipelines(user_id: str = "default", db = Depends(get_db)) -> Dict[str, Any]:
    """CI/CD 파이프라인 상태를 조회합니다."""
    try:
        # 사용자별 연동된 리포지토리 조회
        user_repositories = await get_user_repositories(db, user_id)
        
        if not user_repositories or len(user_repositories) == 0:
            return {
                "status": "success",
                "repositories": [],
                "count": 0,
                "message": "연동된 리포지토리가 없습니다."
            }
        
        # 설치된 GitHub App 목록을 가져와서 첫 번째 앱 사용
        installations = await github_app_auth.get_app_installations()
        
        if not installations or len(installations) == 0:
            return {
                "status": "success",
                "repositories": [],
                "count": 0,
                "message": "GitHub App이 설치되어 있지 않습니다."
            }
        
        installation_id = installations[0]["id"]
        token = await github_app_auth.get_installation_token(str(installation_id))
        
        import httpx
        async with httpx.AsyncClient() as client:
            repositories_data = []
            
            # 각 연동된 리포지토리의 워크플로우 실행 조회
            for repo in user_repositories:
                full_name = repo.get("fullName")
                if not full_name:
                    continue
                    
                workflows_response = await client.get(
                    f"https://api.github.com/repos/{full_name}/actions/runs",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"
                    }
                )
                
                pipelines = []
                if workflows_response.status_code == 200:
                    workflows_data = workflows_response.json()
                    # 최근 5개 워크플로우만 처리 (성능 최적화)
                    recent_workflows = workflows_data.get("workflow_runs", [])[:5]
                    
                    for workflow in recent_workflows:
                        # Jobs 조회는 실행 중이거나 실패한 워크플로우만
                        stages = []
                        if workflow.get("status") in ["in_progress", "completed"] and workflow.get("conclusion") != "success":
                            try:
                                jobs_response = await client.get(
                                    f"https://api.github.com/repos/{full_name}/actions/runs/{workflow['id']}/jobs",
                                    headers={
                                        "Authorization": f"Bearer {token}",
                                        "Accept": "application/vnd.github+json",
                                        "X-GitHub-Api-Version": "2022-11-28"
                                    }
                                )
                                
                                if jobs_response.status_code == 200:
                                    jobs = jobs_response.json()
                                    for job in jobs.get("jobs", []):
                                        stages.append({
                                            "name": job["name"],
                                            "status": job["conclusion"] or job["status"]
                                        })
                            except Exception as e:
                                # Jobs 조회 실패 시 빈 stages로 처리
                                pass
                        
                        # 상태 매핑
                        status_mapping = {
                            "completed": "success" if workflow["conclusion"] == "success" else "failed",
                            "in_progress": "running",
                            "queued": "pending",
                            "cancelled": "cancelled"
                        }
                        
                        pipelines.append({
                            "id": str(workflow["id"]),
                            "branch": workflow["head_branch"],
                            "commit": workflow["head_sha"][:7],
                            "status": status_mapping.get(workflow["status"], "unknown"),
                            "startedAt": workflow["created_at"],
                            "duration": workflow.get("run_duration_ms", 0) // 1000 if workflow.get("run_duration_ms") else 0,
                            "stages": stages
                        })
                
                # 리포지토리별로 파이프라인 데이터 그룹화
                repositories_data.append({
                    "repository": {
                        "id": repo.get("id"),
                        "name": repo.get("name"),
                        "fullName": repo.get("fullName"),
                        "branch": repo.get("branch"),
                        "status": repo.get("status"),
                        "lastSync": repo.get("lastSync")
                    },
                    "pipelines": pipelines,
                    "pipelineCount": len(pipelines)
                })
            
            # 파이프라인 개수로 정렬
            repositories_data.sort(key=lambda x: x["pipelineCount"], reverse=True)
            
            total_pipelines = sum(repo["pipelineCount"] for repo in repositories_data)
            
            return {
                "status": "success",
                "repositories": repositories_data,
                "count": total_pipelines
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get pipelines: {str(e)}")


# 연동된 리포지토리 저장 (메모리 기반, 실제로는 DB에 저장해야 함)
connected_repositories = []

@router.post("/github/repositories/connect", response_model=Dict[str, Any])
async def connect_repository(
    owner: str, 
    repo: str, 
    user_id: str = "default",
    user_email: str = "user@example.com",
    db = Depends(get_db)
) -> Dict[str, Any]:
    """리포지토리를 연동 목록에 추가합니다."""
    try:
        # 먼저 설치 상태 확인
        installation_check = await check_repository_installation(owner, repo)
        
        if installation_check.get("installed"):
            # GitHub API에서 리포지토리 정보 조회
            installation_id = installation_check.get("installation_id")
            token = await github_app_auth.get_installation_token(str(installation_id))
            
            import httpx
            async with httpx.AsyncClient() as client:
                repo_response = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"
                    }
                )
                
                if repo_response.status_code == 200:
                    repo_data = repo_response.json()
                    
                    # 데이터베이스에 리포지토리 연동 정보 저장
                    result = await add_user_repository(
                        db=db,
                        user_id=user_id,
                        user_email=user_email,
                        repository_owner=owner,
                        repository_name=repo,
                        repository_full_name=f"{owner}/{repo}",
                        repository_id=str(repo_data["id"]),
                        branch=repo_data.get("default_branch", "main"),
                        installation_id=installation_id
                    )
                    
                    return result
                else:
                    return {
                        "status": "error",
                        "message": f"리포지토리 정보 조회 실패: {repo_response.status_code}",
                        "repository": f"{owner}/{repo}"
                    }
        else:
            return {
                "status": "error",
                "message": installation_check["message"],
                "repository": f"{owner}/{repo}"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect repository: {str(e)}")


@router.get("/github/repositories/connected", response_model=Dict[str, Any])
async def get_connected_repositories(user_id: str = "default", db = Depends(get_db)) -> Dict[str, Any]:
    """연동된 리포지토리 목록을 조회합니다."""
    try:
        print(f"DEBUG: Getting repositories for user_id: {user_id}")
        # 사용자별 연동된 리포지토리 조회
        repositories = await get_user_repositories(db, user_id)
        print(f"DEBUG: Found {len(repositories)} repositories for user {user_id}")
        
        return {
            "status": "success",
            "repositories": repositories,
            "count": len(repositories)
        }
    except Exception as e:
        print(f"ERROR: Failed to get repositories for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get connected repositories: {str(e)}")


@router.put("/github/webhook/{integration_id}")
async def update_webhook_config(
    integration_id: int,
    enabled: bool = Query(..., description="Auto deploy enabled status"),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """GitHub 웹훅 설정 업데이트 (auto_deploy 토글)"""
    try:
        # 통합 정보 조회
        integration = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.id == integration_id,
            UserProjectIntegration.user_id == str(current_user["id"])
        ).first()
        
        if not integration:
            raise HTTPException(
                status_code=404, 
                detail=f"Integration ID {integration_id}를 찾을 수 없습니다."
            )
        
        # auto_deploy_enabled 업데이트
        integration.auto_deploy_enabled = enabled
        db.commit()
        db.refresh(integration)
        
        return {
            "status": "success",
            "message": f"Auto Deploy가 {'활성화' if enabled else '비활성화'}되었습니다.",
            "integration_id": integration_id,
            "auto_deploy_enabled": enabled,
            "repository": {
                "owner": integration.github_owner,
                "repo": integration.github_repo,
                "full_name": integration.github_full_name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"웹훅 설정 업데이트 실패: {str(e)}"
        )


@router.get("/github/webhook/{integration_id}/status")
async def get_webhook_status(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """GitHub 웹훅 상태 조회"""
    try:
        # 통합 정보 조회
        integration = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.id == integration_id,
            UserProjectIntegration.user_id == str(current_user["id"])
        ).first()
        
        if not integration:
            raise HTTPException(
                status_code=404, 
                detail=f"Integration ID {integration_id}를 찾을 수 없습니다."
            )
        
        return {
            "status": "success",
            "integration_id": integration_id,
            "auto_deploy_enabled": integration.auto_deploy_enabled,
            "webhook_configured": bool(integration.github_webhook_secret),
            "repository": {
                "owner": integration.github_owner,
                "repo": integration.github_repo,
                "full_name": integration.github_full_name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"웹훅 상태 조회 실패: {str(e)}"
        )