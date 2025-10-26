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
from .notification import SlackNotificationService
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

    # Check auto_deploy_enabled status and pipeline configuration
    # GitHub App installation_id for user settings lookup
    installation_id = event.get("installation", {}).get("id")
    integration = None
    
    if installation_id:
        try:
            from ..database import SessionLocal
            from ..models.user_project_integration import UserProjectIntegration
            
            db = SessionLocal()
            try:
                # Query integration by installation_id
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
            # Continue deployment even if DB check fails (preserve existing behavior)

    repo_data = event.get("repository", {})
    repo = repo_data.get("name", "app")
    owner = repo_data.get("owner", {}).get("login", "")
    commit_sha = event.get("after") or ""
    commit = commit_sha[:7] or "latest"

    # 커밋 정보 추출
    head_commit = event.get("head_commit") or {}
    commit_message = head_commit.get("message", "No commit message")
    commit_author = head_commit.get("author", {}).get("name", "Unknown")
    
    # Pipeline mode: Auto-create and use SourcePipeline if build/deploy projects exist
    if integration:
        try:
            from .ncp_pipeline import ensure_sourcepipeline_project, execute_sourcepipeline_rest
            from ..database import SessionLocal
            
            pipeline_id = getattr(integration, 'pipeline_id', None)
            build_project_id = getattr(integration, 'build_project_id', None)
            deploy_project_id = getattr(integration, 'deploy_project_id', None)
            
            # Auto-create pipeline if build and deploy projects exist but pipeline doesn't
            if not pipeline_id and build_project_id and deploy_project_id:
                log.info("auto_creating_pipeline", 
                        repository=f"{owner}/{repo}", 
                        build_id=build_project_id, 
                        deploy_id=deploy_project_id)
                
                db = SessionLocal()
                try:
                    # Create pipeline with existing build/deploy projects
                    pipeline_id = await ensure_sourcepipeline_project(
                        owner=owner,
                        repo=repo,
                        build_project_id=str(build_project_id),
                        deploy_project_id=str(deploy_project_id),
                        deploy_stage_id=1,
                        deploy_scenario_id=1,
                        branch=branch,
                        sc_repo_name=getattr(integration, 'sc_repo_name', None),
                        db=db,
                        user_id=getattr(integration, 'user_id', None)
                    )
                    log.info("pipeline_auto_created", 
                            pipeline_id=pipeline_id, 
                            repository=f"{owner}/{repo}")
                finally:
                    db.close()
            
            # Execute pipeline if available
            if pipeline_id:
                log.info("pipeline_mode_enabled", repository=repo, pipeline_id=pipeline_id)
                
                # Execute SourcePipeline (Build -> Deploy workflow)
                pipeline_result = await execute_sourcepipeline_rest(pipeline_id)
                
                # Send Slack notification for pipeline execution
                try:
                    import asyncio
                    notification_msg = (
                        f"[SourcePipeline] Execution triggered for {repo}:{commit}\n"
                        f"Pipeline ID: {pipeline_id}\n"
                        f"History ID: {pipeline_result.get('history_id', 'N/A')}"
                    )
                    asyncio.create_task(slack_notify(notification_msg))
                except Exception as slack_error:
                    logger.error("Failed to send pipeline Slack notification", 
                               extra={"error": str(slack_error), "repo": repo, "pipeline_id": pipeline_id})
                
                return {
                    "status": "pipeline_triggered",
                    "mode": "sourcepipeline",
                    "pipeline_id": pipeline_id,
                    "history_id": pipeline_result.get("history_id"),
                    "repository": repo,
                    "commit": commit
                }
                
        except Exception as pipeline_error:
            log.warning("pipeline_execution_failed_fallback_to_direct_deploy", 
                       error=str(pipeline_error), repository=repo)
            # Fallback to direct deployment if pipeline execution fails
            # Continue to standard deployment logic below
    
    # 배포 히스토리 기록 생성 (deployment_id 획득용)
    deployment_record = None
    try:
        from ..database import SessionLocal
        from ..models.deployment_history import DeploymentHistory

        db = SessionLocal()
        try:
            deployment_record = DeploymentHistory(
                user_id=getattr(integration, 'user_id', 'system') if integration else 'system',
                github_owner=owner,
                github_repo=repo,
                github_commit_sha=commit_sha,
                github_commit_message=commit_message,
                github_commit_author=commit_author,
                status="running",
                image_tag=commit,
                operation_type="deploy"
            )
            db.add(deployment_record)
            db.commit()
            db.refresh(deployment_record)
            log.info("deployment_record_created", deployment_id=deployment_record.id)
        finally:
            db.close()
    except Exception as e:
        log.warning("failed_to_create_deployment_record", error=str(e))

    # 배포 시작 슬랙 알림 (터미널 스타일)
    if settings.slack_webhook_url and deployment_record:
        try:
            notifier = SlackNotificationService(settings.slack_webhook_url)
            notifier.send_deployment_started(
                repo=f"{owner}/{repo}",
                commit_sha=commit_sha,
                commit_message=commit_message,
                author=commit_author,
                deployment_id=deployment_record.id,
                branch=branch
            )
        except Exception as e:
            log.warning("failed_to_send_deployment_started_notification", error=str(e))

    # Standard direct deployment mode (existing logic)
    image = f"{repo}:{commit}"
    payload = DeployApplicationInput(
        app_name=repo,
        environment="staging",
        image=image,
        replicas=2,
    )
    
    # MCP native Git agent deployment (priority)
    try:
        if settings.mcp_git_agent_enabled:
            from ..mcp.tools.git_deployment import git_deployment_tools
            # Auto-detect cloud provider or get from settings
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
                # Fallback to standard deployment on MCP failure
                result = perform_deploy(payload)
                log.warning("mcp_git_agent_deploy_failed_fallback", 
                           mcp_error=mcp_result.get("error"), fallback_result=result)
        else:
            # Standard direct deployment
            result = perform_deploy(payload)
    except Exception as e:
        log.warning("mcp_git_agent_deploy_error_fallback", error=str(e))
        # Fallback to standard deployment on MCP agent error
        result = perform_deploy(payload)
    
    # Legacy MCP trigger (compatibility)
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
        
    # 배포 완료 후 히스토리 업데이트 및 알림
    if deployment_record:
        try:
            from ..database import SessionLocal
            from datetime import datetime, timezone

            db = SessionLocal()
            try:
                # 배포 결과에 따라 상태 업데이트
                deployment_record.status = "success" if result.get("status") == "success" else "failed"
                deployment_record.completed_at = datetime.now(timezone.utc)
                deployment_record.calculate_duration()

                if deployment_record.status == "failed":
                    deployment_record.error_message = result.get("message", "Deployment failed")

                db.commit()
                db.refresh(deployment_record)

                # 배포 완료 슬랙 알림 (터미널 스타일)
                if settings.slack_webhook_url:
                    notifier = SlackNotificationService(settings.slack_webhook_url)

                    if deployment_record.is_success:
                        notifier.send_deployment_success(
                            repo=f"{owner}/{repo}",
                            commit_sha=commit_sha,
                            commit_message=commit_message,
                            author=commit_author,
                            deployment_id=deployment_record.id,
                            duration_seconds=deployment_record.total_duration or 0,
                            branch=branch,
                            app_url=result.get("app_url")
                        )
                    else:
                        notifier.send_deployment_failed(
                            repo=f"{owner}/{repo}",
                            commit_sha=commit_sha,
                            commit_message=commit_message,
                            author=commit_author,
                            deployment_id=deployment_record.id,
                            duration_seconds=deployment_record.total_duration or 0,
                            error_message=deployment_record.error_message or "Unknown error",
                            branch=branch
                        )
            finally:
                db.close()
        except Exception as e:
            log.warning("failed_to_update_deployment_record_or_send_notification", error=str(e))

    return {"status": "triggered", "deploy": result}


