"""
Deployment URL 모델

사용자별 저장소의 배포 URL을 관리하는 모델입니다.
롤백과 독립적으로 URL을 관리하여 사용자가 설정한 URL이 유지됩니다.
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, UniqueConstraint
from datetime import datetime, timezone
from .base import Base


class DeploymentUrl(Base):
    """
    사용자별 저장소의 배포 URL 관리
    
    사용자가 설정한 배포 URL을 저장하며, 롤백과 독립적으로 관리됩니다.
    """
    __tablename__ = "deployment_urls"

    id = Column(Integer, primary_key=True, index=True)

    # 사용자 및 저장소 식별
    user_id = Column(String(255), nullable=False, index=True)  # 사용자 ID
    github_owner = Column(String(255), nullable=False, index=True)  # GitHub 저장소 소유자
    github_repo = Column(String(255), nullable=False, index=True)  # GitHub 저장소 이름

    # URL 정보
    url = Column(String(500), nullable=False)  # 배포 URL (예: https://test03.klepaas.com)
    
    # 사용자 변경 여부
    is_user_modified = Column(Boolean, default=False, nullable=False)  # 사용자가 직접 변경했는지 여부

    # 타임스탬프
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # 유니크 제약조건: 사용자별 저장소당 하나의 URL
    __table_args__ = (
        UniqueConstraint('user_id', 'github_owner', 'github_repo', name='uq_user_repo_url'),
    )

    def __repr__(self):
        return (
            f"<DeploymentUrl(id={self.id}, "
            f"user_id={self.user_id}, "
            f"repo={self.github_owner}/{self.github_repo}, "
            f"url={self.url}, "
            f"user_modified={self.is_user_modified})>"
        )

    def to_dict(self):
        """딕셔너리로 변환"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "github_owner": self.github_owner,
            "github_repo": self.github_repo,
            "url": self.url,
            "is_user_modified": self.is_user_modified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
