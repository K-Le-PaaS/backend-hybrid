"""
Notification and NotificationReport 모델

인프라 모니터링 알림과 스냅샷 보고서를 저장하는 모델입니다.
"""

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from datetime import datetime, timezone, timedelta
from .base import Base

# 한국 표준시 (KST) 타임존
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """현재 한국 시간(KST) 반환"""
    return datetime.now(KST).replace(tzinfo=None)  # SQLite는 timezone-naive datetime 사용


class Notification(Base):
    """모니터링 알림 모델"""
    
    __tablename__ = "notifications"
    
    id = Column(String(255), primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(50), nullable=False, index=True)  # critical, warning, info
    source = Column(String(255), nullable=True)  # Prometheus, Kubernetes, etc.
    status = Column(String(50), nullable=False, default="firing", index=True)  # firing, resolved
    labels = Column(JSON, nullable=True)  # 추가 메타데이터
    created_at = Column(DateTime, default=get_kst_now, index=True)
    resolved_at = Column(DateTime, nullable=True)
    
    # 복합 인덱스
    __table_args__ = (
        Index('idx_notification_severity_status', 'severity', 'status'),
        Index('idx_notification_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Notification(id={self.id}, severity={self.severity}, status={self.status})>"


class NotificationReport(Base):
    """알림 스냅샷 보고서 모델"""
    
    __tablename__ = "notification_reports"
    
    id = Column(String(255), primary_key=True, index=True)
    notification_id = Column(String(255), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    cluster = Column(String(255), nullable=True, index=True)
    summary = Column(Text, nullable=True)  # 보고서 요약
    snapshot_json = Column(JSON, nullable=False)  # 전체 스냅샷 데이터
    created_at = Column(DateTime, default=get_kst_now, index=True)
    
    # 복합 인덱스
    __table_args__ = (
        Index('idx_report_notification_created', 'notification_id', 'created_at'),
        Index('idx_report_cluster', 'cluster'),
    )
    
    def __repr__(self):
        return f"<NotificationReport(id={self.id}, notification_id={self.notification_id})>"

