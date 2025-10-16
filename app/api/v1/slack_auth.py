"""
Slack OAuth 2.0 인증 API
사용자가 쉽게 Slack을 연동할 수 있도록 도와주는 API
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from typing import Optional, Dict, Any
import httpx
import secrets
import asyncio
from urllib.parse import urlencode

from ...core.config import get_settings
from ...services.slack_oauth import SlackOAuthService
from ...database import get_db
from sqlalchemy.orm import Session
from ...services.user_slack_config_service import (
    upsert_user_slack_config,
    get_user_slack_config,
    to_public_dict,
)
from ..v1.auth_verify import get_current_user

router = APIRouter(prefix="/slack", tags=["slack-auth"])


@router.get("/auth/url")
async def get_slack_auth_url(
    redirect_uri: Optional[str] = Query(None, description="인증 후 리다이렉트할 URI(미제공 시 서버 설정값 사용)"),
    state: Optional[str] = None,
    current_user: dict | None = Depends(get_current_user)
):
    """
    Slack OAuth 인증 URL을 생성합니다.
    사용자가 이 URL을 클릭하면 Slack 인증 페이지로 이동합니다.
    """
    settings = get_settings()
    
    # 상태 토큰 생성 (CSRF 보호)
    if not state:
        # 로그인된 사용자가 있으면 state에 사용자 식별자를 포함하여 콜백에서 자동 저장을 가능하게 함
        user_part = f"uid:{str(current_user['id'])}:" if (current_user and current_user.get('id')) else ""
        state = user_part + secrets.token_urlsafe(24)
    
    # Slack OAuth URL 생성
    # redirect_uri가 없으면 서버 설정(KLEPAAS_SLACK_REDIRECT_URI) 사용
    effective_redirect_uri = redirect_uri or settings.slack_redirect_uri
    if not effective_redirect_uri:
        raise HTTPException(status_code=500, detail="Slack redirect_uri not configured")
    auth_params = {
        "client_id": settings.slack_client_id,
        "scope": "chat:write,channels:read,users:read,team:read",
        "redirect_uri": effective_redirect_uri,
        "state": state,
        "response_type": "code"
    }
    
    auth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(auth_params)}"
    
    return {
        "auth_url": auth_url,
        "state": state,
        "message": "이 URL을 클릭하여 Slack 인증을 진행하세요."
    }


@router.get("/auth/callback")
async def handle_slack_callback(
    code: str = Query(..., description="Slack에서 받은 인증 코드"),
    state: Optional[str] = Query(None, description="상태 토큰(옵션)"),
    error: Optional[str] = Query(None, description="에러 메시지"),
    db: Session = Depends(get_db)
):
    """
    Slack OAuth 콜백을 처리합니다.
    인증 코드를 받아서 액세스 토큰을 교환합니다.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Slack 인증 실패: {error}")
    
    try:
        oauth_service = SlackOAuthService()
        
        # 인증 코드를 액세스 토큰으로 교환
        token_response = await oauth_service.exchange_code_for_token(code)
        
        if not token_response.success:
            raise HTTPException(
                status_code=400, 
                detail=f"토큰 교환 실패: {token_response.error}"
            )
        
        # 사용자/워크스페이스 정보 조회 (참고: auth.test는 봇 토큰 기준의 bot user id를 반환)
        user_info = await oauth_service.get_user_info(token_response.access_token)

        # state가 uid:<user_id>:... 형태면 해당 사용자로 즉시 저장 (UX 단축)
        user_id_from_state: Optional[str] = None
        if state and state.startswith("uid:"):
            try:
                user_id_from_state = state.split(":", 2)[1]
            except Exception:
                user_id_from_state = None

        if user_id_from_state:
            try:
                upsert_user_slack_config(
                    db,
                    user_id=user_id_from_state,
                    integration_type="oauth",
                    access_token=token_response.access_token,
                    dm_enabled=True,
                    # DM 대상은 사람 계정(authed_user)이어야 하므로 토큰 교환 응답의 user_id 사용
                    dm_user_id=token_response.user_id,
                    # 기본 채널은 비워두고, 프론트에서 추후 업데이트 가능
                )
            except Exception:
                # 저장 실패는 무시하고 계속 응답
                pass

        # 성공 시 프론트로 리다이렉트 (?slack=connected)
        settings = get_settings()
        frontend = settings.frontend_base_url or "http://localhost:3000/console"
        # Build URL safely and append slack=connected regardless of path
        try:
            from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl
            parsed = urlparse(frontend)
            query = dict(parse_qsl(parsed.query))
            query["slack"] = "connected"
            target = urlunparse(parsed._replace(query=urlencode(query)))
        except Exception:
            target = f"{frontend}?slack=connected"
        return RedirectResponse(target, status_code=302)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Slack 연동 중 오류 발생: {str(e)}")


@router.post("/test")
async def test_slack_connection(
    access_token: str = Query(..., description="Slack 액세스 토큰"),
    channel: str = Query("#general", description="테스트 메시지를 보낼 채널")
):
    """
    Slack 연동을 테스트합니다.
    지정된 채널에 테스트 메시지를 전송합니다.
    """
    try:
        oauth_service = SlackOAuthService()
        
        # 테스트 메시지 전송
        result = await oauth_service.send_test_message(
            access_token=access_token,
            channel=channel
        )
        
        if result.success:
            return {
                "success": True,
                "message": f"{channel}에 테스트 메시지가 전송되었습니다!",
                "message_ts": result.message_ts
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=f"테스트 메시지 전송 실패: {result.error}"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"테스트 중 오류 발생: {str(e)}")


