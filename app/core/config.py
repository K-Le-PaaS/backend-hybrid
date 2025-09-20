from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field
from pydantic import ConfigDict


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

    # K8s Deploy (staging)
    enable_k8s_deploy: bool = False
    k8s_staging_namespace: str = "staging"
    k8s_image_pull_secret: str | None = "ncp-cr"

    # MCP trigger (optional)
    mcp_trigger_provider: str | None = None
    mcp_trigger_tool: str | None = "deploy_application"

    # Slack
    slack_webhook_url: str | None = None
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


