"""
배포 히스토리 서비스 테스트

DeploymentHistoryService의 기능을 테스트합니다.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.base import Base
from models.deployment_history import (
    DeploymentHistory,
    ImageTagType,
    DeploymentStatus
)
from services.deployment_history import DeploymentHistoryService


@pytest.fixture
def db_session():
    """테스트용 데이터베이스 세션"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def deployment_history_service(db_session):
    """DeploymentHistoryService 인스턴스"""
    return DeploymentHistoryService(db_session)


class TestDeploymentHistoryService:
    """DeploymentHistoryService 테스트 클래스"""

    async def test_create_deployment_record(self, deployment_history_service):
        """배포 기록 생성 테스트"""
        deployment_id = await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0",
            replicas=3,
            namespace="klepaas-staging",
            deployed_by="test-user",
            deployment_reason="Test deployment",
            git_commit_sha="abc123",
            git_branch="main"
        )
        
        assert deployment_id is not None
        assert deployment_id > 0

    async def test_extract_image_tag_sha(self, deployment_history_service):
        """SHA 이미지 태그 추출 테스트"""
        image = "test-app:abc123def456789"
        tag, tag_type = deployment_history_service._extract_image_tag(image)
        
        assert tag == "abc123def456789"
        assert tag_type == ImageTagType.SHA

    async def test_extract_image_tag_semver(self, deployment_history_service):
        """SemVer 이미지 태그 추출 테스트"""
        image = "test-app:v1.2.3"
        tag, tag_type = deployment_history_service._extract_image_tag(image)
        
        assert tag == "v1.2.3"
        assert tag_type == ImageTagType.SEMVER

    async def test_extract_image_tag_branch(self, deployment_history_service):
        """Branch 이미지 태그 추출 테스트"""
        image = "test-app:feature/new-feature"
        tag, tag_type = deployment_history_service._extract_image_tag(image)
        
        assert tag == "feature/new-feature"
        assert tag_type == ImageTagType.BRANCH

    async def test_update_deployment_status(self, deployment_history_service):
        """배포 상태 업데이트 테스트"""
        # 배포 기록 생성
        deployment_id = await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0"
        )
        
        # 상태 업데이트
        success = await deployment_history_service.update_deployment_status(
            deployment_id=deployment_id,
            status=DeploymentStatus.SUCCESS,
            progress=100
        )
        
        assert success is True

    async def test_get_recent_versions(self, deployment_history_service):
        """최근 배포 버전 조회 테스트"""
        # 여러 배포 기록 생성
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0"
        )
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.1.0"
        )
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.2.0"
        )
        
        # 최근 버전 조회
        recent_versions = await deployment_history_service.get_recent_versions(
            app_name="test-app",
            environment="staging",
            limit=2
        )
        
        assert len(recent_versions) == 2
        assert recent_versions[0].image == "test-app:v1.2.0"  # 최신 버전
        assert recent_versions[1].image == "test-app:v1.1.0"  # 두 번째 최신 버전

    async def test_get_previous_version(self, deployment_history_service):
        """이전 배포 버전 조회 테스트"""
        # 여러 배포 기록 생성
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0"
        )
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.1.0"
        )
        
        # 이전 버전 조회
        previous_version = await deployment_history_service.get_previous_version(
            app_name="test-app",
            environment="staging"
        )
        
        assert previous_version is not None
        assert previous_version.image == "test-app:v1.0.0"

    async def test_create_rollback_record(self, deployment_history_service):
        """롤백 기록 생성 테스트"""
        # 원본 배포 기록 생성
        original_id = await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.1.0"
        )
        
        # 롤백 기록 생성
        rollback_id = await deployment_history_service.create_rollback_record(
            app_name="test-app",
            environment="staging",
            target_image="test-app:v1.0.0",
            rolled_back_from=original_id,
            rollback_reason="Test rollback"
        )
        
        assert rollback_id is not None
        assert rollback_id > 0

    async def test_get_deployment_stats(self, deployment_history_service):
        """배포 통계 조회 테스트"""
        # 여러 배포 기록 생성
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0"
        )
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.1.0"
        )
        
        # 통계 조회
        stats = await deployment_history_service.get_deployment_stats(
            app_name="test-app",
            environment="staging"
        )
        
        assert stats.total_deployments == 2
        assert stats.successful_deployments == 0  # 기본 상태는 PENDING
        assert stats.failed_deployments == 0
        assert stats.rollback_count == 0
        assert stats.success_rate == 0.0
        assert len(stats.recent_deployments) == 2

    async def test_query_deployments(self, deployment_history_service):
        """배포 히스토리 조회 테스트"""
        from models.deployment_history import DeploymentHistoryQuery
        
        # 여러 배포 기록 생성
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0"
        )
        await deployment_history_service.create_deployment_record(
            app_name="test-app",
            environment="production",
            image="test-app:v1.0.0"
        )
        
        # 쿼리 생성 및 실행
        query = DeploymentHistoryQuery(
            app_name="test-app",
            environment="staging",
            limit=10
        )
        
        deployments = await deployment_history_service.query_deployments(query)
        
        assert len(deployments) == 1
        assert deployments[0].environment == "staging"
