import json
from typing import Any, Dict

from fastapi import APIRouter, Header, Request
import structlog

from ...services.cicd import verify_github_signature, handle_push_event, handle_release_event
from ...services.github_app import github_app_auth


router = APIRouter()
log = structlog.get_logger(__name__)


@router.post("/cicd/webhook", response_model=dict)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> Dict[str, Any]:
    raw = await request.body()
    verify_github_signature(raw, x_hub_signature_256)
    event = json.loads(raw)

    if x_github_event == "push":
        return handle_push_event(event)
    if x_github_event == "release":
        return handle_release_event(event)

    return {"status": "ignored", "reason": f"unsupported event {x_github_event}"}
@router.post("/cicd/staging-webhook", response_model=dict)
async def staging_webhook(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_signature_timestamp: str | None = Header(default=None, alias="X-Signature-Timestamp"),
) -> Dict[str, Any]:
    raw = await request.body()
    from ...services.cicd import verify_staging_signature

    verify_staging_signature(raw, x_signature, x_signature_timestamp)
    event = json.loads(raw)
    # basic structured log
    log.info(
        "staging_webhook_received",
        event=event.get("event"),
        app=event.get("app"),
        env=event.get("env"),
        version=event.get("version"),
    )
    return {"status": "received"}


@router.get("/github/app/installations", response_model=dict)
async def get_github_app_installations() -> Dict[str, Any]:
    """GitHub App 설치 목록 조회"""
    try:
        installations = await github_app_auth.get_app_installations()
        return {"status": "success", "installations": installations}
    except ValueError as e:
        return {"status": "error", "message": f"Invalid request: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Internal error: {e}"}


@router.post("/github/app/installations/{installation_id}/token", response_model=dict)
async def get_installation_token(installation_id: str) -> Dict[str, Any]:
    """GitHub App 설치 토큰 조회"""
    try:
        token = await github_app_auth.get_installation_token(installation_id)
        return {"status": "success", "token": token}
    except ValueError as e:
        return {"status": "error", "message": f"Invalid request: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Internal error: {e}"}


