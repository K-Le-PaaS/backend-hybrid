from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
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

    # Prometheus
    prometheus_base_url: str | None = None

    # Slack
    slack_webhook_url: str | None = None

    # GitHub App
    github_app_id: str | None = None
    github_app_private_key: str | None = None
    github_app_webhook_secret: str | None = None

    class Config:
        env_prefix = "KLEPAAS_"
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


