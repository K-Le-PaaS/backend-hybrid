"""
Slack OAuth 2.0 서비스
사용자 친화적인 Slack 연동을 위한 OAuth 처리
"""

import httpx
import structlog
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from ..core.config import get_settings

logger = structlog.get_logger(__name__)


class SlackTokenResponse(BaseModel):
    """Slack 토큰 응답 모델"""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    team_id: Optional[str] = None
    user_id: Optional[str] = None
    error: Optional[str] = None


class SlackMessageResponse(BaseModel):
    """Slack 메시지 응답 모델"""
    success: bool
    message_ts: Optional[str] = None
    channel: Optional[str] = None
    error: Optional[str] = None


class SlackChannel(BaseModel):
    """Slack 채널 모델"""
    id: str
    name: str
    is_private: bool
    is_member: bool


class SlackOAuthService:
    """Slack OAuth 2.0 서비스"""
    
    def __init__(self):
        self.settings = get_settings()
        self.client_id = self.settings.slack_client_id
        self.client_secret = self.settings.slack_client_secret
        self.redirect_uri = self.settings.slack_redirect_uri
    
    async def exchange_code_for_token(self, code: str) -> SlackTokenResponse:
        """인증 코드를 액세스 토큰으로 교환"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri
                    }
                )
                
                data = response.json()
                
                if data.get("ok"):
                    logger.info("slack_token_exchange_success")
                    # user_scope 사용 시 authed_user 객체에서 토큰 추출
                    authed_user = data.get("authed_user", {})
                    return SlackTokenResponse(
                        success=True,
                        access_token=authed_user.get("access_token") or data.get("access_token"),
                        refresh_token=authed_user.get("refresh_token") or data.get("refresh_token"),
                        team_id=data.get("team", {}).get("id"),
                        user_id=authed_user.get("id")
                    )
                else:
                    error = data.get("error", "Unknown error")
                    logger.error("slack_token_exchange_failed", error=error)
                    return SlackTokenResponse(
                        success=False,
                        error=error
                    )
                    
        except Exception as e:
            logger.error("slack_token_exchange_error", error=str(e))
            return SlackTokenResponse(
                success=False,
                error=f"Token exchange failed: {str(e)}"
            )
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """사용자 정보 조회"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                data = response.json()
                
                if data.get("ok"):
                    return {
                        "user_id": data.get("user_id"),
                        "team_id": data.get("team_id"),
                        "team_name": data.get("team"),
                        "bot_id": data.get("bot_id")
                    }
                else:
                    logger.error("slack_user_info_failed", error=data.get("error"))
                    return {}
                    
        except Exception as e:
            logger.error("slack_user_info_error", error=str(e))
            return {}
    
    async def get_available_channels(self, access_token: str) -> List[SlackChannel]:
        """사용자가 접근 가능한 채널 목록 조회"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://slack.com/api/conversations.list",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "types": "public_channel,private_channel",
                        "exclude_archived": "true",
                        "limit": 100
                    }
                )
                
                data = response.json()
                
                if data.get("ok"):
                    channels = []
                    for channel_data in data.get("channels", []):
                        channels.append(SlackChannel(
                            id=channel_data.get("id"),
                            name=channel_data.get("name"),
                            is_private=channel_data.get("is_private", False),
                            is_member=channel_data.get("is_member", False)
                        ))
                    
                    logger.info("slack_channels_retrieved", count=len(channels))
                    return channels
                else:
                    logger.error("slack_channels_failed", error=data.get("error"))
                    return []
                    
        except Exception as e:
            logger.error("slack_channels_error", error=str(e))
            return []
    
    async def send_test_message(
        self, 
        access_token: str, 
        channel: str = "#general"
    ) -> SlackMessageResponse:
        """테스트 메시지 전송"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={
                        "channel": channel,
                        "text": "🎉 K-Le-PaaS Slack 연동 테스트 성공!\n\n이 메시지가 보이면 Slack 연동이 완료된 것입니다!",
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": "🎉 K-Le-PaaS 연동 성공!"
                                }
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "Slack 연동이 성공적으로 완료되었습니다!\n이제 K-Le-PaaS에서 배포 알림을 받을 수 있습니다."
                                }
                            },
                            {
                                "type": "divider"
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": "K-Le-PaaS MCP를 통해 전송된 메시지입니다."
                                    }
                                ]
                            }
                        ]
                    }
                )
                
                data = response.json()
                
                if data.get("ok"):
                    logger.info("slack_test_message_sent", channel=channel)
                    return SlackMessageResponse(
                        success=True,
                        message_ts=data.get("ts"),
                        channel=data.get("channel")
                    )
                else:
                    error = data.get("error", "Unknown error")
                    logger.error("slack_test_message_failed", error=error)
                    return SlackMessageResponse(
                        success=False,
                        error=error
                    )
                    
        except Exception as e:
            logger.error("slack_test_message_error", error=str(e))
            return SlackMessageResponse(
                success=False,
                error=f"Test message failed: {str(e)}"
            )
    
    async def send_notification(
        self,
        access_token: str,
        channel: str,
        title: str,
        message: str,
        blocks: Optional[List[Dict[str, Any]]] = None
    ) -> SlackMessageResponse:
        """알림 메시지 전송"""
        try:
            payload = {
                "channel": channel,
                "text": f"*{title}*\n\n{message}"
            }
            
            if blocks:
                payload["blocks"] = blocks
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=payload
                )
                
                data = response.json()
                
                if data.get("ok"):
                    logger.info("slack_notification_sent", channel=channel, title=title)
                    return SlackMessageResponse(
                        success=True,
                        message_ts=data.get("ts"),
                        channel=data.get("channel")
                    )
                else:
                    error = data.get("error", "Unknown error")
                    logger.error("slack_notification_failed", error=error)
                    return SlackMessageResponse(
                        success=False,
                        error=error
                    )
                    
        except Exception as e:
            logger.error("slack_notification_error", error=str(e))
            return SlackMessageResponse(
                success=False,
                error=f"Notification failed: {str(e)}"
            )

    async def open_im_channel(self, access_token: str, user_id: str) -> Optional[str]:
        """Open (or find) a DM channel with the specified user and return channel id.

        Requires im:write scope. Returns None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://slack.com/api/conversations.open",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"users": user_id},
                )
                data = resp.json()
                if data.get("ok"):
                    return data.get("channel", {}).get("id")
                logger.error("slack_open_im_failed", error=data.get("error"))
                return None
        except Exception as e:
            logger.error("slack_open_im_error", error=str(e))
            return None

    async def send_dm(
        self,
        access_token: str,
        user_id: str,
        title: str,
        message: str,
    ) -> SlackMessageResponse:
        """Send DM directly to user. With user_scope, we can send to user_id directly."""
        # user_scope 사용 시 user_id로 바로 전송 가능 (conversations.open 불필요)
        return await self.send_notification(access_token, user_id, title, message)