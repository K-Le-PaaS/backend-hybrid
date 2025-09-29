"""
사용자별 연동된 리포지토리 모델
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base


class UserRepository(Base):
    """사용자별 연동된 리포지토리"""
    __tablename__ = "user_repositories"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)  # OAuth 사용자 ID
    user_email = Column(String(255), nullable=True)  # 사용자 이메일
    repository_owner = Column(String(255), nullable=False)  # 리포지토리 소유자
    repository_name = Column(String(255), nullable=False)  # 리포지토리 이름
    repository_full_name = Column(String(255), nullable=False)  # 전체 이름 (owner/repo)
    repository_id = Column(String(255), nullable=False)  # GitHub 리포지토리 ID
    branch = Column(String(100), nullable=True, default="main")  # 기본 브랜치
    last_sync = Column(DateTime(timezone=True), nullable=True)  # 마지막 동기화 시간
    status = Column(String(50), nullable=False, default="healthy")  # 상태 (healthy, warning, error)
    auto_deploy_enabled = Column(Boolean, default=False)  # 자동 배포 활성화
    webhook_configured = Column(Boolean, default=True)  # 웹훅 설정 여부
    installation_id = Column(String(255), nullable=True)  # GitHub App 설치 ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 인덱스 설정
    __table_args__ = (
        {"extend_existing": True}
    )
    
    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            "id": str(self.id),
            "name": self.repository_name,
            "fullName": self.repository_full_name,
            "connected": True,
            "lastSync": self.last_sync.isoformat() if self.last_sync else None,
            "branch": self.branch,
            "status": self.status,
            "autoDeployEnabled": self.auto_deploy_enabled,
            "webhookConfigured": self.webhook_configured,
        }

