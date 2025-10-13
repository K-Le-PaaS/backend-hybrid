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
    # 기본값: SQLite 파일 데이터베이스 (NFS 호환)
    # /data 디렉터리는 PVC로 마운트된 영구 저장소
    DATABASE_URL = "sqlite:////data/klepaas.db"

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
    import os
    import structlog
    from .models.base import Base
    from .models.audit_log import AuditLogModel
    from .models.deployment_history import DeploymentHistory
    
    logger = structlog.get_logger(__name__)
    
    try:
        # SQLite 파일의 디렉터리가 존재하는지 확인하고 생성
        if DATABASE_URL.startswith("sqlite:///"):
            db_path = DATABASE_URL.replace("sqlite:///", "")
            if db_path.startswith("/"):  # 절대 경로인 경우
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    logger.info(f"Creating database directory: {db_dir}")
                    os.makedirs(db_dir, exist_ok=True)
        
        # 모든 모델을 임포트하여 메타데이터에 등록
        logger.info(f"Initializing database: {DATABASE_URL}")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


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
