import hmac
import hashlib
import json
import logging
from typing import Any, Dict
import time

from fastapi import HTTPException

from ..core.config import get_settings
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

    # Enforce PR-merge-only deploys on protected branch (best-effort)
    head = event.get("head_commit") or {}
    message = (head.get("message") or "").lower()
    pusher = (event.get("pusher") or {}).get("name", "").lower()
    is_merge = ("merge pull request" in message) or (pusher == "web-flow")
    if not is_merge:
        return {"status": "ignored", "reason": "not a PR merge commit"}

    # 🔧 추가: auto_deploy_enabled 상태 확인
    # GitHub App installation_id로 사용자 설정 조회
    installation_id = event.get("installation", {}).get("id")
    if installation_id:
        try:
            from ..database import SessionLocal
            from ..models.user_project_integration import UserProjectIntegration
            
            db = SessionLocal()
            try:
                # installation_id로 통합 정보 조회
                integration = db.query(UserProjectIntegration).filter(
                    UserProjectIntegration.github_installation_id == str(installation_id)
                ).first()
                
                if integration and not getattr(integration, 'auto_deploy_enabled', False):
                    return {
                        "status": "skipped", 
                        "reason": "auto_deploy_disabled",
                        "repository": event.get("repository", {}).get("full_name", "unknown"),
                        "message": "Auto deploy is disabled for this repository"
                    }
            finally:
                db.close()
        except Exception as e:
            log.warning("Failed to check auto_deploy_enabled status", error=str(e))
            # DB 조회 실패 시에도 배포는 진행 (기존 동작 유지)

    repo = event.get("repository", {}).get("name", "app")
    # simplistic image tag using commit sha short
    commit = (event.get("after") or "")[:7] or "latest"
    image = f"{repo}:{commit}"
    payload = DeployApplicationInput(
        app_name=repo,
        environment="staging",
        image=image,
        replicas=2,
    )
    # MCP 네이티브 Git 에이전트를 통한 배포 (우선순위)
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
                result = perform_deploy(payload)
                log.warning("mcp_git_agent_deploy_failed_fallback", 
                           mcp_error=mcp_result.get("error"), fallback_result=result)
        else:
            # 기존 직접 배포 방식
            result = perform_deploy(payload)
    except Exception as e:
        log.warning("mcp_git_agent_deploy_error_fallback", error=str(e))
        # MCP 에이전트 실패 시 기존 방식으로 폴백
        result = perform_deploy(payload)
    
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
    result = perform_deploy(payload)
    try:
        import asyncio
        asyncio.create_task(slack_notify(f"[Production] Release deploy triggered: {repo}:{tag}"))
    except Exception as e:
        logger.error("Failed to send Slack notification for production release", extra={"error": str(e), "repo": repo, "tag": tag})
    return {"status": "triggered", "environment": "production", "deploy": result}


