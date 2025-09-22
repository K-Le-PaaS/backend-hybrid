"""
감사 로그 서비스

K-Le-PaaS의 보안 이벤트를 기록하고 관리하는 서비스입니다.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from ..models.audit_log import (
    AuditLogModel,
    AuditLogCreate,
    AuditLogResponse,
    AuditLogQuery,
    AuditLogStats,
    AuditAction,
    AuditResource,
    AuditResult
)
from ..core.config import get_settings

logger = structlog.get_logger(__name__)


class AuditLogger:
    """감사 로그 관리 클래스"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.settings = get_settings()

    async def log_event(
        self,
        user_id: str,
        user_type: str,
        source_ip: str,
        action: AuditAction,
        resource_type: AuditResource,
        result: AuditResult,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        reason: Optional[str] = None,
        message: Optional[str] = None,
        request_body: Optional[Dict[str, Any]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """감사 이벤트를 기록합니다."""
        try:
            # 감사 로그 생성
            audit_data = AuditLogCreate(
                user_id=user_id,
                user_type=user_type,
                source_ip=source_ip,
                user_agent=user_agent,
                action=action,
                resource_type=resource_type,
                resource_name=resource_name,
                namespace=namespace,
                result=result,
                reason=reason,
                message=message,
                request_body=request_body,
                response_body=response_body,
                extra_metadata=metadata
            )
            
            # 데이터베이스에 저장
            audit_log = AuditLogModel(
                timestamp=datetime.now(timezone.utc),
                user_id=audit_data.user_id,
                user_type=audit_data.user_type,
                source_ip=audit_data.source_ip,
                user_agent=audit_data.user_agent,
                action=audit_data.action.value,
                resource_type=audit_data.resource_type.value,
                resource_name=audit_data.resource_name,
                namespace=audit_data.namespace,
                result=audit_data.result.value,
                reason=audit_data.reason,
                message=audit_data.message,
                request_body=audit_data.request_body,
                response_body=audit_data.response_body,
                extra_metadata=audit_data.extra_metadata
            )
            
            self.db.add(audit_log)
            self.db.commit()
            self.db.refresh(audit_log)
            
            # 구조화된 로그 기록
            logger.info(
                "audit_event_logged",
                audit_id=audit_log.id,
                user_id=user_id,
                action=action.value,
                resource_type=resource_type.value,
                resource_name=resource_name,
                namespace=namespace,
                result=result.value,
                timestamp=audit_log.timestamp.isoformat()
            )
            
            return audit_log.id
            
        except Exception as e:
            logger.error(
                "audit_log_failed",
                error=str(e),
                user_id=user_id,
                action=action.value,
                resource_type=resource_type.value
            )
            raise

    async def log_deployment_event(
        self,
        user_id: str,
        source_ip: str,
        action: AuditAction,
        app_name: str,
        environment: str,
        result: AuditResult,
        reason: Optional[str] = None,
        request_body: Optional[Dict[str, Any]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """배포 관련 감사 이벤트를 기록합니다."""
        return await self.log_event(
            user_id=user_id,
            user_type="serviceaccount",
            source_ip=source_ip,
            action=action,
            resource_type=AuditResource.DEPLOYMENT,
            resource_name=app_name,
            namespace=f"klepaas-{environment}",
            result=result,
            reason=reason,
            message=f"Deployment {action.value} for {app_name} in {environment}",
            request_body=request_body,
            response_body=response_body,
            metadata=metadata
        )

    async def log_rollback_event(
        self,
        user_id: str,
        source_ip: str,
        app_name: str,
        environment: str,
        result: AuditResult,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """롤백 관련 감사 이벤트를 기록합니다."""
        return await self.log_event(
            user_id=user_id,
            user_type="serviceaccount",
            source_ip=source_ip,
            action=AuditAction.ROLLBACK,
            resource_type=AuditResource.DEPLOYMENT,
            resource_name=app_name,
            namespace=f"klepaas-{environment}",
            result=result,
            reason=reason,
            message=f"Rollback for {app_name} in {environment}",
            metadata=metadata
        )

    async def log_monitoring_event(
        self,
        user_id: str,
        source_ip: str,
        resource_type: AuditResource,
        resource_name: str,
        namespace: str,
        result: AuditResult,
        query: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """모니터링 관련 감사 이벤트를 기록합니다."""
        return await self.log_event(
            user_id=user_id,
            user_type="serviceaccount",
            source_ip=source_ip,
            action=AuditAction.MONITOR,
            resource_type=resource_type,
            resource_name=resource_name,
            namespace=namespace,
            result=result,
            message=f"Monitoring query for {resource_name}",
            metadata={**(metadata or {}), "query": query}
        )

    async def log_auth_event(
        self,
        user_id: str,
        source_ip: str,
        action: AuditAction,
        result: AuditResult,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """인증/인가 관련 감사 이벤트를 기록합니다."""
        return await self.log_event(
            user_id=user_id,
            user_type="user",
            source_ip=source_ip,
            action=action,
            resource_type=AuditResource.USER,
            resource_name=user_id,
            result=result,
            reason=reason,
            message=f"Authentication/Authorization {action.value}",
            metadata=metadata
        )

    async def query_logs(self, query: AuditLogQuery) -> List[AuditLogResponse]:
        """감사 로그를 조회합니다."""
        try:
            # 기본 쿼리
            db_query = self.db.query(AuditLogModel)
            
            # 필터 적용
            if query.user_id:
                db_query = db_query.filter(AuditLogModel.user_id == query.user_id)
            
            if query.action:
                db_query = db_query.filter(AuditLogModel.action == query.action.value)
            
            if query.resource_type:
                db_query = db_query.filter(AuditLogModel.resource_type == query.resource_type.value)
            
            if query.resource_name:
                db_query = db_query.filter(AuditLogModel.resource_name == query.resource_name)
            
            if query.namespace:
                db_query = db_query.filter(AuditLogModel.namespace == query.namespace)
            
            if query.result:
                db_query = db_query.filter(AuditLogModel.result == query.result.value)
            
            if query.start_time:
                db_query = db_query.filter(AuditLogModel.timestamp >= query.start_time)
            
            if query.end_time:
                db_query = db_query.filter(AuditLogModel.timestamp <= query.end_time)
            
            # 정렬 및 페이징
            db_query = db_query.order_by(desc(AuditLogModel.timestamp))
            db_query = db_query.offset(query.offset).limit(query.limit)
            
            # 결과 조회
            logs = db_query.all()
            
            return [
                AuditLogResponse(
                    id=log.id,
                    timestamp=log.timestamp,
                    user_id=log.user_id,
                    user_type=log.user_type,
                    source_ip=log.source_ip,
                    user_agent=log.user_agent,
                    action=log.action,
                    resource_type=log.resource_type,
                    resource_name=log.resource_name,
                    namespace=log.namespace,
                    result=log.result,
                    reason=log.reason,
                    message=log.message,
                    request_body=log.request_body,
                    response_body=log.response_body,
                    extra_metadata=log.extra_metadata
                )
                for log in logs
            ]
            
        except Exception as e:
            logger.error("audit_log_query_failed", error=str(e), query=query.model_dump())
            raise

    async def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> AuditLogStats:
        """감사 로그 통계를 조회합니다."""
        try:
            # 기본 쿼리
            base_query = self.db.query(AuditLogModel)
            
            if start_time:
                base_query = base_query.filter(AuditLogModel.timestamp >= start_time)
            
            if end_time:
                base_query = base_query.filter(AuditLogModel.timestamp <= end_time)
            
            # 전체 카운트
            total_count = base_query.count()
            
            # 결과별 카운트
            success_count = base_query.filter(AuditLogModel.result == AuditResult.SUCCESS.value).count()
            failure_count = base_query.filter(AuditLogModel.result == AuditResult.FAILURE.value).count()
            error_count = base_query.filter(AuditLogModel.result == AuditResult.ERROR.value).count()
            unauthorized_count = base_query.filter(AuditLogModel.result == AuditResult.UNAUTHORIZED.value).count()
            forbidden_count = base_query.filter(AuditLogModel.result == AuditResult.FORBIDDEN.value).count()
            
            # 액션별 통계
            action_stats = {}
            action_results = (
                base_query
                .with_entities(AuditLogModel.action, func.count(AuditLogModel.id))
                .group_by(AuditLogModel.action)
                .all()
            )
            for action, count in action_results:
                action_stats[action] = count
            
            # 리소스별 통계
            resource_stats = {}
            resource_results = (
                base_query
                .with_entities(AuditLogModel.resource_type, func.count(AuditLogModel.id))
                .group_by(AuditLogModel.resource_type)
                .all()
            )
            for resource, count in resource_results:
                resource_stats[resource] = count
            
            # 사용자별 통계
            user_stats = {}
            user_results = (
                base_query
                .with_entities(AuditLogModel.user_id, func.count(AuditLogModel.id))
                .group_by(AuditLogModel.user_id)
                .all()
            )
            for user, count in user_results:
                user_stats[user] = count
            
            # 시간 범위
            time_range = {}
            if start_time:
                time_range["start"] = start_time
            if end_time:
                time_range["end"] = end_time
            
            return AuditLogStats(
                total_count=total_count,
                success_count=success_count,
                failure_count=failure_count,
                error_count=error_count,
                unauthorized_count=unauthorized_count,
                forbidden_count=forbidden_count,
                action_stats=action_stats,
                resource_stats=resource_stats,
                user_stats=user_stats,
                time_range=time_range
            )
            
        except Exception as e:
            logger.error("audit_log_stats_failed", error=str(e))
            raise


# 전역 감사 로거 인스턴스 (의존성 주입용)
audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """감사 로거 인스턴스를 반환합니다."""
    if audit_logger is None:
        raise RuntimeError("AuditLogger not initialized")
    return audit_logger


def init_audit_logger(db_session: Session) -> None:
    """감사 로거를 초기화합니다."""
    global audit_logger
    audit_logger = AuditLogger(db_session)
