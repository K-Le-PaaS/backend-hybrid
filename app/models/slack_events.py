"""
Slack 이벤트 타입 및 라우팅 모델

Slack 알림 시스템에서 사용하는 이벤트 타입과 라우팅 규칙을 정의합니다.
"""

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class SlackEventType(str, Enum):
    """Slack 이벤트 타입"""
    # 배포 관련
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_SUCCESS = "deployment_success"
    DEPLOYMENT_FAILED = "deployment_failed"
    DEPLOYMENT_ROLLBACK = "deployment_rollback"
    
    # 빌드 관련
    BUILD_STARTED = "build_started"
    BUILD_SUCCESS = "build_success"
    BUILD_FAILED = "build_failed"
    
    # 릴리즈 관련
    RELEASE_CREATED = "release_created"
    RELEASE_DEPLOYED = "release_deployed"
    
    # 에러 관련
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    API_ERROR = "api_error"
    SYSTEM_ERROR = "system_error"
    
    # 헬스 체크 관련
    HEALTH_DOWN = "health_down"
    HEALTH_RECOVERED = "health_recovered"
    
    # MCP 관련
    MCP_CONNECTION_FAILED = "mcp_connection_failed"
    MCP_TOOL_FAILED = "mcp_tool_failed"
    MCP_RATE_LIMITED = "mcp_rate_limited"


class SlackChannelType(str, Enum):
    """Slack 채널 타입"""
    DEFAULT = "default"
    DEPLOYMENTS = "deployments"
    BUILD = "build"
    RELEASES = "releases"
    ERRORS = "errors"
    SECURITY = "security"
    HEALTH = "health"
    MCP = "mcp"


class SlackNotificationRequest(BaseModel):
    """Slack 알림 요청 모델"""
    event_type: SlackEventType
    title: str
    message: str
    channel: Optional[str] = None
    channel_type: Optional[SlackChannelType] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    blocks: Optional[list[Dict[str, Any]]] = None
    attachments: Optional[list[Dict[str, Any]]] = None
    thread_ts: Optional[str] = None
    priority: str = Field(default="normal")  # low, normal, high, urgent


class SlackChannelMapping(BaseModel):
    """Slack 채널 매핑 설정"""
    event_type: SlackEventType
    channel: str
    channel_type: SlackChannelType
    template: Optional[str] = None
    priority: str = "normal"


class SlackTemplate(BaseModel):
    """Slack 템플릿 설정"""
    event_type: SlackEventType
    template_name: str
    template_content: str
    variables: list[str] = Field(default_factory=list)


class SlackNotificationResponse(BaseModel):
    """Slack 알림 응답 모델"""
    success: bool
    message_ts: Optional[str] = None
    channel: str
    error: Optional[str] = None
    retry_after: Optional[int] = None  # Rate limit 시 재시도 시간


class SlackRoutingConfig(BaseModel):
    """Slack 라우팅 설정"""
    default_channel: str
    channel_mappings: Dict[SlackEventType, SlackChannelMapping] = Field(default_factory=dict)
    templates: Dict[SlackEventType, SlackTemplate] = Field(default_factory=dict)
    rate_limit_config: Dict[str, Any] = Field(default_factory=dict)
    retry_config: Dict[str, Any] = Field(default_factory=dict)
