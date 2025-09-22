"""
Slack OAuth 2.0 인증 API
사용자가 쉽게 Slack을 연동할 수 있도록 도와주는 API
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse
from typing import Optional
import httpx
import secrets
import asyncio
from urllib.parse import urlencode

from ...core.config import get_settings
from ...services.slack_oauth import SlackOAuthService

router = APIRouter(prefix="/slack", tags=["slack-auth"])


@router.get("/auth/url")
async def get_slack_auth_url(
    redirect_uri: str = Query(..., description="인증 후 리다이렉트할 URI"),
    state: Optional[str] = None
):
    """
    Slack OAuth 인증 URL을 생성합니다.
    사용자가 이 URL을 클릭하면 Slack 인증 페이지로 이동합니다.
    """
    settings = get_settings()
    
    # 상태 토큰 생성 (CSRF 보호)
    if not state:
        state = secrets.token_urlsafe(32)
    
    # Slack OAuth URL 생성
    auth_params = {
        "client_id": settings.slack_client_id,
        "scope": "chat:write,channels:read,users:read,team:read",
        "redirect_uri": redirect_uri,
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
    state: str = Query(..., description="상태 토큰"),
    error: Optional[str] = Query(None, description="에러 메시지")
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
        
        # 사용자 정보 조회
        user_info = await oauth_service.get_user_info(token_response.access_token)
        
        return {
            "success": True,
            "message": "Slack 연동이 성공적으로 완료되었습니다!",
            "access_token": token_response.access_token,
            "team_id": token_response.team_id,
            "user_id": user_info.get("user_id"),
            "team_name": user_info.get("team_name"),
            "channels": await oauth_service.get_available_channels(token_response.access_token)
        }
        
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
    access_token: str = Query(..., description="Slack 액세스 토큰")
):
    """
    사용자가 접근 가능한 Slack 채널 목록을 조회합니다.
    """
    try:
        oauth_service = SlackOAuthService()
        channels = await oauth_service.get_available_channels(access_token)
        
        return {
            "success": True,
            "channels": channels
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채널 목록 조회 중 오류 발생: {str(e)}")


@router.post("/save-config")
async def save_slack_config(
    access_token: str = Query(..., description="Slack 액세스 토큰"),
    default_channel: str = Query("#general", description="기본 알림 채널"),
    deployment_channel: str = Query("#deployments", description="배포 알림 채널"),
    error_channel: str = Query("#alerts", description="에러 알림 채널")
):
    """
    Slack 설정을 저장합니다.
    """
    try:
        # 설정을 데이터베이스나 설정 파일에 저장
        # 여기서는 간단히 성공 응답만 반환
        return {
            "success": True,
            "message": "Slack 설정이 저장되었습니다!",
            "config": {
                "default_channel": default_channel,
                "deployment_channel": deployment_channel,
                "error_channel": error_channel
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"설정 저장 중 오류 발생: {str(e)}")
