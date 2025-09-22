from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field
from pydantic import ConfigDict
from typing import Dict


class Settings(BaseSettings):
    model_config = ConfigDict(env_prefix="KLEPAAS_", extra="ignore")
    app_name: str = Field(default="K-Le-PaaS Backend Hybrid")
    app_version: str = Field(default="0.1.0")

    # Vertex AI / Gemini
    gcp_project: str | None = None
    gcp_location: str | None = "europe-west4"
    gemini_model: str | None = "gemini-2.0-flash"
    # Authentication expects ADC or service account via env; optional here

    # GitHub Webhook
    github_webhook_secret: str | None = None
    github_branch_main: str | None = "main"
    # Generic staging webhook secret (HMAC-SHA256)
    staging_webhook_secret: str | None = None

    # Prometheus
    prometheus_base_url: str | None = None

    # Health Check & Monitoring
    rabbitmq_bridge_url: str | None = Field(default="http://localhost:8001/health")
    prometheus_health_url: str | None = None
    database_url: str | None = None
    
    # Alertmanager
    alertmanager_url: str | None = None
    alertmanager_webhook_url: str | None = None

    # K8s Deploy (staging)
    enable_k8s_deploy: bool = False
    k8s_staging_namespace: str = "staging"
    k8s_image_pull_secret: str | None = "ncp-cr"

    # MCP trigger (optional)
    mcp_trigger_provider: str | None = None
    mcp_trigger_tool: str | None = "deploy_application"
    
    # MCP Git Agent 설정
    mcp_git_agent_enabled: bool = Field(default=True, description="MCP 네이티브 Git 에이전트 사용 여부")
    mcp_default_cloud_provider: str = Field(default="gcp", description="기본 클라우드 프로바이더 (gcp/ncp)")
    mcp_git_agent_timeout: int = Field(default=300, description="MCP Git 에이전트 타임아웃 (초)")
    
    # GCP Git Agent 설정
    gcp_git_agent_url: str | None = Field(default="http://gcp-git-agent:8001", description="GCP Git Agent URL")
    gcp_project_id: str | None = None
    gcp_gcr_region: str = Field(default="asia-northeast3", description="GCP Container Registry 지역")
    
    # NCP Git Agent 설정
    ncp_git_agent_url: str | None = Field(default="http://ncp-git-agent:8001", description="NCP Git Agent URL")
    ncp_container_registry_url: str | None = None
    ncp_region: str = Field(default="KR", description="NCP 지역")

    # Slack
    slack_webhook_url: str | None = None
    
    # Slack OAuth 2.0 (사용자 친화적 연동용)
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_redirect_uri: str | None = None
    
    # Alerting (optional)
    slack_alert_channel_default: str | None = None
    slack_alert_channel_rate_limited: str | None = None
    slack_alert_channel_unauthorized: str | None = None
    slack_alert_template_error: str | None = Field(
        default="[MCP][ERROR] {{operation}} failed: code={{code}} msg={{message}}"
    )
    slack_alert_template_health_down: str | None = Field(
        default="[MCP][HEALTH][DOWN] code={{code}} msg={{message}}"
    )

    # GitHub App
    github_app_id: str | None = None
    github_app_private_key: str | None = None
    github_app_webhook_secret: str | None = None

    # Advanced NLP Settings
    advanced_nlp_enabled: bool = Field(default=True, description="고급 NLP 기능 활성화 여부")
    redis_url: str = Field(default="redis://localhost:6379", description="Redis 연결 URL")
    context_ttl: int = Field(default=3600, description="컨텍스트 TTL (초)")
    conversation_ttl: int = Field(default=86400, description="대화 히스토리 TTL (초)")
    pattern_ttl: int = Field(default=604800, description="패턴 데이터 TTL (초)")
    learning_ttl: int = Field(default=2592000, description="학습 데이터 TTL (초)")
    
    # Model Performance Tracking
    model_performance_tracking: bool = Field(default=True, description="모델 성능 추적 활성화")
    performance_tracking_ttl: int = Field(default=7776000, description="성능 추적 데이터 TTL (초)")
    
    # Learning Weights
    learning_weights: Dict[str, float] = Field(
        default={
            "user_feedback": 0.4,
            "success_patterns": 0.3,
            "model_performance": 0.2,
            "context_similarity": 0.1
        },
        description="학습 가중치 설정"
    )
    
    # Multi-Model Configuration
    multi_model_enabled: bool = Field(default=True, description="다중 모델 처리 활성화")
    claude_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    
    # Model Selection Strategy
    model_selection_strategy: str = Field(default="confidence_based", description="모델 선택 전략 (confidence_based, performance_based, hybrid)")
    confidence_threshold: float = Field(default=0.7, description="신뢰도 임계값")
    performance_weight: float = Field(default=0.3, description="성능 가중치")
    
    # Context Management
    max_context_length: int = Field(default=4000, description="최대 컨텍스트 길이")
    context_window_size: int = Field(default=10, description="컨텍스트 윈도우 크기")
    
    # Smart Command Interpreter
    ambiguity_threshold: float = Field(default=0.3, description="모호함 임계값")
    suggestion_confidence_threshold: float = Field(default=0.8, description="제안 신뢰도 임계값")
    
    # Learning Processor
    learning_enabled: bool = Field(default=True, description="학습 기능 활성화")
    feedback_learning_rate: float = Field(default=0.1, description="피드백 학습률")
    pattern_learning_rate: float = Field(default=0.05, description="패턴 학습률")
    
    # OAuth2 Configuration
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


