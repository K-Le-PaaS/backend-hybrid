"""
배포 히스토리 서비스 간단 테스트

DeploymentHistoryService의 기본 기능을 테스트합니다.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 직접 import
from app.models.base import Base
from app.models.deployment_history import (
    DeploymentHistoryModel,
    ImageTagType,
    DeploymentStatus
)
from app.services.deployment_history import DeploymentHistoryService


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
            deployment_reason="Test deployment"
        )
        
        assert deployment_id is not None
        assert deployment_id > 0

    async def test_extract_image_tag_semver(self, deployment_history_service):
        """SemVer 이미지 태그 추출 테스트"""
        image = "test-app:v1.2.3"
        tag, tag_type = deployment_history_service._extract_image_tag(image)
        
        assert tag == "v1.2.3"
        assert tag_type == ImageTagType.SEMVER

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
        
        # 최근 버전 조회
        recent_versions = await deployment_history_service.get_recent_versions(
            app_name="test-app",
            environment="staging",
            limit=2
        )
        
        assert len(recent_versions) == 2
        assert recent_versions[0].image == "test-app:v1.1.0"  # 최신 버전
        assert recent_versions[1].image == "test-app:v1.0.0"  # 두 번째 최신 버전
