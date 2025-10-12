"""
DeploymentHistory 모델

CI/CD 파이프라인의 배포 히스토리를 저장하는 모델입니다.
GitHub Push 이벤트부터 SourceCommit, SourceBuild, SourceDeploy까지의
전체 배포 과정을 추적하고 실시간 진행률 표시에 사용됩니다.
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, List
from enum import Enum
from .base import Base


class ImageTagType(Enum):
    """이미지 태그 타입"""
    CUSTOM = "custom"
    SHA = "sha"
    SEMVER = "semver"
    BRANCH = "branch"


class DeploymentStatus(Enum):
    """배포 상태"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentHistoryCreate:
    """배포 히스토리 생성 데이터"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DeploymentHistoryResponse:
    """배포 히스토리 응답 데이터"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DeploymentHistoryQuery:
    """배포 히스토리 쿼리 데이터"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DeploymentHistoryStats:
    """배포 히스토리 통계 데이터"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DeploymentHistory(Base):
    """배포 히스토리 모델"""
    
    __tablename__ = "deployment_histories"
    
    # 기본 정보
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    
    # GitHub 정보
    github_owner = Column(String(255), nullable=False)
    github_repo = Column(String(255), nullable=False)
    github_commit_sha = Column(String(255), nullable=True)
    github_commit_message = Column(Text, nullable=True)
    github_commit_author = Column(String(255), nullable=True)
    github_commit_url = Column(String(500), nullable=True)
    
    # NCP 파이프라인 정보
    sourcecommit_project_id = Column(String(255), nullable=True)
    sourcecommit_repo_name = Column(String(255), nullable=True)
    sourcebuild_project_id = Column(String(255), nullable=True)
    sourcedeploy_project_id = Column(String(255), nullable=True)
    build_id = Column(String(255), nullable=True)
    deploy_id = Column(String(255), nullable=True)
    
    # 단계별 상태
    status = Column(String(50), nullable=False, default="running")  # running, success, failed
    sourcecommit_status = Column(String(50), nullable=True)  # success, failed
    sourcebuild_status = Column(String(50), nullable=True)  # success, failed
    sourcedeploy_status = Column(String(50), nullable=True)  # success, failed
    
    # 이미지 정보
    image_name = Column(String(500), nullable=True)
    image_tag = Column(String(100), nullable=True)
    image_url = Column(String(500), nullable=True)
    
    # 클러스터 정보
    cluster_id = Column(String(255), nullable=True)
    cluster_name = Column(String(255), nullable=True)
    namespace = Column(String(255), nullable=True, default="default")
    
    # 시간 정보
    started_at = Column(DateTime, nullable=False, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 소요 시간 (초)
    total_duration = Column(Integer, nullable=True)  # 전체 소요 시간
    sourcecommit_duration = Column(Integer, nullable=True)  # SourceCommit 소요 시간
    sourcebuild_duration = Column(Integer, nullable=True)  # SourceBuild 소요 시간
    sourcedeploy_duration = Column(Integer, nullable=True)  # SourceDeploy 소요 시간
    
    # 에러 정보
    error_message = Column(Text, nullable=True)
    error_stage = Column(String(50), nullable=True)  # 어느 단계에서 에러 발생
    
    # 메타데이터
    webhook_payload = Column(Text, nullable=True)  # 원본 웹훅 페이로드 (디버깅용)
    auto_deploy_enabled = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<DeploymentHistory(id={self.id}, user_id={self.user_id}, repo={self.github_owner}/{self.github_repo}, status={self.status})>"
    
    @property
    def repository_name(self):
        """리포지토리 전체 이름 반환"""
        return f"{self.github_owner}/{self.github_repo}"
    
    @property
    def short_commit_sha(self):
        """짧은 커밋 SHA 반환"""
        return self.github_commit_sha[:7] if self.github_commit_sha else None
    
    @property
    def is_completed(self):
        """배포 완료 여부"""
        return self.status in ["success", "failed"]
    
    @property
    def is_success(self):
        """배포 성공 여부"""
        return self.status == "success"
    
    @property
    def is_failed(self):
        """배포 실패 여부"""
        return self.status == "failed"
    
    @property
    def is_running(self):
        """배포 실행 중 여부"""
        return self.status == "running"
    
    def calculate_duration(self):
        """소요 시간 계산"""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            self.total_duration = int(delta.total_seconds())
        return self.total_duration
    
    def get_stage_status(self, stage_name):
        """특정 단계의 상태 반환"""
        stage_mapping = {
            "sourcecommit": self.sourcecommit_status,
            "sourcebuild": self.sourcebuild_status,
            "sourcedeploy": self.sourcedeploy_status
        }
        return stage_mapping.get(stage_name.lower())
    
    def get_stage_duration(self, stage_name):
        """특정 단계의 소요 시간 반환"""
        stage_mapping = {
            "sourcecommit": self.sourcecommit_duration,
            "sourcebuild": self.sourcebuild_duration,
            "sourcedeploy": self.sourcedeploy_duration
        }
        return stage_mapping.get(stage_name.lower())
    
    def to_dict(self):
        """딕셔너리로 변환 (API 응답용)"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "repository": self.repository_name,
            "commit": {
                "sha": self.github_commit_sha,
                "short_sha": self.short_commit_sha,
                "message": self.github_commit_message,
                "author": self.github_commit_author,
                "url": self.github_commit_url
            },
            "status": self.status,
            "stages": {
                "sourcecommit": {
                    "status": self.sourcecommit_status,
                    "duration": self.sourcecommit_duration
                },
                "sourcebuild": {
                    "status": self.sourcebuild_status,
                    "duration": self.sourcebuild_duration
                },
                "sourcedeploy": {
                    "status": self.sourcedeploy_status,
                    "duration": self.sourcedeploy_duration
                }
            },
            "image": {
                "name": self.image_name,
                "tag": self.image_tag,
                "url": self.image_url
            },
            "cluster": {
                "id": self.cluster_id,
                "name": self.cluster_name,
                "namespace": self.namespace
            },
            "timing": {
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "total_duration": self.total_duration
            },
            "error": {
                "message": self.error_message,
                "stage": self.error_stage
            } if self.error_message else None,
            "auto_deploy_enabled": self.auto_deploy_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }