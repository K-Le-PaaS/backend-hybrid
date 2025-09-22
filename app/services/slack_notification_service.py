"""
Slack 통합 알림 서비스

모든 Slack 알림을 통합 관리하고 이벤트 기반 라우팅을 제공하는 서비스입니다.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum

import structlog
from jinja2 import Environment, StrictUndefined, FileSystemLoader

from ..models.slack_events import (
    SlackEventType,
    SlackChannelType,
    SlackNotificationRequest,
    SlackNotificationResponse,
    SlackChannelMapping,
    SlackTemplate
)
from .slack_client import get_slack_client, SlackClientWrapper
from ..core.config import get_settings

logger = structlog.get_logger(__name__)


class NotificationPriority(str, Enum):
    """알림 우선순위"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SlackNotificationService:
    """Slack 통합 알림 서비스"""
    
    def __init__(self, slack_client: Optional[SlackClientWrapper] = None):
        self.slack_client = slack_client or get_slack_client()
        self.settings = get_settings()
        self.template_env = None
        self._initialize_templates()
        
    def _initialize_templates(self):
        """템플릿 환경을 초기화합니다."""
        try:
            # Jinja2 템플릿 환경 설정
            self.template_env = Environment(
                loader=FileSystemLoader("templates/slack"),
                undefined=StrictUndefined,
                autoescape=False
            )
            logger.info("slack_templates_initialized")
        except Exception as e:
            logger.warning("slack_templates_initialization_failed", error=str(e))
            # 기본 템플릿 환경
            self.template_env = Environment(undefined=StrictUndefined, autoescape=False)

    async def send_deployment_notification(
        self,
        event_type: SlackEventType,
        app_name: str,
        environment: str,
        image: str,
        status: str,
        deployment_id: Optional[str] = None,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """배포 관련 알림을 전송합니다."""
        try:
            # 이벤트별 제목 및 메시지 생성
            title, message = self._create_deployment_message(
                event_type, app_name, environment, image, status, 
                error_message, progress, deployment_id
            )
            
            # 컨텍스트 생성
            context = {
                "app_name": app_name,
                "environment": environment,
                "image": image,
                "status": status,
                "deployment_id": deployment_id,
                "error_message": error_message,
                "progress": progress,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # 알림 요청 생성
            request = SlackNotificationRequest(
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                channel_type=SlackChannelType.DEPLOYMENTS,
                context=context,
                priority=self._get_priority_for_event(event_type)
            )
            
            # 알림 전송
            response = await self.slack_client.send_notification(request)
            
            logger.info(
                "deployment_notification_sent",
                event_type=event_type,
                app_name=app_name,
                environment=environment,
                success=response.success
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "deployment_notification_failed",
                error=str(e),
                event_type=event_type,
                app_name=app_name
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_build_notification(
        self,
        event_type: SlackEventType,
        app_name: str,
        branch: str,
        commit_sha: str,
        status: str,
        build_url: Optional[str] = None,
        error_message: Optional[str] = None,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """빌드 관련 알림을 전송합니다."""
        try:
            # 이벤트별 제목 및 메시지 생성
            title, message = self._create_build_message(
                event_type, app_name, branch, commit_sha, status, 
                build_url, error_message
            )
            
            # 컨텍스트 생성
            context = {
                "app_name": app_name,
                "branch": branch,
                "commit_sha": commit_sha,
                "status": status,
                "build_url": build_url,
                "error_message": error_message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # 알림 요청 생성
            request = SlackNotificationRequest(
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                channel_type=SlackChannelType.BUILD,
                context=context,
                priority=self._get_priority_for_event(event_type)
            )
            
            # 알림 전송
            response = await self.slack_client.send_notification(request)
            
            logger.info(
                "build_notification_sent",
                event_type=event_type,
                app_name=app_name,
                branch=branch,
                success=response.success
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "build_notification_failed",
                error=str(e),
                event_type=event_type,
                app_name=app_name
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_error_notification(
        self,
        event_type: SlackEventType,
        operation: str,
        error_code: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """에러 관련 알림을 전송합니다."""
        try:
            # 이벤트별 제목 및 메시지 생성
            title, message = self._create_error_message(
                event_type, operation, error_code, error_message, context
            )
            
            # 컨텍스트 병합
            full_context = {
                "operation": operation,
                "error_code": error_code,
                "error_message": error_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **(context or {})
            }
            
            # 알림 요청 생성
            request = SlackNotificationRequest(
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                channel_type=SlackChannelType.ERRORS,
                context=full_context,
                priority=self._get_priority_for_event(event_type)
            )
            
            # 알림 전송
            response = await self.slack_client.send_notification(request)
            
            logger.info(
                "error_notification_sent",
                event_type=event_type,
                operation=operation,
                error_code=error_code,
                success=response.success
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "error_notification_failed",
                error=str(e),
                event_type=event_type,
                operation=operation
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_health_notification(
        self,
        event_type: SlackEventType,
        service_name: str,
        status: str,
        details: Optional[str] = None,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """헬스 체크 관련 알림을 전송합니다."""
        try:
            # 이벤트별 제목 및 메시지 생성
            title, message = self._create_health_message(
                event_type, service_name, status, details
            )
            
            # 컨텍스트 생성
            context = {
                "service_name": service_name,
                "status": status,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # 알림 요청 생성
            request = SlackNotificationRequest(
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                channel_type=SlackChannelType.HEALTH,
                context=context,
                priority=self._get_priority_for_event(event_type)
            )
            
            # 알림 전송
            response = await self.slack_client.send_notification(request)
            
            logger.info(
                "health_notification_sent",
                event_type=event_type,
                service_name=service_name,
                success=response.success
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "health_notification_failed",
                error=str(e),
                event_type=event_type,
                service_name=service_name
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    def _create_deployment_message(
        self,
        event_type: SlackEventType,
        app_name: str,
        environment: str,
        image: str,
        status: str,
        error_message: Optional[str] = None,
        progress: Optional[int] = None,
        deployment_id: Optional[str] = None
    ) -> tuple[str, str]:
        """배포 메시지를 생성합니다."""
        if event_type == SlackEventType.DEPLOYMENT_STARTED:
            title = f"🚀 배포 시작: {app_name}"
            message = f"**환경**: {environment}\n**이미지**: {image}\n**진행률**: {progress or 0}%"
            if deployment_id:
                message += f"\n**배포 ID**: {deployment_id}"
        
        elif event_type == SlackEventType.DEPLOYMENT_SUCCESS:
            title = f"✅ 배포 성공: {app_name}"
            message = f"**환경**: {environment}\n**이미지**: {image}\n**상태**: {status}"
            if deployment_id:
                message += f"\n**배포 ID**: {deployment_id}"
        
        elif event_type == SlackEventType.DEPLOYMENT_FAILED:
            title = f"❌ 배포 실패: {app_name}"
            message = f"**환경**: {environment}\n**이미지**: {image}\n**상태**: {status}"
            if error_message:
                message += f"\n**에러**: {error_message}"
            if deployment_id:
                message += f"\n**배포 ID**: {deployment_id}"
        
        elif event_type == SlackEventType.DEPLOYMENT_ROLLBACK:
            title = f"🔄 롤백 완료: {app_name}"
            message = f"**환경**: {environment}\n**이미지**: {image}\n**상태**: {status}"
            if deployment_id:
                message += f"\n**배포 ID**: {deployment_id}"
        
        else:
            title = f"📦 배포 알림: {app_name}"
            message = f"**환경**: {environment}\n**이미지**: {image}\n**상태**: {status}"
        
        return title, message

    def _create_build_message(
        self,
        event_type: SlackEventType,
        app_name: str,
        branch: str,
        commit_sha: str,
        status: str,
        build_url: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> tuple[str, str]:
        """빌드 메시지를 생성합니다."""
        if event_type == SlackEventType.BUILD_STARTED:
            title = f"🔨 빌드 시작: {app_name}"
            message = f"**브랜치**: {branch}\n**커밋**: {commit_sha[:8]}"
            if build_url:
                message += f"\n**빌드 URL**: {build_url}"
        
        elif event_type == SlackEventType.BUILD_SUCCESS:
            title = f"✅ 빌드 성공: {app_name}"
            message = f"**브랜치**: {branch}\n**커밋**: {commit_sha[:8]}\n**상태**: {status}"
            if build_url:
                message += f"\n**빌드 URL**: {build_url}"
        
        elif event_type == SlackEventType.BUILD_FAILED:
            title = f"❌ 빌드 실패: {app_name}"
            message = f"**브랜치**: {branch}\n**커밋**: {commit_sha[:8]}\n**상태**: {status}"
            if error_message:
                message += f"\n**에러**: {error_message}"
            if build_url:
                message += f"\n**빌드 URL**: {build_url}"
        
        else:
            title = f"🔨 빌드 알림: {app_name}"
            message = f"**브랜치**: {branch}\n**커밋**: {commit_sha[:8]}\n**상태**: {status}"
        
        return title, message

    def _create_error_message(
        self,
        event_type: SlackEventType,
        operation: str,
        error_code: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[str, str]:
        """에러 메시지를 생성합니다."""
        if event_type == SlackEventType.RATE_LIMITED:
            title = f"⏰ Rate Limited: {operation}"
            message = f"**에러 코드**: {error_code}\n**메시지**: {error_message}"
        
        elif event_type == SlackEventType.UNAUTHORIZED:
            title = f"🔒 인증 실패: {operation}"
            message = f"**에러 코드**: {error_code}\n**메시지**: {error_message}"
        
        elif event_type == SlackEventType.API_ERROR:
            title = f"⚠️ API 에러: {operation}"
            message = f"**에러 코드**: {error_code}\n**메시지**: {error_message}"
        
        elif event_type == SlackEventType.SYSTEM_ERROR:
            title = f"💥 시스템 에러: {operation}"
            message = f"**에러 코드**: {error_code}\n**메시지**: {error_message}"
        
        else:
            title = f"❌ 에러: {operation}"
            message = f"**에러 코드**: {error_code}\n**메시지**: {error_message}"
        
        # 추가 컨텍스트 정보
        if context:
            for key, value in context.items():
                if key not in ["operation", "error_code", "error_message", "timestamp"]:
                    message += f"\n**{key}**: {value}"
        
        return title, message

    def _create_health_message(
        self,
        event_type: SlackEventType,
        service_name: str,
        status: str,
        details: Optional[str] = None
    ) -> tuple[str, str]:
        """헬스 체크 메시지를 생성합니다."""
        if event_type == SlackEventType.HEALTH_DOWN:
            title = f"🔴 서비스 다운: {service_name}"
            message = f"**상태**: {status}"
            if details:
                message += f"\n**세부사항**: {details}"
        
        elif event_type == SlackEventType.HEALTH_RECOVERED:
            title = f"🟢 서비스 복구: {service_name}"
            message = f"**상태**: {status}"
            if details:
                message += f"\n**세부사항**: {details}"
        
        else:
            title = f"🏥 헬스 체크: {service_name}"
            message = f"**상태**: {status}"
            if details:
                message += f"\n**세부사항**: {details}"
        
        return title, message

    def _get_priority_for_event(self, event_type: SlackEventType) -> str:
        """이벤트 타입에 따른 우선순위를 반환합니다."""
        high_priority_events = {
            SlackEventType.DEPLOYMENT_FAILED,
            SlackEventType.BUILD_FAILED,
            SlackEventType.UNAUTHORIZED,
            SlackEventType.SYSTEM_ERROR,
            SlackEventType.HEALTH_DOWN
        }
        
        urgent_events = {
            SlackEventType.UNAUTHORIZED,
            SlackEventType.SYSTEM_ERROR
        }
        
        if event_type in urgent_events:
            return NotificationPriority.URGENT.value
        elif event_type in high_priority_events:
            return NotificationPriority.HIGH.value
        else:
            return NotificationPriority.NORMAL.value

    async def send_custom_notification(
        self,
        event_type: SlackEventType,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
        channel_type: Optional[SlackChannelType] = None,
        priority: str = "normal"
    ) -> SlackNotificationResponse:
        """사용자 정의 알림을 전송합니다."""
        try:
            request = SlackNotificationRequest(
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                channel_type=channel_type,
                context=context or {},
                priority=priority
            )
            
            response = await self.slack_client.send_notification(request)
            
            logger.info(
                "custom_notification_sent",
                event_type=event_type,
                title=title,
                success=response.success
            )
            
            return response
            
        except Exception as e:
            logger.error(
                "custom_notification_failed",
                error=str(e),
                event_type=event_type,
                title=title
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_simple_message(
        self,
        title: str,
        message: str,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """간단한 메시지를 직접 전송합니다."""
        try:
            # 직접 httpx를 사용하여 메시지 전송
            webhook_url = self.settings.slack_webhook_url
            if not webhook_url:
                return SlackNotificationResponse(
                    success=False,
                    channel=channel or "unknown",
                    error="Slack webhook URL not configured"
                )
            
            # 채널 결정
            target_channel = channel or self.settings.slack_alert_channel_default or "#general"
            
            # 메시지 포맷팅
            formatted_message = f"*{title}*\n\n{message}"
            
            # 웹훅으로 전송
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "text": formatted_message,
                    "channel": target_channel
                }
                
                response = await client.post(webhook_url, json=payload)
                
                if response.status_code == 200:
                    logger.info("simple_message_sent", title=title, success=True)
                    return SlackNotificationResponse(
                        success=True,
                        channel=target_channel,
                        message_ts="webhook_success"
                    )
                else:
                    logger.error("simple_message_failed", title=title, status_code=response.status_code)
                    return SlackNotificationResponse(
                        success=False,
                        channel=target_channel,
                        error=f"HTTP {response.status_code}: {response.text}"
                    )
            
        except Exception as e:
            logger.error("simple_message_failed", title=title, error=str(e))
            return SlackNotificationResponse(
                success=False,
                channel=channel or "unknown",
                error=f"Unexpected error: {e}"
            )


# 전역 서비스 인스턴스
_slack_notification_service: Optional[SlackNotificationService] = None


def get_slack_notification_service() -> SlackNotificationService:
    """Slack 알림 서비스 인스턴스를 반환합니다."""
    global _slack_notification_service
    if _slack_notification_service is None:
        _slack_notification_service = SlackNotificationService()
    return _slack_notification_service


def init_slack_notification_service(slack_client: Optional[SlackClientWrapper] = None) -> SlackNotificationService:
    """Slack 알림 서비스를 초기화합니다."""
    global _slack_notification_service
    _slack_notification_service = SlackNotificationService(slack_client)
    return _slack_notification_service
