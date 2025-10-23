"""
데이터베이스 설정 및 초기화

SQLAlchemy 엔진, 세션, 그리고 모델 초기화를 관리합니다.
"""

import os
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import text

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
        connect_args={
            "check_same_thread": False,
            "timeout": 30  # 30초 대기 (기본값: 5초)
        },
        poolclass=StaticPool,
        echo=False  # 디버그 모드 비활성화
    )

    # SQLite PRAGMA 설정 (동시성 개선)
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """SQLite 연결 시 WAL 모드와 busy_timeout을 설정합니다."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")  # WAL 모드 활성화 (동시성 크게 개선)
        cursor.execute("PRAGMA busy_timeout = 30000")  # 30초 (밀리초 단위)
        cursor.execute("PRAGMA synchronous = NORMAL")  # 성능 향상
        cursor.close()
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
    from .models.user_slack_config import UserSlackConfig
    
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

        # Lightweight migration: ensure new columns exist on existing tables
        try:
            _ensure_user_slack_config_columns()
        except Exception as e:
            logger.warning(f"UserSlackConfig column ensure failed: {e}")

        try:
            _ensure_deployment_history_columns()
        except Exception as e:
            logger.warning(f"DeploymentHistory column ensure failed: {e}")
        logger.info("Database tables created successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def init_services(db_session: Session):
    """서비스들을 초기화합니다."""
    from .services.audit_logger import init_audit_logger
    from .services.deployment_history import init_deployment_history_service
    from .services.kubernetes_watcher import (
        init_kubernetes_watcher,
        get_kubernetes_watcher,
        update_deployment_history_on_success
    )
    from .websocket.deployment_monitor import init_deployment_monitor_manager

    # 서비스 초기화
    init_audit_logger(db_session)
    init_deployment_history_service(db_session)
    init_kubernetes_watcher()
    init_deployment_monitor_manager()

    # Kubernetes Watcher 이벤트 핸들러 등록
    try:
        watcher = get_kubernetes_watcher()
        watcher.add_event_handler('deployment', update_deployment_history_on_success)
    except RuntimeError:
        # Watcher 초기화 실패 시 (kubeconfig 없는 경우 등)
        pass


def _ensure_user_slack_config_columns() -> None:
    """Ensure recently added columns exist for UserSlackConfig.

    This is a minimal, safe migration for SQLite/Postgres: add dm_enabled (BOOLEAN) and dm_user_id (TEXT)
    columns if they are missing. It does nothing if the table doesn't exist yet or columns already exist.
    """
    try:
        with engine.connect() as conn:
            # Detect columns (SQLite: PRAGMA; Postgres: information_schema)
            dialect = engine.dialect.name
            existing_cols: set[str] = set()
            if dialect == "sqlite":
                res = conn.execute(text("PRAGMA table_info('user_slack_configs')"))
                existing_cols = {row[1] for row in res.fetchall()}
            else:
                res = conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'user_slack_configs'
                        """
                    )
                )
                existing_cols = {row[0] for row in res.fetchall()}

            # Add missing columns
            if "dm_enabled" not in existing_cols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE user_slack_configs ADD COLUMN dm_enabled BOOLEAN DEFAULT 1"))
                else:
                    conn.execute(text("ALTER TABLE user_slack_configs ADD COLUMN dm_enabled BOOLEAN DEFAULT TRUE"))
            if "dm_user_id" not in existing_cols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE user_slack_configs ADD COLUMN dm_user_id TEXT"))
                else:
                    conn.execute(text("ALTER TABLE user_slack_configs ADD COLUMN dm_user_id VARCHAR(255)"))
            conn.commit()
    except Exception:
        # Best-effort; do not crash app on migration failure
        raise


def _ensure_deployment_history_columns() -> None:
    """Ensure recently added columns exist for DeploymentHistory.

    This is a minimal, safe migration for SQLite/Postgres: add pipeline_id (VARCHAR) and pipeline_history_id (INTEGER)
    columns if they are missing. It does nothing if the table doesn't exist yet or columns already exist.
    """
    try:
        with engine.connect() as conn:
            # Detect columns (SQLite: PRAGMA; Postgres: information_schema)
            dialect = engine.dialect.name
            existing_cols: set[str] = set()
            if dialect == "sqlite":
                res = conn.execute(text("PRAGMA table_info('deployment_histories')"))
                existing_cols = {row[1] for row in res.fetchall()}
            else:
                res = conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'deployment_histories'
                        """
                    )
                )
                existing_cols = {row[0] for row in res.fetchall()}

            # Add missing columns
            if "pipeline_id" not in existing_cols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE deployment_histories ADD COLUMN pipeline_id VARCHAR(255)"))
                else:
                    conn.execute(text("ALTER TABLE deployment_histories ADD COLUMN pipeline_id VARCHAR(255)"))
            if "pipeline_history_id" not in existing_cols:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE deployment_histories ADD COLUMN pipeline_history_id INTEGER"))
                else:
                    conn.execute(text("ALTER TABLE deployment_histories ADD COLUMN pipeline_history_id INTEGER"))
            conn.commit()
    except Exception:
        # Best-effort; do not crash app on migration failure
        raise
