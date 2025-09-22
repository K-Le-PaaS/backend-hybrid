"""
감사 로그 데이터 모델

K-Le-PaaS의 보안 이벤트를 추적하기 위한 감사 로그 스키마를 정의합니다.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, String, DateTime, Text, JSON, Integer, Index
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class AuditAction(str, Enum):
    """감사 액션 타입"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    GET = "get"
    LIST = "list"
    PATCH = "patch"
    ROLLBACK = "rollback"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    AUTHENTICATE = "authenticate"
    AUTHORIZE = "authorize"


class AuditResource(str, Enum):
    """감사 리소스 타입"""
    DEPLOYMENT = "deployment"
    SERVICE = "service"
    CONFIGMAP = "configmap"
    SECRET = "secret"
    POD = "pod"
    EVENT = "event"
    USER = "user"
    SERVICE_ACCOUNT = "serviceaccount"
    ROLE = "role"
    ROLEBINDING = "rolebinding"
    NAMESPACE = "namespace"
    CLUSTER = "cluster"


class AuditResult(str, Enum):
    """감사 결과 타입"""
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"


class AuditLogModel(Base):
    """감사 로그 데이터베이스 모델"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    user_type = Column(String(50), nullable=False)  # user, serviceaccount, system
    source_ip = Column(String(45), nullable=False, index=True)  # IPv4/IPv6 지원
    user_agent = Column(String(500), nullable=True)
    action = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_name = Column(String(255), nullable=True, index=True)
    namespace = Column(String(255), nullable=True, index=True)
    result = Column(String(20), nullable=False, index=True)
    reason = Column(String(500), nullable=True)
    message = Column(Text, nullable=True)
    request_body = Column(JSON, nullable=True)
    response_body = Column(JSON, nullable=True)
    extra_metadata = Column(JSON, nullable=True)  # 추가 메타데이터
    
    # 복합 인덱스
    __table_args__ = (
        Index('idx_audit_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_audit_resource_timestamp', 'resource_type', 'resource_name', 'timestamp'),
        Index('idx_audit_action_result', 'action', 'result', 'timestamp'),
        Index('idx_audit_namespace_timestamp', 'namespace', 'timestamp'),
    )


class AuditLogCreate(BaseModel):
    """감사 로그 생성 요청 모델"""
    user_id: str = Field(..., min_length=1, max_length=255, description="사용자 또는 서비스계정 ID")
    user_type: str = Field(..., description="사용자 타입: user, serviceaccount, system")
    source_ip: str = Field(..., description="요청 소스 IP 주소")
    user_agent: Optional[str] = Field(None, max_length=500, description="사용자 에이전트")
    action: AuditAction = Field(..., description="수행된 액션")
    resource_type: AuditResource = Field(..., description="대상 리소스 타입")
    resource_name: Optional[str] = Field(None, max_length=255, description="대상 리소스 이름")
    namespace: Optional[str] = Field(None, max_length=255, description="네임스페이스")
    result: AuditResult = Field(..., description="액션 결과")
    reason: Optional[str] = Field(None, max_length=500, description="실패 이유")
    message: Optional[str] = Field(None, description="상세 메시지")
    request_body: Optional[Dict[str, Any]] = Field(None, description="요청 본문")
    response_body: Optional[Dict[str, Any]] = Field(None, description="응답 본문")
    extra_metadata: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")

    @field_validator("source_ip")
    @classmethod
    def validate_source_ip(cls, v: str) -> str:
        """IP 주소 형식 검증"""
        import ipaddress
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError("Invalid IP address format")

    @field_validator("user_type")
    @classmethod
    def validate_user_type(cls, v: str) -> str:
        """사용자 타입 검증"""
        allowed_types = ["user", "serviceaccount", "system"]
        if v not in allowed_types:
            raise ValueError(f"user_type must be one of: {allowed_types}")
        return v


class AuditLogResponse(BaseModel):
    """감사 로그 응답 모델"""
    id: int
    timestamp: datetime
    user_id: str
    user_type: str
    source_ip: str
    user_agent: Optional[str]
    action: str
    resource_type: str
    resource_name: Optional[str]
    namespace: Optional[str]
    result: str
    reason: Optional[str]
    message: Optional[str]
    request_body: Optional[Dict[str, Any]]
    response_body: Optional[Dict[str, Any]]
    extra_metadata: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


class AuditLogQuery(BaseModel):
    """감사 로그 조회 쿼리 모델"""
    user_id: Optional[str] = Field(None, description="사용자 ID 필터")
    action: Optional[AuditAction] = Field(None, description="액션 필터")
    resource_type: Optional[AuditResource] = Field(None, description="리소스 타입 필터")
    resource_name: Optional[str] = Field(None, description="리소스 이름 필터")
    namespace: Optional[str] = Field(None, description="네임스페이스 필터")
    result: Optional[AuditResult] = Field(None, description="결과 필터")
    start_time: Optional[datetime] = Field(None, description="시작 시간")
    end_time: Optional[datetime] = Field(None, description="종료 시간")
    limit: int = Field(default=100, ge=1, le=1000, description="조회 제한")
    offset: int = Field(default=0, ge=0, description="오프셋")


class AuditLogStats(BaseModel):
    """감사 로그 통계 모델"""
    total_count: int
    success_count: int
    failure_count: int
    error_count: int
    unauthorized_count: int
    forbidden_count: int
    action_stats: Dict[str, int]
    resource_stats: Dict[str, int]
    user_stats: Dict[str, int]
    time_range: Dict[str, datetime]