@router.get("/channels")
async def get_slack_channels(
    access_token: Optional[str] = Query(None, description="Slack 액세스 토큰 (미제공 시 서버 저장값 사용)"),
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_current_user)
):
    """
    사용자가 접근 가능한 Slack 채널 목록을 조회합니다.
    """
    try:
        oauth_service = SlackOAuthService()

        token_to_use = access_token
        if not token_to_use and current_user and current_user.get("id"):
            cfg = get_user_slack_config(db, str(current_user["id"]))
            if cfg and cfg.integration_type == "oauth" and cfg.access_token:
                token_to_use = cfg.access_token
        if not token_to_use:
            raise HTTPException(status_code=400, detail="Slack 토큰이 필요합니다.")

        channels = await oauth_service.get_available_channels(token_to_use)
        
        return {
            "success": True,
            "channels": channels
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채널 목록 조회 중 오류 발생: {str(e)}")


@router.post("/save-config")
async def save_slack_config(
    access_token: Optional[str] = Query(None, description="Slack 액세스 토큰(OAuth 사용 시)"),
    default_channel: str = Query("#general", description="기본 알림 채널"),
    deployment_channel: str = Query("#deployments", description="배포 알림 채널"),
    error_channel: str = Query("#alerts", description="에러 알림 채널"),
    webhook_url: Optional[str] = Query(None, description="Incoming Webhook URL(웹훅 사용 시)"),
    dm_enabled: bool = Query(True, description="개인 DM 기본 사용 여부"),
    dm_user_id: Optional[str] = Query(None, description="개인 DM 수신자 Slack 사용자 ID (없으면 인증 사용자)"),
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_current_user)
):
    """
    Slack 설정을 저장합니다.
    """
    try:
        if not current_user or not current_user.get("id"):
            raise HTTPException(status_code=401, detail="인증된 사용자가 필요합니다.")
        user_id = str(current_user["id"])
        cfg = upsert_user_slack_config(
            db,
            user_id=user_id,
            integration_type="oauth" if access_token else "webhook",
            access_token=access_token,
            webhook_url=webhook_url,
            default_channel=default_channel,
            deployment_channel=deployment_channel,
            error_channel=error_channel,
            dm_enabled=dm_enabled,
            dm_user_id=dm_user_id or None,
        )

        return {
            "success": True,
            "message": "Slack 설정이 저장되었습니다!",
            "config": to_public_dict(cfg)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"설정 저장 중 오류 발생: {str(e)}")

@router.post("/test-with-config")
async def test_with_config(
    message: str = Query("K-Le-PaaS Slack 테스트", description="전송할 메시지"),
    channel: Optional[str] = Query(None, description="지정 시 이 채널로 전송, 미지정 시 저장된 기본 채널 사용"),
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_current_user)
):
    """
    저장된 사용자 Slack 설정을 사용해 테스트 메시지를 전송합니다.
    OAuth이면 chat.postMessage, Webhook이면 Incoming Webhook으로 전송합니다.
    """
    if not current_user or not current_user.get("id"):
        raise HTTPException(status_code=401, detail="인증된 사용자가 필요합니다.")

    cfg = get_user_slack_config(db, str(current_user["id"]))
    if not cfg:
        raise HTTPException(status_code=404, detail="저장된 Slack 설정이 없습니다.")

    target_channel = channel or cfg.deployment_channel or cfg.default_channel or "#general"

    # 우선순위: webhook > oauth
    if cfg.integration_type == "webhook" and cfg.webhook_url and not cfg.dm_enabled:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(cfg.webhook_url, json={"text": message, "channel": target_channel})
                if resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Webhook 전송 실패: {resp.status_code}")
            return {"success": True, "via": "webhook", "channel": target_channel}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Webhook 전송 오류: {str(e)}")

    if cfg.integration_type == "oauth" and cfg.access_token:
        svc = SlackOAuthService()
        # DM 우선 경로
        if cfg.dm_enabled and cfg.dm_user_id:
            result = await svc.send_dm(
                access_token=cfg.access_token,
                user_id=cfg.dm_user_id,
                title="K-Le-PaaS",
                message=message,
            )
        else:
            result = await svc.send_notification(
                access_token=cfg.access_token,
                channel=target_channel,
                title="K-Le-PaaS",
                message=message,
            )
        if result.success:
            return {"success": True, "via": "oauth", "channel": target_channel, "message_ts": result.message_ts}
        raise HTTPException(status_code=400, detail=f"OAuth 전송 실패: {result.error}")

    raise HTTPException(status_code=400, detail="유효한 Slack 설정이 없습니다.")


@router.get("/status")
async def get_slack_status(
    db: Session = Depends(get_db),
    current_user: dict | None = Depends(get_current_user)
) -> Dict[str, Any]:
    """현재 사용자 Slack 연동 상태를 반환합니다.

    connected: 설정이 존재하고(access_token 또는 webhook_url) DM 또는 채널 어느 하나라도 전송 경로가 유효하면 true
    details: 일부 설정 값(민감정보 제외)
    """
    if not current_user or not current_user.get("id"):
        return {"connected": False}

    cfg = get_user_slack_config(db, str(current_user["id"]))
    if not cfg:
        return {"connected": False}

    connected = bool((cfg.access_token or cfg.webhook_url))
    return {
        "connected": connected,
        "details": {
            "integration_type": cfg.integration_type,
            "dm_enabled": getattr(cfg, "dm_enabled", False),
            "dm_user_id": getattr(cfg, "dm_user_id", None),
            "deployment_channel": cfg.deployment_channel,
            "default_channel": cfg.default_channel,
        },
    }
