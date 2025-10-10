"""
사용자별 GitHub↔NCP 파이프라인 매핑 모델
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from .base import Base


class UserProjectIntegration(Base):
    __tablename__ = "user_project_integrations"

    id = Column(Integer, primary_key=True, index=True)

    # 사용자 식별자 (우리 서비스의 사용자 기준)
    user_id = Column(String(255), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)

    # GitHub 정보
    github_owner = Column(String(255), nullable=False)
    github_repo = Column(String(255), nullable=False)
    github_full_name = Column(String(512), nullable=False)  # owner/repo
    github_repository_id = Column(String(255), nullable=True)
    github_installation_id = Column(String(255), nullable=True)
    github_webhook_secret = Column(String(255), nullable=True)

    # SourceCommit 매핑
    sc_project_id = Column(String(255), nullable=True)
    sc_repo_name = Column(String(255), nullable=True)
    sc_clone_url = Column(String(1024), nullable=True)
    sc_repo_id = Column(String(255), nullable=True)

    # Build/Deploy/Pipeline 식별자
    build_project_id = Column(String(255), nullable=True)
    deploy_project_id = Column(String(255), nullable=True)
    pipeline_id = Column(String(255), nullable=True)

    # 레지스트리 정보
    registry_url = Column(String(512), nullable=True)
    image_repository = Column(String(512), nullable=True)  # {registry}/{owner}-{repo}

    # 기본 브랜치 및 자동화 옵션
    branch = Column(String(100), nullable=True, default="main")
    auto_deploy_enabled = Column(Boolean, default=True)

    # 메타/로그
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def key(self) -> str:
        return f"{self.user_id}:{self.github_full_name}"




