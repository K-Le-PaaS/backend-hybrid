"""
배포 히스토리 데이터 모델

K-Le-PaaS의 배포 이력을 영구 저장하고 관리하는 모델입니다.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base

from .base import Base


class ImageTagType(str, Enum):
    """이미지 태그 타입"""
    SHA = "sha"  # Git commit SHA 기반
    SEMVER = "semver"  # Semantic Version 기반
    BRANCH = "branch"  # Git branch 기반
    CUSTOM = "custom"  # 사용자 정의


class DeploymentStatus(str, Enum):
    """배포 상태"""
    PENDING = "pending"  # 배포 대기 중
    IN_PROGRESS = "in_progress"  # 배포 진행 중
    SUCCESS = "success"  # 배포 성공
    FAILED = "failed"  # 배포 실패
    ROLLED_BACK = "rolled_back"  # 롤백됨


class DeploymentHistoryModel(Base):
    """배포 히스토리 테이블 모델"""
    __tablename__ = "deployment_history"

    id = Column(Integer, primary_key=True, index=True)
    
    # 기본 정보
    app_name = Column(String(255), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    image = Column(String(500), nullable=False)
    image_tag = Column(String(255), nullable=True, index=True)
    image_tag_type = Column(String(20), nullable=True, default=ImageTagType.SHA.value)
    
    # 배포 설정
    replicas = Column(Integer, nullable=False, default=2)
    namespace = Column(String(100), nullable=True)
    
    # 상태 정보
    status = Column(String(20), nullable=False, default=DeploymentStatus.PENDING.value)
    progress = Column(Integer, nullable=False, default=0)  # 0-100%
    
    # 메타데이터
    deployed_by = Column(String(255), nullable=True)  # 사용자 또는 서비스
    deployment_reason = Column(String(500), nullable=True)  # 배포 사유
    git_commit_sha = Column(String(40), nullable=True)  # Git commit SHA
    git_branch = Column(String(100), nullable=True)  # Git branch
    
    # 롤백 정보
    is_rollback = Column(Boolean, nullable=False, default=False)
    rolled_back_from = Column(Integer, nullable=True)  # 롤백된 배포 ID
    rollback_reason = Column(String(500), nullable=True)  # 롤백 사유
    
    # Kubernetes 리소스 정보
    deployment_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True)
    configmap_name = Column(String(255), nullable=True)
    
    # 추가 메타데이터 (JSON)
    extra_metadata = Column(JSON, nullable=True)
    
    # 타임스탬프
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deployed_at = Column(DateTime(timezone=True), nullable=True)  # 실제 배포 완료 시간
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)  # 롤백 시간


class DeploymentHistoryCreate(BaseModel):
    """배포 히스토리 생성 요청 모델"""
    app_name: str = Field(..., min_length=1, max_length=255)
    environment: str = Field(..., min_length=1, max_length=50)
    image: str = Field(..., min_length=1, max_length=500)
    image_tag: Optional[str] = Field(None, max_length=255)
    image_tag_type: ImageTagType = Field(default=ImageTagType.SHA)
    replicas: int = Field(default=2, ge=1)
    namespace: Optional[str] = Field(None, max_length=100)
    status: DeploymentStatus = Field(default=DeploymentStatus.PENDING)
    progress: int = Field(default=0, ge=0, le=100)
    deployed_by: Optional[str] = Field(None, max_length=255)
    deployment_reason: Optional[str] = Field(None, max_length=500)
    git_commit_sha: Optional[str] = Field(None, max_length=40)
    git_branch: Optional[str] = Field(None, max_length=100)
    is_rollback: bool = Field(default=False)
    rolled_back_from: Optional[int] = Field(None)
    rollback_reason: Optional[str] = Field(None, max_length=500)
    deployment_name: Optional[str] = Field(None, max_length=255)
    service_name: Optional[str] = Field(None, max_length=255)
    configmap_name: Optional[str] = Field(None, max_length=255)
    extra_metadata: Optional[dict] = Field(None)


class DeploymentHistoryResponse(BaseModel):
    """배포 히스토리 응답 모델"""
    id: int
    app_name: str
    environment: str
    image: str
    image_tag: Optional[str]
    image_tag_type: str
    replicas: int
    namespace: Optional[str]
    status: str
    progress: int
    deployed_by: Optional[str]
    deployment_reason: Optional[str]
    git_commit_sha: Optional[str]
    git_branch: Optional[str]
    is_rollback: bool
    rolled_back_from: Optional[int]
    rollback_reason: Optional[str]
    deployment_name: Optional[str]
    service_name: Optional[str]
    configmap_name: Optional[str]
    extra_metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime
    deployed_at: Optional[datetime]
    rolled_back_at: Optional[datetime]

    class Config:
        from_attributes = True


class DeploymentHistoryQuery(BaseModel):
    """배포 히스토리 조회 쿼리 모델"""
    app_name: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[DeploymentStatus] = None
    image_tag_type: Optional[ImageTagType] = None
    is_rollback: Optional[bool] = None
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class DeploymentHistoryStats(BaseModel):
    """배포 히스토리 통계 모델"""
    total_deployments: int
    successful_deployments: int
    failed_deployments: int
    rollback_count: int
    success_rate: float
    average_deployment_time: Optional[float]  # 초 단위
    recent_deployments: list[DeploymentHistoryResponse]
    image_tag_type_stats: dict[str, int]
    environment_stats: dict[str, int]
