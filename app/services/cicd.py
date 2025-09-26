import hmac
import hashlib
import json
import logging
from typing import Any, Dict
import time

from fastapi import HTTPException

from ..core.config import get_settings
from .github_contents import update_values_tag
from .deployments import DeployApplicationInput, perform_deploy
from .notify import slack_notify
from .github_app import github_app_auth
import structlog

logger = logging.getLogger(__name__)
log = structlog.get_logger(__name__)


def verify_github_signature(payload_bytes: bytes, signature_header: str | None) -> None:
    """GitHub 웹훅 서명 검증 (GitHub App 우선, 기존 방식 호환)"""
    settings = get_settings()
    
    # GitHub App 방식 우선 시도
    if settings.github_app_webhook_secret:
        if not signature_header:
            raise HTTPException(status_code=400, detail="Missing signature header")
        
        if not github_app_auth.verify_webhook_signature(payload_bytes, signature_header):
            raise HTTPException(status_code=401, detail="Invalid GitHub App signature")
        return
    
    # 기존 Personal Access Token 방식 (호환성)
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(status_code=400, detail="webhook secret not configured")
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="invalid signature header")
    signature = signature_header.split("=", 1)[1]
    mac = hmac.new(secret.encode(), msg=payload_bytes, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="signature mismatch")


def verify_staging_signature(payload_bytes: bytes, signature: str | None, timestamp: str | None) -> None:
    """Generic HMAC-SHA256 webhook signature verification with timestamp replay window."""
    settings = get_settings()
    secret = settings.staging_webhook_secret
    if not secret:
        raise HTTPException(status_code=400, detail="staging webhook secret not configured")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="invalid signature header")
    if not timestamp:
        raise HTTPException(status_code=401, detail="missing timestamp header")
    try:
        ts = int(timestamp)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid timestamp header")
    if abs(int(time.time() * 1000) - ts) > 5 * 60 * 1000:
        raise HTTPException(status_code=401, detail="timestamp out of window")
    mac = hmac.new(secret.encode(), msg=payload_bytes + timestamp.encode(), digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    provided = signature.split("=", 1)[1]
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="signature mismatch")


