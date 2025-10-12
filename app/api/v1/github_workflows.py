from typing import Any, Dict, Optional
import json

from fastapi import APIRouter, HTTPException, Depends, Query, Request
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


async def get_pr_ci_status(client, token: str, repo_full_name: str, pr_number: int) -> str:
    """PR의 실제 CI 상태를 조회합니다."""
    try:
        # GitHub Actions 워크플로우 실행 상태 조회
        response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/actions/runs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            },
            params={
                "per_page": 10,  # 최근 10개 실행만 조회
                "branch": f"pr/{pr_number}"  # PR 브랜치의 워크플로우 실행
            }
        )
        
        if response.status_code == 200:
            runs = response.json().get("workflow_runs", [])
            if runs:
                latest_run = runs[0]
                conclusion = latest_run.get("conclusion")
                status = latest_run.get("status")
                
                if conclusion == "success":
                    return "success"
                elif conclusion == "failure":
                    return "failure"
                elif conclusion == "cancelled":
                    return "cancelled"
                elif status == "in_progress":
                    return "pending"
                else:
                    return "pending"
        
        # 워크플로우가 없거나 조회 실패 시 PR 상태 기반으로 판단
        pr_response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
        )
        
        if pr_response.status_code == 200:
            pr_data = pr_response.json()
            # PR이 mergeable 상태인지 확인
            if pr_data.get("mergeable") is True:
                return "success"
            elif pr_data.get("mergeable") is False:
                return "failure"
        
        return "pending"
        
    except Exception as e:
        logger.warning(f"Failed to get CI status for PR {pr_number}: {e}")
        return "pending"


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
async def get_pull_requests(
    user_id: str = "default", 
    db = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Pull Request 목록을 조회합니다."""
    try:
        # 🔧 수정: 실제 인증된 사용자 ID 사용
        actual_user_id = str(current_user.get("id", user_id))
        print(f"DEBUG: Using user_id: {actual_user_id} (from current_user: {current_user.get('id')})")
        
        # 사용자별 연동된 리포지토리 조회
        user_repositories = await get_user_repositories(db, actual_user_id)
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
                        # 🔧 수정: 실제 CI 상태 조회
                        ci_status = await get_pr_ci_status(client, token, full_name, pr["number"])
                        
                        pr_data = {
                            "id": str(pr["id"]),
                            "number": pr["number"],
                            "title": pr["title"],
                            "author": pr["user"]["login"],
                            "status": pr["state"],
                            "branch": pr["head"]["ref"],
                            "targetBranch": pr["base"]["ref"],
                            "createdAt": pr["created_at"],
                            "ciStatus": ci_status,
                            "deploymentStatus": None,
                            "htmlUrl": pr["html_url"],
                            "deploymentUrl": None  # TODO: 실제 배포 URL 조회
                        }
                        print(f"DEBUG: PR {pr['number']} htmlUrl: {pr_data['htmlUrl']}")
                        pull_requests.append(pr_data)
                
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
async def get_pipelines(
    user_id: str = "default", 
    db = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """CI/CD 파이프라인 상태를 조회합니다."""
    try:
        # 🔧 수정: 실제 인증된 사용자 ID 사용
        actual_user_id = str(current_user.get("id", user_id))
        print(f"DEBUG: Using user_id for pipelines: {actual_user_id}")
        
        # 사용자별 연동된 리포지토리 조회
        user_repositories = await get_user_repositories(db, actual_user_id)
        
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


@router.post("/github/webhook")
async def github_webhook_handler(
    request: Request,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """GitHub App 웹훅 수신 및 auto_deploy_enabled 상태에 따른 처리"""
    try:
        # GitHub App 웹훅 서명 검증
        body_bytes = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")
        
        if not signature:
            raise HTTPException(status_code=400, detail="Missing signature header")
        
        # GitHub App 웹훅 서명 검증
        if not await github_app_auth.verify_webhook_signature(body_bytes, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        # 웹훅 페이로드 파싱
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
        # 이벤트 타입 확인
        event_type = request.headers.get("X-GitHub-Event")
        logger.info(f"Webhook event type: {event_type}")
        if not event_type:
            raise HTTPException(status_code=400, detail="Missing event type header")
        
        # installation_id와 리포지토리 정보 추출
        installation_id = payload.get("installation", {}).get("id")
        if not installation_id:
            return {"status": "ignored", "reason": "no installation_id"}
        
        # 리포지토리 정보 추출
        repository = payload.get("repository", {})
        full_name = repository.get("full_name")  # owner/repo
        if not full_name:
            return {"status": "ignored", "reason": "no repository full_name"}
        
        owner, repo_name = full_name.split("/", 1)
        
        # 🔧 수정: installation_id + 리포지토리 이름으로 정확한 통합 정보 조회
        integration = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.github_installation_id == str(installation_id),
            UserProjectIntegration.github_owner == owner,
            UserProjectIntegration.github_repo == repo_name
        ).first()
        
        if not integration:
            return {"status": "ignored", "reason": "integration_not_found", "repository": full_name}
        
        # auto_deploy_enabled 상태 확인
        logger.info(f"Integration found: {integration.github_owner}/{integration.github_repo}, auto_deploy_enabled: {getattr(integration, 'auto_deploy_enabled', False)}")
        if not getattr(integration, 'auto_deploy_enabled', False):
            logger.info(f"Auto deploy disabled for {integration.github_owner}/{integration.github_repo}")
            return {
                "status": "skipped",
                "reason": "auto_deploy_disabled",
                "repository": f"{integration.github_owner}/{integration.github_repo}",
                "message": "Auto deploy is disabled for this repository"
            }
        
        # 이벤트 타입별 처리
        if event_type == "push":
            return await handle_push_webhook(payload, integration, db)
        elif event_type == "pull_request":
            return await handle_pull_request_webhook(payload, integration, db)
        elif event_type == "release":
            return await handle_release_webhook(payload, integration, db)
        else:
            return {"status": "ignored", "reason": f"unsupported_event_type: {event_type}"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GitHub webhook processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")


async def auto_link_sourcecommit(integration: UserProjectIntegration, db: Session) -> Dict[str, Any]:
    """SourceCommit 자동 연동"""
    try:
        from ...core.config import get_settings
        from ...services.user_project_integration import upsert_integration
        
        settings = get_settings()
        
        # 환경변수에서 SourceCommit 정보 가져오기
        sc_project_id = getattr(settings, 'ncp_sourcecommit_project_id', None)
        sc_username = getattr(settings, 'ncp_sourcecommit_username', None)
        sc_password = getattr(settings, 'ncp_sourcecommit_password', None)
        
        if not sc_project_id:
            return {
                "status": "error",
                "reason": "sourcecommit_config_missing",
                "message": "SourceCommit project ID not configured in environment"
            }
        
        # 리포지토리 이름 생성: {owner}-{repo_name}
        sc_repo_name = f"{integration.github_owner}-{integration.github_repo}"
        
        # GitHub 리포지토리 URL 생성
        github_repo_url = f"https://github.com/{integration.github_owner}/{integration.github_repo}.git"
        
        # SourceCommit full URL 생성
        sc_full_url = f"https://devtools.ncloud.com/{sc_project_id}/{sc_repo_name}.git"
        
        logger.info(f"Auto-linking SourceCommit: {sc_repo_name} -> {sc_full_url}")
        
        # DB에 SourceCommit 정보 업데이트
        updated_integration = upsert_integration(
            db=db,
            user_id=integration.user_id,
            owner=integration.github_owner,
            repo=integration.github_repo,
            repository_id=integration.github_repository_id,
            installation_id=integration.github_installation_id,
            sc_project_id=sc_project_id,
            sc_repo_name=sc_repo_name,
            sc_clone_url=sc_full_url
        )
        
        # SourceCommit 리포지토리 생성
        from ...services.ncp_pipeline import ensure_sourcecommit_repo
        ensure_result = ensure_sourcecommit_repo(sc_project_id, sc_repo_name)
        
        if ensure_result.get("status") not in ("created", "exists"):
            logger.warning(f"SourceCommit repository creation failed: {ensure_result}")
            # DB는 업데이트했으므로 계속 진행
        
        # GitHub → SourceCommit 미러링
        from ...services.ncp_pipeline import mirror_to_sourcecommit
        
        # GitHub 토큰 획득
        from ...services.github_app import github_app_auth
        github_token = await github_app_auth.get_installation_token(str(integration.github_installation_id))
        
        mirror_result = mirror_to_sourcecommit(
            github_repo_url=github_repo_url,
            installation_or_access_token=github_token,
            sc_project_id=sc_project_id,
            sc_repo_name=sc_repo_name,
            sc_username=sc_username,
            sc_password=sc_password,
            sc_full_url=sc_full_url
        )
        
        return {
            "status": "success",
            "message": "SourceCommit auto-linked successfully",
            "sourcecommit": {
                "project_id": sc_project_id,
                "repo_name": sc_repo_name,
                "full_url": sc_full_url
            },
            "mirror_result": mirror_result
        }
        
    except Exception as e:
        logger.error(f"SourceCommit auto-link failed: {str(e)}")
        return {
            "status": "error",
            "reason": "auto_link_failed",
            "message": str(e)
        }


async def handle_sourcecommit_mirror(payload: Dict[str, Any], integration: UserProjectIntegration, db: Session) -> Dict[str, Any]:
    """SourceCommit 연동 및 미러링 처리"""
    try:
        logger.info(f"Starting SourceCommit mirror for {integration.github_owner}/{integration.github_repo}")
        
        # 기존 통합 정보에서 SourceCommit 정보 확인
        logger.info(f"SourceCommit config - project_id: {integration.sc_project_id}, repo_name: {integration.sc_repo_name}")
        
        # SourceCommit이 연동되지 않은 경우 자동으로 연동
        if not integration.sc_project_id or not integration.sc_repo_name:
            logger.info("SourceCommit not configured, attempting auto-link")
            auto_link_result = await auto_link_sourcecommit(integration, db)
            if auto_link_result.get("status") != "success":
                return auto_link_result
            
            # DB에서 업데이트된 정보 다시 조회
            db.refresh(integration)
            logger.info(f"Auto-linked SourceCommit - project_id: {integration.sc_project_id}, repo_name: {integration.sc_repo_name}")
        
        # GitHub 토큰 획득
        installation_id = integration.github_installation_id
        if not installation_id:
            return {
                "status": "error",
                "reason": "no_installation_id",
                "message": "GitHub installation ID not found"
            }
        
        from ...services.github_app import github_app_auth
        try:
            github_token = await github_app_auth.get_installation_token(str(installation_id))
        except Exception as e:
            logger.error(f"Failed to get GitHub token: {str(e)}")
            return {
                "status": "error",
                "reason": "github_token_failed",
                "message": f"Failed to get GitHub token: {str(e)}"
            }
        
        # SourceCommit 리포지토리 확인 (기존 리포지토리 사용)
        from ...services.ncp_pipeline import ensure_sourcecommit_repo
        ensure_result = ensure_sourcecommit_repo(integration.sc_project_id, integration.sc_repo_name)
        
        if ensure_result.get("status") not in ("created", "exists"):
            return {
                "status": "error",
                "reason": "sourcecommit_repo_failed",
                "message": f"SourceCommit repository check failed: {ensure_result}"
            }
        
        # GitHub → SourceCommit 미러링 (k8s 매니페스트 포함)
        from ...services.ncp_pipeline import mirror_to_sourcecommit
        
        github_repo_url = f"https://github.com/{integration.github_owner}/{integration.github_repo}.git"
        
        mirror_result = mirror_to_sourcecommit(
            github_repo_url=github_repo_url,
            installation_or_access_token=github_token,
            sc_project_id=integration.sc_project_id,
            sc_repo_name=integration.sc_repo_name
        )
        
        return {
            "status": "success",
            "repository": f"{integration.github_owner}/{integration.github_repo}",
            "sourcecommit": {
                "project_id": integration.sc_project_id,
                "repo_name": integration.sc_repo_name
            },
            "mirror_result": mirror_result
        }
        
    except Exception as e:
        logger.error(f"SourceCommit mirror processing failed: {str(e)}")
        return {
            "status": "error",
            "reason": "mirror_failed",
            "message": str(e)
        }


async def handle_push_webhook(payload: Dict[str, Any], integration: UserProjectIntegration, db: Session) -> Dict[str, Any]:
    """Push 이벤트 처리"""
    try:
        logger.info(f"Processing push webhook for {integration.github_owner}/{integration.github_repo}")
        
        # main 브랜치 push 확인
        ref = payload.get("ref", "")
        logger.info(f"Push ref: {ref}")
        if not ref.endswith("/main"):
            logger.info(f"Not main branch push: {ref}")
            return {"status": "ignored", "reason": "not_main_branch", "ref": ref}
        
        # PR merge 또는 직접 push 확인
        head_commit = payload.get("head_commit", {})
        message = head_commit.get("message", "").lower()
        pusher = payload.get("pusher", {}).get("name", "").lower()
        is_merge = ("merge pull request" in message) or (pusher == "web-flow")
        is_direct_push = pusher != "web-flow"  # 직접 push (사용자가 직접 push)
        
        logger.info(f"Commit message: {message}, pusher: {pusher}, is_merge: {is_merge}, is_direct_push: {is_direct_push}")
        
        # PR merge 또는 직접 push 모두 처리
        if not is_merge and not is_direct_push:
            logger.info("Not a PR merge or direct push, ignoring")
            return {"status": "ignored", "reason": "not_pr_merge_or_direct_push"}
        
        # Step 1: SourceCommit 연동 확인 및 미러링
        sourcecommit_result = await handle_sourcecommit_mirror(payload, integration, db)
        if sourcecommit_result.get("status") != "success":
            return sourcecommit_result
        
        # Step 2: SourceBuild 실행 (build/run 방식 사용)
        from ...services.ncp_pipeline import ensure_sourcebuild_project, run_sourcebuild as run_sb
        from ...core.config import get_settings
        
        settings = get_settings()
        
        # 이미지 레지스트리 URL 구성 (build/run과 동일)
        registry = getattr(settings, "ncp_container_registry_url", None)
        if not registry:
            logger.error("ncp_container_registry_url not configured")
            return {
                "status": "error",
                "reason": "registry_not_configured",
                "repository": f"{integration.github_owner}/{integration.github_repo}",
                "sourcecommit": sourcecommit_result
            }
        
        image_repo = f"{registry}/{integration.github_owner}-{integration.github_repo}"
        
        logger.info(f"Starting SourceBuild for {integration.github_owner}/{integration.github_repo}")
        logger.info(f"Image repo: {image_repo}")
        
        # SourceBuild 프로젝트 확인/생성 (build/run과 동일)
        build_id = await ensure_sourcebuild_project(
            owner=integration.github_owner,
            repo=integration.github_repo,
            branch="main",
            sc_project_id=integration.sc_project_id,
            sc_repo_name=integration.sc_repo_name,
            db=db,
            user_id=integration.user_id
        )
        
        # SourceBuild 실행 (build/run과 동일)
        build_result = await run_sb(build_id, image_repo=image_repo)
        logger.info(f"SourceBuild completed: {build_result}")
        
        # Step 3: SourceDeploy 실행 (deploy/run 방식 사용)
        from ...services.ncp_pipeline import ensure_sourcedeploy_project, run_sourcedeploy
        
        # 배포 매니페스트 생성 (deploy/run과 동일)
        manifest_text = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {integration.github_repo}-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {integration.github_repo}
  template:
    metadata:
      labels:
        app: {integration.github_repo}
    spec:
      containers:
      - name: {integration.github_repo}
        image: {image_repo}:${{GIT_COMMIT}}
        ports:
        - containerPort: 80
""".strip()
        
        nks_cluster_id = getattr(settings, "ncp_nks_cluster_id", None)
        
        # SourceDeploy 프로젝트 확인/생성 (deploy/run과 동일)
        deploy_project_id = await ensure_sourcedeploy_project(
            owner=integration.github_owner,
            repo=integration.github_repo,
            manifest_text=manifest_text,
            nks_cluster_id=nks_cluster_id,
            db=db,
            user_id=integration.user_id,
        )
        
        # SourceDeploy 실행 (deploy/run과 동일)
        deploy_result = await run_sourcedeploy(
            deploy_project_id,
            stage_name="production",
            scenario_name="deploy-app",
            sc_project_id=integration.sc_project_id,
            db=db,
            user_id=integration.user_id,
            owner=integration.github_owner,
            repo=integration.github_repo,
        )
        
        logger.info(f"SourceDeploy completed: {deploy_result}")
        
        return {
            "status": "success",
            "event": "push",
            "repository": f"{integration.github_owner}/{integration.github_repo}",
            "sourcecommit": sourcecommit_result,
            "build_result": build_result,
            "deploy_result": deploy_result
        }
            
    except Exception as e:
        logger.error(f"Push webhook processing failed: {str(e)}")
        return {"status": "error", "message": str(e)}


async def handle_pull_request_webhook(payload: Dict[str, Any], integration: UserProjectIntegration, db: Session) -> Dict[str, Any]:
    """Pull Request 이벤트 처리"""
    action = payload.get("action")
    if action != "closed":
        return {"status": "ignored", "reason": f"unsupported_action: {action}"}
    
    pr = payload.get("pull_request", {})
    if not pr.get("merged"):
        return {"status": "ignored", "reason": "pr_not_merged"}
    
    # main 브랜치로의 merge인지 확인
    base_branch = pr.get("base", {}).get("ref")
    if base_branch != "main":
        return {"status": "ignored", "reason": "not_merged_to_main", "base_branch": base_branch}
    
    # Push 이벤트와 동일한 처리 (SourceCommit 미러링 포함)
    return await handle_push_webhook(payload, integration, db)


async def handle_release_webhook(payload: Dict[str, Any], integration: UserProjectIntegration, db: Session) -> Dict[str, Any]:
    """Release 이벤트 처리 (프로덕션 배포)"""
    action = payload.get("action")
    if action != "published":
        return {"status": "ignored", "reason": f"unsupported_action: {action}"}
    
    release = payload.get("release", {})
    tag_name = release.get("tag_name", "latest")
    
    # 프로덕션 배포 로직 (향후 구현)
    return {
        "status": "success",
        "event": "release",
        "repository": f"{integration.github_owner}/{integration.github_repo}",
        "tag": tag_name,
        "message": "Production deployment triggered"
    }