"""
데이터베이스 설정 및 초기화

SQLAlchemy 엔진, 세션, 그리고 모델 초기화를 관리합니다.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from .core.config import get_settings

settings = get_settings()

# 데이터베이스 URL 설정
if settings.database_url:
    DATABASE_URL = settings.database_url
else:
    # 기본값: SQLite 인메모리 데이터베이스 (테스트용)
    DATABASE_URL = "sqlite:///./test.db"

# SQLite용 엔진 설정
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False  # 디버그 모드 비활성화
    )
else:
    # PostgreSQL용 엔진 설정
    engine = create_engine(
        DATABASE_URL,
        echo=False,  # 디버그 모드 비활성화
        pool_pre_ping=True
    )

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """데이터베이스 세션 의존성"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """데이터베이스 테이블을 생성합니다."""
    from .models.base import Base
    from .models.audit_log import AuditLogModel
    from .models.deployment_history import DeploymentHistoryModel
    
    # 모든 모델을 임포트하여 메타데이터에 등록
    Base.metadata.create_all(bind=engine)


def init_services(db_session: Session):
    """서비스들을 초기화합니다."""
    from .services.audit_logger import init_audit_logger
    from .services.deployment_history import init_deployment_history_service
    from .services.kubernetes_watcher import init_kubernetes_watcher
    from .websocket.deployment_monitor import init_deployment_monitor_manager
    
    # 서비스 초기화
    init_audit_logger(db_session)
    init_deployment_history_service(db_session)
    init_kubernetes_watcher()
    init_deployment_monitor_manager()