async def handle_push_event(event: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    ref = event.get("ref", "")
    branch = ref.split("/")[-1] if ref else ""
    if branch != (settings.github_branch_main or "main"):
        return {"status": "ignored", "reason": "not main branch", "branch": branch}

    # Prevent infinite loop: ignore pushes from deployment-config repository
    try:
        repo_full_name = (event.get("repository") or {}).get("full_name") or ""
    except Exception:
        repo_full_name = ""
    deployment_config_repo = getattr(settings, "deployment_config_repo", None) or settings.model_extra.get("deployment_config_repo") or "K-Le-PaaS/deployment-config"
    if repo_full_name.lower() == str(deployment_config_repo).lower():
        return {"status": "ignored", "reason": "deployment-config repo push"}

    # Gate updates to workflow success to avoid racing ArgoCD before image exists
    return {"status": "ignored", "reason": "awaiting workflow success"}

    # Enforce PR-merge-only deploys if configured
    if settings.require_pr_merge:
        head = event.get("head_commit") or {}
        message = (head.get("message") or "").lower()
        pusher = (event.get("pusher") or {}).get("name", "").lower()
        is_merge = ("merge pull request" in message) or (pusher == "web-flow")
        if not is_merge:
            return {"status": "ignored", "reason": "not a PR merge commit"}

    repo = event.get("repository", {}).get("name", "app")
    owner = event.get("repository", {}).get("owner", {}).get("name") or event.get("organization", {}).get("login") or ""
    commit = (event.get("after") or "")[:7] or "latest"

    # 1) deployment-config values tag 업데이트
    try:
        await update_values_tag(owner=owner, repo=repo, tag=f"{commit}")
    except Exception as e:
        logger.error("Failed to update deployment-config values", extra={"error": str(e), "owner": owner, "repo": repo, "tag": commit})

    # 2) (옵션) 내부 배포 트리거 유지 가능
    image = f"{repo}:{commit}"
    payload = DeployApplicationInput(
        app_name=repo,
        environment="staging",
        image=image,
        replicas=2,
    )
    try:
        if settings.mcp_git_agent_enabled:
            from ..mcp.tools.git_deployment import git_deployment_tools
            # 클라우드 프로바이더 자동 감지 또는 설정에서 가져오기
            cloud_provider = getattr(settings, 'mcp_default_cloud_provider', 'gcp')
            
            mcp_result = await git_deployment_tools._deploy_application_mcp({
                "app_name": payload.app_name,
                "environment": payload.environment,
                "image": payload.image,
                "replicas": payload.replicas,
                "cloud_provider": cloud_provider
            })
            
            if mcp_result.get("status") == "success":
                result = mcp_result
                log.info("mcp_git_agent_deploy_success", result=mcp_result)
            else:
                # MCP 실패 시 기존 방식으로 폴백
                result = await perform_deploy(payload)
                log.warning("mcp_git_agent_deploy_failed_fallback", 
                           mcp_error=mcp_result.get("error"), fallback_result=result)
        else:
            # 기존 직접 배포 방식
            result = await perform_deploy(payload)
    except Exception as e:
        log.warning("mcp_git_agent_deploy_error_fallback", error=str(e))
        # MCP 에이전트 실패 시 기존 방식으로 폴백
        result = await perform_deploy(payload)
    
    # 레거시 MCP 트리거 (호환성)
    try:
        if settings.mcp_trigger_provider:
            from ..mcp.external.registry import mcp_registry
            provider = settings.mcp_trigger_provider
            tool = settings.mcp_trigger_tool or "deploy_application"
            args = {
                "app_name": payload.app_name,
                "environment": payload.environment,
                "image": payload.image,
                "replicas": payload.replicas,
            }
            # fire and forget best-effort
            import asyncio
            asyncio.create_task(mcp_registry.call_tool(provider, tool, args))
    except Exception as e:
        log.warning("mcp_trigger_failed", error=str(e))
    try:
        # fire-and-forget
        import asyncio
        asyncio.create_task(slack_notify(f"[Staging] Deploy triggered: {repo}:{commit}"))
    except Exception as e:
        logger.error("Failed to send Slack notification for staging deploy", extra={"error": str(e), "repo": repo, "commit": commit})
    return {"status": "triggered", "deploy": result}


async def handle_release_event(event: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    action = event.get("action")
    if action != "published":
        return {"status": "ignored", "reason": f"unsupported release action {action}"}

    repo = event.get("repository", {}).get("name", "app")
    tag = (event.get("release") or {}).get("tag_name") or "latest"
    image = f"{repo}:{tag}"

    payload = DeployApplicationInput(
        app_name=repo,
        environment="production",
        image=image,
        replicas=2,
    )
    result = await perform_deploy(payload)
    try:
        import asyncio
        asyncio.create_task(slack_notify(f"[Production] Release deploy triggered: {repo}:{tag}"))
    except Exception as e:
        logger.error("Failed to send Slack notification for production release", extra={"error": str(e), "repo": repo, "tag": tag})
    return {"status": "triggered", "environment": "production", "deploy": result}


async def handle_workflow_run_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle GitHub 'workflow_run' events.

    We update deployment-config only when the run is completed successfully
    on the main branch, preventing premature updates on initial push.
    """
    settings = get_settings()
    run = event.get("workflow_run") or {}
    status = (run.get("status") or "").lower()
    conclusion = (run.get("conclusion") or "").lower()
    branch = (run.get("head_branch") or "")
    sha = (run.get("head_sha") or "")

    # Ensure success on target branch
    if status != "completed" or conclusion != "success":
        return {"status": "ignored", "reason": f"run {status}/{conclusion}"}
    if branch != (settings.github_branch_main or "main"):
        return {"status": "ignored", "reason": "not main branch", "branch": branch}

    # Prevent loop for deployment-config repo
    repo = (event.get("repository") or {})
    repo_full_name = (repo.get("full_name") or "").lower()
    deployment_config_repo = (getattr(settings, "deployment_config_repo", None) or settings.model_extra.get("deployment_config_repo") or "K-Le-PaaS/deployment-config").lower()
    if repo_full_name == deployment_config_repo:
        return {"status": "ignored", "reason": "deployment-config repo run"}

    service_repo = repo.get("name", "app")
    owner = (repo.get("owner") or {}).get("login") or (event.get("organization") or {}).get("login") or ""
    short = sha[:7] if sha else "latest"

    # 1) Update deployment-config values tag now that image should exist
    try:
        await update_values_tag(owner=owner, repo=service_repo, tag=f"{short}")
    except Exception as e:
        logger.error("Failed to update deployment-config values on workflow success", extra={"error": str(e), "owner": owner, "repo": service_repo, "tag": short})

    # 2) Optional deploy trigger using same flow as push
    image = f"{service_repo}:{short}"
    payload = DeployApplicationInput(
        app_name=service_repo,
        environment="staging",
        image=image,
        replicas=2,
    )
    try:
        if settings.mcp_git_agent_enabled:
            from ..mcp.tools.git_deployment import git_deployment_tools
            cloud_provider = getattr(settings, 'mcp_default_cloud_provider', 'gcp')
            mcp_result = await git_deployment_tools._deploy_application_mcp({
                "app_name": payload.app_name,
                "environment": payload.environment,
                "image": payload.image,
                "replicas": payload.replicas,
                "cloud_provider": cloud_provider
            })
            if mcp_result.get("status") == "success":
                result = mcp_result
                log.info("mcp_git_agent_deploy_success", result=mcp_result)
            else:
                result = await perform_deploy(payload)
                log.warning("mcp_git_agent_deploy_failed_fallback", mcp_error=mcp_result.get("error"), fallback_result=result)
        else:
            result = await perform_deploy(payload)
    except Exception as e:
        log.warning("mcp_git_agent_deploy_error_fallback", error=str(e))
        result = await perform_deploy(payload)

    # Notifications
    try:
        import asyncio
        asyncio.create_task(slack_notify(f"[Staging] Deploy triggered after workflow success: {service_repo}:{short}"))
    except Exception:
        pass

    return {"status": "triggered", "source": "workflow_run", "deploy": result}


