"""
Slack SDK 기반 고급 클라이언트

slack_sdk를 사용한 고급 Slack 연동 기능을 제공합니다.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from enum import Enum

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackClientError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.webhook import WebhookClient
from slack_sdk.webhook.async_client import AsyncWebhookClient

from ..core.config import get_settings
from ..models.slack_events import (
    SlackEventType,
    SlackChannelType,
    SlackNotificationRequest,
    SlackNotificationResponse,
    SlackChannelMapping,
    SlackRoutingConfig,
    SlackTemplate
)

logger = structlog.get_logger(__name__)


class SlackClientType(str, Enum):
    """Slack 클라이언트 타입"""
    WEBHOOK = "webhook"
    BOT_TOKEN = "bot_token"
    AUTO = "auto"  # 자동 선택


class SlackClientWrapper:
    """Slack SDK 래퍼 클래스"""
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        client_type: SlackClientType = SlackClientType.AUTO
    ):
        self.settings = get_settings()
        self.webhook_url = webhook_url or self.settings.slack_webhook_url
        self.bot_token = bot_token
        self.client_type = client_type
        
        # 클라이언트 초기화
        self._webhook_client: Optional[WebhookClient] = None
        self._bot_client: Optional[AsyncWebClient] = None
        self._routing_config: Optional[SlackRoutingConfig] = None
        
        # Rate limiting 상태
        self._rate_limits: Dict[str, Any] = {}
        self._retry_after: Dict[str, float] = {}
        
        # 즉시 초기화
        self._initialize_clients()
        
    def _initialize_clients(self):
        """클라이언트를 동기적으로 초기화합니다."""
        try:
            # Webhook URL만 저장 (httpx로 직접 사용)
            if self.webhook_url:
                logger.info("slack_webhook_url_configured", url=self.webhook_url[:50] + "...")
            
            # Bot Token 클라이언트 초기화
            if self.bot_token:
                self._bot_client = AsyncWebClient(token=self.bot_token)
                logger.info("slack_bot_client_initialized")
                
        except Exception as e:
            logger.error("slack_client_initialization_failed", error=str(e))
        
    async def initialize(self):
        """클라이언트를 초기화합니다."""
        try:
            # Webhook 클라이언트 초기화
            if self.webhook_url:
                self._webhook_client = AsyncWebhookClient(self.webhook_url)
                logger.info("slack_webhook_client_initialized")
            
            # Bot Token 클라이언트 초기화
            if self.bot_token:
                self._bot_client = AsyncWebClient(token=self.bot_token)
                logger.info("slack_bot_client_initialized")
            
            # 라우팅 설정 로드
            await self._load_routing_config()
            
            logger.info("slack_client_initialized", client_type=self.client_type)
            
        except Exception as e:
            logger.error("slack_client_initialization_failed", error=str(e))
            raise

    async def _load_routing_config(self):
        """라우팅 설정을 로드합니다."""
        try:
            # 기본 채널 매핑 설정
            channel_mappings = {}
            
            # 환경변수에서 채널 매핑 로드
            if self.settings.slack_alert_channel_default:
                channel_mappings[SlackEventType.DEPLOYMENT_SUCCESS] = SlackChannelMapping(
                    event_type=SlackEventType.DEPLOYMENT_SUCCESS,
                    channel=self.settings.slack_alert_channel_default,
                    channel_type=SlackChannelType.DEFAULT
                )
            
            if self.settings.slack_alert_channel_rate_limited:
                channel_mappings[SlackEventType.RATE_LIMITED] = SlackChannelMapping(
                    event_type=SlackEventType.RATE_LIMITED,
                    channel=self.settings.slack_alert_channel_rate_limited,
                    channel_type=SlackChannelType.ERRORS
                )
            
            if self.settings.slack_alert_channel_unauthorized:
                channel_mappings[SlackEventType.UNAUTHORIZED] = SlackChannelMapping(
                    event_type=SlackEventType.UNAUTHORIZED,
                    channel=self.settings.slack_alert_channel_unauthorized,
                    channel_type=SlackChannelType.SECURITY
                )
            
            # 기본 템플릿 설정
            templates = {}
            if self.settings.slack_alert_template_error:
                templates[SlackEventType.API_ERROR] = SlackTemplate(
                    event_type=SlackEventType.API_ERROR,
                    template_name="error",
                    template_content=self.settings.slack_alert_template_error,
                    variables=["operation", "code", "message"]
                )
            
            if self.settings.slack_alert_template_health_down:
                templates[SlackEventType.HEALTH_DOWN] = SlackTemplate(
                    event_type=SlackEventType.HEALTH_DOWN,
                    template_name="health_down",
                    template_content=self.settings.slack_alert_template_health_down,
                    variables=["code", "message"]
                )
            
            self._routing_config = SlackRoutingConfig(
                default_channel=self.settings.slack_alert_channel_default or "#general",
                channel_mappings=channel_mappings,
                templates=templates,
                rate_limit_config={
                    "max_retries": 3,
                    "base_delay": 1.0,
                    "max_delay": 60.0
                },
                retry_config={
                    "exponential_backoff": True,
                    "jitter": True
                }
            )
            
            logger.info("slack_routing_config_loaded", mappings_count=len(channel_mappings))
            
        except Exception as e:
            logger.error("slack_routing_config_load_failed", error=str(e))
            # 기본 설정으로 폴백
            self._routing_config = SlackRoutingConfig(
                default_channel="#general",
                channel_mappings={},
                templates={}
            )

    async def send_notification(self, request: SlackNotificationRequest) -> SlackNotificationResponse:
        """Slack 알림을 전송합니다."""
        try:
            # 채널 결정
            channel = await self._determine_channel(request)
            
            # 템플릿 적용
            message = await self._apply_template(request)
            
            # Rate limiting 확인
            if await self._is_rate_limited(channel):
                return SlackNotificationResponse(
                    success=False,
                    channel=channel,
                    error="Rate limited",
                    retry_after=int(self._retry_after.get(channel, 0))
                )
            
            # 메시지 전송
            response = await self._send_message(
                channel=channel,
                text=message,
                blocks=request.blocks,
                attachments=request.attachments,
                thread_ts=request.thread_ts
            )
            
            # Rate limiting 정보 업데이트
            await self._update_rate_limit_info(channel, response)
            
            return SlackNotificationResponse(
                success=True,
                message_ts=response.get("ts"),
                channel=channel
            )
            
        except SlackApiError as e:
            logger.error(
                "slack_api_error",
                error=str(e),
                error_code=e.response["error"],
                event_type=request.event_type
            )
            
            # Rate limiting 에러 처리
            if e.response["error"] == "rate_limited":
                retry_after = int(e.response.get("retry_after", 60))
                self._retry_after[channel] = retry_after
                
                return SlackNotificationResponse(
                    success=False,
                    channel=channel,
                    error="Rate limited",
                    retry_after=retry_after
                )
            
            return SlackNotificationResponse(
                success=False,
                channel=channel,
                error=f"Slack API error: {e.response['error']}"
            )
            
        except Exception as e:
            logger.error("slack_notification_failed", error=str(e), event_type=request.event_type)
            return SlackNotificationResponse(
                success=False,
                channel=channel,
                error=f"Unexpected error: {str(e)}"
            )

    async def _determine_channel(self, request: SlackNotificationRequest) -> str:
        """알림을 보낼 채널을 결정합니다."""
        # 명시적으로 지정된 채널
        if request.channel:
            return request.channel
        
        # 채널 타입별 매핑
        if request.channel_type and self._routing_config:
            for mapping in self._routing_config.channel_mappings.values():
                if mapping.channel_type == request.channel_type:
                    return mapping.channel
        
        # 이벤트 타입별 매핑
        if self._routing_config and request.event_type in self._routing_config.channel_mappings:
            mapping = self._routing_config.channel_mappings[request.event_type]
            return mapping.channel
        
        # 기본 채널
        return self._routing_config.default_channel if self._routing_config else "#general"

    async def _apply_template(self, request: SlackNotificationRequest) -> str:
        """템플릿을 적용하여 메시지를 생성합니다."""
        try:
            # 이벤트 타입별 템플릿 확인
            if (self._routing_config and 
                request.event_type in self._routing_config.templates):
                template_info = self._routing_config.templates[request.event_type]
                
                # Jinja2 템플릿 렌더링
                from jinja2 import Environment, StrictUndefined
                env = Environment(undefined=StrictUndefined, autoescape=False)
                template = env.from_string(template_info.template_content)
                
                # 컨텍스트 병합
                context = {**request.context, "title": request.title, "message": request.message}
                return template.render(**context)
            
            # 기본 메시지 포맷
            return f"**{request.title}**\n{request.message}"
            
        except Exception as e:
            logger.warning("template_rendering_failed", error=str(e), event_type=request.event_type)
            # 템플릿 실패 시 기본 메시지 반환
            return f"**{request.title}**\n{request.message}"

    async def _is_rate_limited(self, channel: str) -> bool:
        """채널이 Rate limited 상태인지 확인합니다."""
        if channel in self._retry_after:
            retry_after = self._retry_after[channel]
            if retry_after > 0:
                return True
        return False

    async def _send_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None
    ) -> Dict[str, Any]:
        """실제 메시지를 전송합니다."""
        # 클라이언트 타입 결정 (웹훅 우선)
        if self.webhook_url and (self.client_type == SlackClientType.WEBHOOK or not self._bot_client):
            return await self._send_webhook_message(
                channel, text, blocks, attachments, thread_ts
            )
        elif self._bot_client:
            return await self._send_bot_message(
                channel, text, blocks, attachments, thread_ts
            )
        else:
            raise SlackClientError("No Slack client configured")

    async def _send_webhook_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None
    ) -> Dict[str, Any]:
        """Webhook을 사용하여 메시지를 전송합니다."""
        if not self.webhook_url:
            raise SlackClientError("Webhook URL not configured")
        
        payload = {
            "text": text,
            "channel": channel
        }
        
        if blocks:
            payload["blocks"] = blocks
        if attachments:
            payload["attachments"] = attachments
        if thread_ts:
            payload["thread_ts"] = thread_ts
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self.webhook_url, json=payload)
                
                if response.status_code == 200:
                    return {
                        "ok": True,
                        "status": "success",
                        "channel": channel
                    }
                else:
                    logger.error("slack_webhook_send_failed", 
                               status_code=response.status_code, 
                               response=response.text)
                    raise SlackClientError(f"Webhook send failed: {response.status_code} - {response.text}")
                    
        except Exception as e:
            logger.error("slack_webhook_send_failed", error=str(e))
            raise SlackClientError(f"Webhook send failed: {e}")

    async def _send_bot_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bot Token을 사용하여 메시지를 전송합니다."""
        if not self._bot_client:
            raise SlackClientError("Bot client not initialized")
        
        response = await self._bot_client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=blocks,
            attachments=attachments,
            thread_ts=thread_ts
        )
        
        return {"ts": response["ts"]}

    async def _update_rate_limit_info(self, channel: str, response: Dict[str, Any]):
        """Rate limiting 정보를 업데이트합니다."""
        # 성공적인 전송 후 rate limit 정보 초기화
        if channel in self._retry_after:
            del self._retry_after[channel]

    async def get_channel_info(self, channel: str) -> Dict[str, Any]:
        """채널 정보를 조회합니다."""
        if not self._bot_client:
            return {"error": "Bot client not available"}
        
        try:
            response = await self._bot_client.conversations_info(channel=channel)
            return response.data
        except SlackApiError as e:
            logger.error("channel_info_failed", error=str(e), channel=channel)
            return {"error": str(e)}

    async def list_channels(self) -> List[Dict[str, Any]]:
        """사용 가능한 채널 목록을 조회합니다."""
        if not self._bot_client:
            return []
        
        try:
            response = await self._bot_client.conversations_list(types="public_channel,private_channel")
            return response.data.get("channels", [])
        except SlackApiError as e:
            logger.error("channels_list_failed", error=str(e))
            return []

    async def close(self):
        """클라이언트를 종료합니다."""
        if self._bot_client:
            await self._bot_client.close()
        logger.info("slack_client_closed")


# 전역 클라이언트 인스턴스
_slack_client: Optional[SlackClientWrapper] = None


def get_slack_client() -> SlackClientWrapper:
    """Slack 클라이언트 인스턴스를 반환합니다."""
    global _slack_client
    if _slack_client is None:
        _slack_client = SlackClientWrapper()
    return _slack_client


async def init_slack_client(
    webhook_url: Optional[str] = None,
    bot_token: Optional[str] = None,
    client_type: SlackClientType = SlackClientType.AUTO
) -> SlackClientWrapper:
    """Slack 클라이언트를 초기화합니다."""
    global _slack_client
    _slack_client = SlackClientWrapper(webhook_url, bot_token, client_type)
    await _slack_client.initialize()
    return _slack_client
