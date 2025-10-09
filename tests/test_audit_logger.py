"""
감사 로그 서비스 테스트

보안 이벤트 추적 및 감사 로그 기능을 테스트합니다.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.audit_log import (
    AuditLogModel,
    AuditAction,
    AuditResource,
    AuditResult,
    AuditLogQuery
)
from app.services.audit_logger import AuditLogger, init_audit_logger


@pytest.fixture
def db_session():
    """테스트용 데이터베이스 세션 생성"""
    engine = create_engine("sqlite:///:memory:")
    AuditLogModel.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    return session


@pytest.fixture
def audit_logger_instance(db_session):
    """감사 로거 인스턴스 생성"""
    return AuditLogger(db_session)


class TestAuditLogger:
    """감사 로거 테스트 클래스"""
    
    async def test_log_event_success(self, audit_logger_instance):
        """감사 이벤트 기록 성공 테스트"""
        audit_id = await audit_logger_instance.log_event(
            user_id="klepaas-deployer",
            user_type="serviceaccount",
            source_ip="192.168.1.100",
            action=AuditAction.DEPLOY,
            resource_type=AuditResource.DEPLOYMENT,
            resource_name="myapp",
            namespace="klepaas-staging",
            result=AuditResult.SUCCESS,
            message="Deployment successful"
        )
        
        assert audit_id is not None
        assert audit_id > 0

    async def test_log_deployment_event(self, audit_logger_instance):
        """배포 이벤트 기록 테스트"""
        audit_id = await audit_logger_instance.log_deployment_event(
            user_id="klepaas-deployer",
            source_ip="192.168.1.100",
            action=AuditAction.CREATE,
            app_name="myapp",
            environment="staging",
            result=AuditResult.SUCCESS,
            request_body={"image": "myapp:latest", "replicas": 2}
        )
        
        assert audit_id is not None
        
        # 데이터베이스에서 확인
        audit_log = audit_logger_instance.db.query(AuditLogModel).filter(
            AuditLogModel.id == audit_id
        ).first()
        
        assert audit_log is not None
        assert audit_log.user_id == "klepaas-deployer"
        assert audit_log.action == "create"
        assert audit_log.resource_type == "deployment"
        assert audit_log.resource_name == "myapp"
        assert audit_log.namespace == "klepaas-staging"
        assert audit_log.result == "success"

    async def test_log_rollback_event(self, audit_logger_instance):
        """롤백 이벤트 기록 테스트"""
        audit_id = await audit_logger_instance.log_rollback_event(
            user_id="klepaas-rollbacker",
            source_ip="192.168.1.101",
            app_name="myapp",
            environment="staging",
            result=AuditResult.SUCCESS,
            metadata={"previous_image": "myapp:v1.0"}
        )
        
        assert audit_id is not None
        
        audit_log = audit_logger_instance.db.query(AuditLogModel).filter(
            AuditLogModel.id == audit_id
        ).first()
        
        assert audit_log.action == "rollback"
        assert audit_log.resource_name == "myapp"
        assert audit_log.extra_metadata["previous_image"] == "myapp:v1.0"

    async def test_log_monitoring_event(self, audit_logger_instance):
        """모니터링 이벤트 기록 테스트"""
        audit_id = await audit_logger_instance.log_monitoring_event(
            user_id="klepaas-monitor",
            source_ip="192.168.1.102",
            resource_type=AuditResource.POD,
            resource_name="myapp-pod-123",
            namespace="klepaas-staging",
            result=AuditResult.SUCCESS,
            query="up{job='myapp'}",
            metadata={"query_type": "prometheus"}
        )
        
        assert audit_id is not None
        
        audit_log = audit_logger_instance.db.query(AuditLogModel).filter(
            AuditLogModel.id == audit_id
        ).first()
        
        assert audit_log.action == "monitor"
        assert audit_log.resource_type == "pod"
        assert audit_log.extra_metadata["query"] == "up{job='myapp'}"
        assert audit_log.extra_metadata["query_type"] == "prometheus"

    async def test_log_auth_event(self, audit_logger_instance):
        """인증 이벤트 기록 테스트"""
        audit_id = await audit_logger_instance.log_auth_event(
            user_id="user123",
            source_ip="192.168.1.103",
            action=AuditAction.AUTHENTICATE,
            result=AuditResult.SUCCESS,
            metadata={"auth_method": "oauth2"}
        )
        
        assert audit_id is not None
        
        audit_log = audit_logger_instance.db.query(AuditLogModel).filter(
            AuditLogModel.id == audit_id
        ).first()
        
        assert audit_log.user_type == "user"
        assert audit_log.action == "authenticate"
        assert audit_log.resource_type == "user"
        assert audit_log.extra_metadata["auth_method"] == "oauth2"

    async def test_query_logs_with_filters(self, audit_logger_instance):
        """필터를 사용한 로그 조회 테스트"""
        # 테스트 데이터 생성
        await audit_logger_instance.log_event(
            user_id="user1",
            user_type="user",
            source_ip="192.168.1.100",
            action=AuditAction.CREATE,
            resource_type=AuditResource.DEPLOYMENT,
            result=AuditResult.SUCCESS
        )
        
        await audit_logger_instance.log_event(
            user_id="user2",
            user_type="user",
            source_ip="192.168.1.101",
            action=AuditAction.DELETE,
            resource_type=AuditResource.SERVICE,
            result=AuditResult.FAILURE
        )
        
        # 사용자별 필터
        query = AuditLogQuery(user_id="user1")
        logs = await audit_logger_instance.query_logs(query)
        
        assert len(logs) == 1
        assert logs[0].user_id == "user1"
        assert logs[0].action == "create"
        
        # 액션별 필터
        query = AuditLogQuery(action=AuditAction.DELETE)
        logs = await audit_logger_instance.query_logs(query)
        
        assert len(logs) == 1
        assert logs[0].action == "delete"
        assert logs[0].result == "failure"

    async def test_query_logs_with_time_range(self, audit_logger_instance):
        """시간 범위를 사용한 로그 조회 테스트"""
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(hours=1)
        future_time = now + timedelta(hours=1)
        
        # 과거 이벤트
        await audit_logger_instance.log_event(
            user_id="user1",
            user_type="user",
            source_ip="192.168.1.100",
            action=AuditAction.CREATE,
            resource_type=AuditResource.DEPLOYMENT,
            result=AuditResult.SUCCESS
        )
        
        # 시간 범위 쿼리
        query = AuditLogQuery(
            start_time=past_time,
            end_time=future_time
        )
        logs = await audit_logger_instance.query_logs(query)
        
        assert len(logs) >= 1

    async def test_get_stats(self, audit_logger_instance):
        """감사 로그 통계 조회 테스트"""
        # 테스트 데이터 생성
        await audit_logger_instance.log_event(
            user_id="user1",
            user_type="user",
            source_ip="192.168.1.100",
            action=AuditAction.CREATE,
            resource_type=AuditResource.DEPLOYMENT,
            result=AuditResult.SUCCESS
        )
        
        await audit_logger_instance.log_event(
            user_id="user2",
            user_type="user",
            source_ip="192.168.1.101",
            action=AuditAction.DELETE,
            resource_type=AuditResource.SERVICE,
            result=AuditResult.FAILURE
        )
        
        stats = await audit_logger_instance.get_stats()
        
        assert stats.total_count == 2
        assert stats.success_count == 1
        assert stats.failure_count == 1
        assert stats.error_count == 0
        assert "create" in stats.action_stats
        assert "delete" in stats.action_stats
        assert "deployment" in stats.resource_stats
        assert "service" in stats.resource_stats

    async def test_log_event_with_metadata(self, audit_logger_instance):
        """메타데이터가 포함된 이벤트 기록 테스트"""
        metadata = {
            "deployment_id": "deploy-123",
            "image_tag": "v1.2.3",
            "replicas": 3,
            "environment": "staging"
        }
        
        audit_id = await audit_logger_instance.log_event(
            user_id="klepaas-deployer",
            user_type="serviceaccount",
            source_ip="192.168.1.100",
            action=AuditAction.DEPLOY,
            resource_type=AuditResource.DEPLOYMENT,
            resource_name="myapp",
            namespace="klepaas-staging",
            result=AuditResult.SUCCESS,
            metadata=metadata
        )
        
        audit_log = audit_logger_instance.db.query(AuditLogModel).filter(
            AuditLogModel.id == audit_id
        ).first()
        
        assert audit_log.extra_metadata == metadata
        assert audit_log.extra_metadata["deployment_id"] == "deploy-123"
        assert audit_log.extra_metadata["image_tag"] == "v1.2.3"

    async def test_log_event_failure_handling(self, audit_logger_instance):
        """이벤트 기록 실패 처리 테스트"""
        # 잘못된 IP 주소로 실패 테스트
        with pytest.raises(ValueError, match="Invalid IP address format"):
            await audit_logger_instance.log_event(
                user_id="user1",
                user_type="user",
                source_ip="invalid-ip",
                action=AuditAction.CREATE,
                resource_type=AuditResource.DEPLOYMENT,
                result=AuditResult.SUCCESS
            )

    async def test_audit_log_query_pagination(self, audit_logger_instance):
        """감사 로그 페이징 테스트"""
        # 여러 이벤트 생성
        for i in range(5):
            await audit_logger_instance.log_event(
                user_id=f"user{i}",
                user_type="user",
                source_ip=f"192.168.1.{100 + i}",
                action=AuditAction.CREATE,
                resource_type=AuditResource.DEPLOYMENT,
                result=AuditResult.SUCCESS
            )
        
        # 첫 번째 페이지
        query = AuditLogQuery(limit=2, offset=0)
        logs = await audit_logger_instance.query_logs(query)
        assert len(logs) == 2
        
        # 두 번째 페이지
        query = AuditLogQuery(limit=2, offset=2)
        logs = await audit_logger_instance.query_logs(query)
        assert len(logs) == 2
        
        # 세 번째 페이지
        query = AuditLogQuery(limit=2, offset=4)
        logs = await audit_logger_instance.query_logs(query)
        assert len(logs) == 1

    def test_audit_logger_initialization(self, db_session):
        """감사 로거 초기화 테스트"""
        init_audit_logger(db_session)
        
        from app.services.audit_logger import get_audit_logger
        logger = get_audit_logger()
        
        assert logger is not None
        assert isinstance(logger, AuditLogger)