async def handle_release_event(event: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    action = event.get("action")
    if action != "published":
        return {"status": "ignored", "reason": f"unsupported release action {action}"}

    repo_data = event.get("repository", {})
    repo = repo_data.get("name", "app")
    owner = repo_data.get("owner", {}).get("login", "")
    release = event.get("release") or {}
    tag = release.get("tag_name") or "latest"
    release_name = release.get("name", tag)
    release_body = release.get("body", "No release notes")
    release_author = release.get("author", {}).get("login", "Unknown")

    # 배포 히스토리 기록 생성
    deployment_record = None
    try:
        from ..database import SessionLocal
        from ..models.deployment_history import DeploymentHistory

        db = SessionLocal()
        try:
            deployment_record = DeploymentHistory(
                user_id='system',
                github_owner=owner,
                github_repo=repo,
                github_commit_message=f"Release {release_name}: {release_body}",
                github_commit_author=release_author,
                status="running",
                image_tag=tag,
                operation_type="deploy"
            )
            db.add(deployment_record)
            db.commit()
            db.refresh(deployment_record)
            log.info("release_deployment_record_created", deployment_id=deployment_record.id)
        finally:
            db.close()
    except Exception as e:
        log.warning("failed_to_create_release_deployment_record", error=str(e))

    # 배포 시작 슬랙 알림 (터미널 스타일)
    if settings.slack_webhook_url and deployment_record:
        try:
            notifier = SlackNotificationService(settings.slack_webhook_url)
            notifier.send_deployment_started(
                repo=f"{owner}/{repo}",
                commit_sha=tag,  # 릴리스는 태그 사용
                commit_message=f"Release {release_name}",
                author=release_author,
                deployment_id=deployment_record.id,
                branch="production"
            )
        except Exception as e:
            log.warning("failed_to_send_release_started_notification", error=str(e))

    image = f"{repo}:{tag}"
    payload = DeployApplicationInput(
        app_name=repo,
        environment="production",
        image=image,
        replicas=2,
    )
    result = perform_deploy(payload)

    # 배포 완료 후 히스토리 업데이트 및 알림
    if deployment_record:
        try:
            from ..database import SessionLocal
            from datetime import datetime, timezone

            db = SessionLocal()
            try:
                deployment_record.status = "success" if result.get("status") == "success" else "failed"
                deployment_record.completed_at = datetime.now(timezone.utc)
                deployment_record.calculate_duration()

                if deployment_record.status == "failed":
                    deployment_record.error_message = result.get("message", "Deployment failed")

                db.commit()
                db.refresh(deployment_record)

                # 배포 완료 슬랙 알림 (터미널 스타일)
                if settings.slack_webhook_url:
                    notifier = SlackNotificationService(settings.slack_webhook_url)

                    if deployment_record.is_success:
                        notifier.send_deployment_success(
                            repo=f"{owner}/{repo}",
                            commit_sha=tag,
                            commit_message=f"Release {release_name}",
                            author=release_author,
                            deployment_id=deployment_record.id,
                            duration_seconds=deployment_record.total_duration or 0,
                            branch="production",
                            app_url=result.get("app_url")
                        )
                    else:
                        notifier.send_deployment_failed(
                            repo=f"{owner}/{repo}",
                            commit_sha=tag,
                            commit_message=f"Release {release_name}",
                            author=release_author,
                            deployment_id=deployment_record.id,
                            duration_seconds=deployment_record.total_duration or 0,
                            error_message=deployment_record.error_message or "Unknown error",
                            branch="production"
                        )
            finally:
                db.close()
        except Exception as e:
            log.warning("failed_to_update_release_deployment_record_or_send_notification", error=str(e))

    return {"status": "triggered", "environment": "production", "deploy": result}


