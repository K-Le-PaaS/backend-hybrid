"""Admin DB inspection API endpoints for production debugging."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from pydantic import BaseModel, Field

from ...database import get_db
from ...models.user_repository import UserRepository
from ...models.user_project_integration import UserProjectIntegration
from ...models.deployment_history import DeploymentHistory
from ...models.command_history import CommandHistory
from ...models.audit_log import AuditLogModel
from ...models.oauth_token import OAuthToken

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/db", tags=["admin-db"])


class TableInfo(BaseModel):
    """테이블 정보"""
    table_name: str
    row_count: int
    columns: List[str]


class QueryResult(BaseModel):
    """쿼리 결과"""
    columns: List[str]
    rows: List[Dict[str, Any]]
    total: int
    affected_rows: Optional[int] = None


@router.get("/tables", response_model=List[TableInfo], summary="모든 테이블 목록 조회")
def list_tables(db: Session = Depends(get_db)) -> List[TableInfo]:
    """
    데이터베이스의 모든 테이블과 기본 정보를 조회합니다.

    Returns:
        - table_name: 테이블 이름
        - row_count: 총 행 수
        - columns: 컬럼 목록
    """
    inspector = inspect(db.bind)
    tables = []

    for table_name in inspector.get_table_names():
        try:
            # Get row count
            count_query = text(f"SELECT COUNT(*) FROM {table_name}")
            row_count = db.execute(count_query).scalar() or 0

            # Get columns
            columns = [col["name"] for col in inspector.get_columns(table_name)]

            tables.append(TableInfo(
                table_name=table_name,
                row_count=row_count,
                columns=columns
            ))
        except Exception as e:
            logger.warning(f"Failed to inspect table {table_name}: {e}")
            continue

    return tables


@router.get("/user-repositories", summary="사용자 리포지토리 목록")
def get_user_repositories(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    limit: int = Query(100, ge=1, le=1000, description="최대 결과 수"),
    offset: int = Query(0, ge=0, description="결과 오프셋"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    사용자 리포지토리 연동 정보를 조회합니다.
    """
    query = db.query(UserRepository)

    if user_id:
        query = query.filter(UserRepository.user_id == user_id)

    total = query.count()
    repos = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "owner": r.owner,
                "repo": r.repo,
                "installation_id": r.installation_id,
                "repository_id": r.repository_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in repos
        ]
    }


@router.get("/project-integrations", summary="프로젝트 통합 정보")
def get_project_integrations(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    owner: Optional[str] = Query(None, description="GitHub owner로 필터"),
    repo: Optional[str] = Query(None, description="GitHub repo로 필터"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    프로젝트 통합 정보 (GitHub, SourceCommit 연동 등)를 조회합니다.
    """
    query = db.query(UserProjectIntegration)

    if user_id:
        query = query.filter(UserProjectIntegration.user_id == user_id)
    if owner:
        query = query.filter(UserProjectIntegration.github_owner == owner)
    if repo:
        query = query.filter(UserProjectIntegration.github_repo == repo)

    total = query.count()
    integrations = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": i.id,
                "user_id": i.user_id,
                "user_email": i.user_email,
                "github_owner": i.github_owner,
                "github_repo": i.github_repo,
                "github_full_name": i.github_full_name,
                "github_repository_id": i.github_repository_id,
                "github_installation_id": i.github_installation_id,
                "auto_deploy_enabled": i.auto_deploy_enabled,
                "sc_project_id": i.sc_project_id,
                "sc_repo_name": i.sc_repo_name,
                "sc_clone_url": i.sc_clone_url,
                "sc_repo_id": i.sc_repo_id,
                "build_project_id": i.build_project_id,
                "deploy_project_id": i.deploy_project_id,
                "pipeline_id": i.pipeline_id,
                "registry_url": i.registry_url,
                "image_repository": i.image_repository,
                "branch": i.branch,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            }
            for i in integrations
        ]
    }


@router.get("/deployment-histories", summary="배포 히스토리")
def get_deployment_histories(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    github_owner: Optional[str] = Query(None, description="GitHub owner로 필터"),
    github_repo: Optional[str] = Query(None, description="GitHub repo로 필터"),
    status: Optional[str] = Query(None, description="상태로 필터"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    배포 히스토리를 조회합니다.
    """
    query = db.query(DeploymentHistory)

    if user_id:
        query = query.filter(DeploymentHistory.user_id == user_id)
    if github_owner:
        query = query.filter(DeploymentHistory.github_owner == github_owner)
    if github_repo:
        query = query.filter(DeploymentHistory.github_repo == github_repo)
    if status:
        query = query.filter(DeploymentHistory.status == status)

    query = query.order_by(DeploymentHistory.created_at.desc())

    total = query.count()
    histories = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": h.id,
                "user_id": h.user_id,
                "github_owner": h.github_owner,
                "github_repo": h.github_repo,
                "repository": h.repository_name,  # property
                "github_commit_sha": h.github_commit_sha,
                "github_commit_message": h.github_commit_message,
                "github_commit_author": h.github_commit_author,
                "github_commit_url": h.github_commit_url,
                "status": h.status,
                "sourcecommit_status": h.sourcecommit_status,
                "sourcebuild_status": h.sourcebuild_status,
                "sourcedeploy_status": h.sourcedeploy_status,
                "image_name": h.image_name,
                "image_tag": h.image_tag,
                "image_url": h.image_url,
                "cluster_id": h.cluster_id,
                "namespace": h.namespace,
                "started_at": h.started_at.isoformat() if h.started_at else None,
                "completed_at": h.completed_at.isoformat() if h.completed_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "total_duration": h.total_duration,
                "error_message": h.error_message,
                "error_stage": h.error_stage,
                "is_rollback": h.is_rollback,
                "rollback_from_id": h.rollback_from_id,
            }
            for h in histories
        ]
    }


@router.get("/command-histories", summary="명령 히스토리")
def get_command_histories(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    status: Optional[str] = Query(None, description="상태로 필터 (success, error, pending)"),
    tool: Optional[str] = Query(None, description="도구명으로 필터"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    명령 히스토리를 조회합니다.
    """
    query = db.query(CommandHistory)

    if user_id:
        query = query.filter(CommandHistory.user_id == user_id)
    if status:
        query = query.filter(CommandHistory.status == status)
    if tool:
        query = query.filter(CommandHistory.tool == tool)

    query = query.order_by(CommandHistory.created_at.desc())

    total = query.count()
    commands = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "command_text": c.command_text,
                "tool": c.tool,
                "args": c.args,
                "status": c.status,
                "error_message": c.error_message,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "result": c.result,
            }
            for c in commands
        ]
    }


@router.get("/audit-logs", summary="감사 로그")
def get_audit_logs(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    action: Optional[str] = Query(None, description="액션으로 필터"),
    status: Optional[str] = Query(None, description="상태로 필터"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    감사 로그를 조회합니다.
    """
    query = db.query(AuditLogModel)

    if user_id:
        query = query.filter(AuditLogModel.user_id == user_id)
    if action:
        query = query.filter(AuditLogModel.action == action)
    if status:
        query = query.filter(AuditLogModel.result == status)
    
    query = query.order_by(AuditLogModel.timestamp.desc())

    total = query.count()
    logs = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": l.id,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "user_id": l.user_id,
                "action": l.action,
                "resource": l.resource,
                "status": l.status,
                "ip_address": l.ip_address,
                "details": l.details,
            }
            for l in logs
        ]
    }


@router.get("/oauth-tokens", summary="OAuth 토큰 정보")
def get_oauth_tokens(
    user_id: Optional[str] = Query(None, description="특정 사용자 ID로 필터"),
    provider: Optional[str] = Query(None, description="OAuth 제공자로 필터"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    OAuth 토큰 정보를 조회합니다 (민감한 정보는 마스킹).
    """
    query = db.query(OAuthToken)

    if user_id:
        query = query.filter(OAuthToken.user_id == user_id)
    if provider:
        query = query.filter(OAuthToken.provider == provider)

    total = query.count()
    tokens = query.offset(offset).limit(limit).all()

    def mask_token(token: str) -> str:
        """토큰 마스킹 (앞 4자리, 뒤 4자리만 표시)"""
        if not token or len(token) <= 8:
            return "****"
        return f"{token[:4]}...{token[-4:]}"

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "provider": t.provider,
                "access_token": mask_token(t.access_token) if t.access_token else None,
                "refresh_token": mask_token(t.refresh_token) if t.refresh_token else None,
                "token_type": t.token_type,
                "scope": t.scope,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tokens
        ]
    }


@router.get("/stats", summary="데이터베이스 통계")
def get_db_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    데이터베이스 전체 통계를 조회합니다.
    """
    try:
        stats = {
            "user_repositories": db.query(UserRepository).count(),
            "project_integrations": db.query(UserProjectIntegration).count(),
            "deployment_histories": db.query(DeploymentHistory).count(),
            "command_histories": db.query(CommandHistory).count(),
            "audit_logs": db.query(AuditLogModel).count(),
            "oauth_tokens": db.query(OAuthToken).count(),
        }

        # 최근 배포 통계
        recent_deployments = db.query(DeploymentHistory).order_by(
            DeploymentHistory.created_at.desc()
        ).limit(10).all()

        deployment_status_counts = {}
        for status in ["pending", "running", "success", "failed", "cancelled"]:
            count = db.query(DeploymentHistory).filter(
                DeploymentHistory.status == status
            ).count()
            deployment_status_counts[status] = count

        # 활성 사용자 수
        active_users = db.query(UserProjectIntegration.user_id).distinct().count()

        return {
            "table_counts": stats,
            "deployment_status": deployment_status_counts,
            "active_users": active_users,
            "recent_deployments": [
                {
                    "id": d.id,
                    "repository": d.repository_name,
                    "github_owner": d.github_owner,
                    "github_repo": d.github_repo,
                    "status": d.status,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in recent_deployments
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get DB stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class QueryRequest(BaseModel):
    """SQL 쿼리 요청"""
    query: str = Field(..., description="실행할 SQL 쿼리")
    limit: int = Field(100, ge=1, le=10000, description="SELECT 쿼리의 최대 결과 수")


@router.post("/query", summary="커스텀 SQL 쿼리 실행 (CRUD 모두 가능)", response_model=QueryResult)
def execute_custom_query(
    req: QueryRequest,
    db: Session = Depends(get_db)
) -> QueryResult:
    """
    커스텀 SQL 쿼리를 실행합니다.

    **모든 CRUD 작업이 가능합니다: SELECT, INSERT, UPDATE, DELETE**

    ⚠️ **주의사항**:
    - 프로덕션 데이터베이스에서 실행됩니다
    - DELETE, UPDATE, DROP 등의 작업은 복구 불가능할 수 있습니다
    - 트랜잭션이 자동으로 커밋되므로 신중하게 사용하세요

    **예시**:

    **SELECT**:
    ```sql
    SELECT * FROM user_project_integrations WHERE github_owner = 'K-Le-PaaS'
    SELECT COUNT(*) as total, status FROM deployment_histories GROUP BY status
    ```

    **INSERT**:
    ```sql
    INSERT INTO audit_logs (timestamp, user_id, action, resource, status)
    VALUES (datetime('now'), 'admin', 'test', 'test_resource', 'success')
    ```

    **UPDATE**:
    ```sql
    UPDATE user_project_integrations
    SET auto_deploy_enabled = 1
    WHERE github_owner = 'K-Le-PaaS' AND github_repo = 'test01'
    ```

    **DELETE**:
    ```sql
    DELETE FROM deployment_histories WHERE status = 'cancelled' AND created_at < datetime('now', '-30 days')
    ```
    """
    query = req.query.strip()
    query_upper = query.upper()

    try:
        # SELECT 쿼리인 경우
        if query_upper.startswith("SELECT"):
            # LIMIT 자동 추가 (없는 경우)
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {req.limit}"

            result = db.execute(text(query))
            rows = result.fetchall()

            if rows:
                columns = list(result.keys())
                rows_dict = [dict(zip(columns, row)) for row in rows]
            else:
                columns = []
                rows_dict = []

            return QueryResult(
                columns=columns,
                rows=rows_dict,
                total=len(rows_dict),
                affected_rows=None
            )

        # INSERT, UPDATE, DELETE 쿼리인 경우
        elif any(query_upper.startswith(cmd) for cmd in ["INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE"]):
            result = db.execute(text(query))
            db.commit()  # 명시적으로 커밋

            affected_rows = result.rowcount if hasattr(result, 'rowcount') else None

            logger.info(f"Executed non-SELECT query: {query[:100]}... | Affected rows: {affected_rows}")

            return QueryResult(
                columns=[],
                rows=[],
                total=0,
                affected_rows=affected_rows
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported query type. Supported: SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, TRUNCATE"
            )

    except Exception as e:
        db.rollback()  # 에러 발생 시 롤백
        logger.error(f"Query execution failed: {e} | Query: {query[:200]}")
        raise HTTPException(status_code=400, detail=f"Query failed: {str(e)}")


@router.get("/integration-detail/{integration_id}", summary="통합 상세 정보")
def get_integration_detail(
    integration_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    특정 프로젝트 통합의 상세 정보를 조회합니다.
    """
    integration = db.query(UserProjectIntegration).filter(
        UserProjectIntegration.id == integration_id
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    # 관련 배포 히스토리
    deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == integration.github_owner,
        DeploymentHistory.github_repo == integration.github_repo
    ).order_by(DeploymentHistory.created_at.desc()).limit(10).all()

    return {
        "integration": {
            "id": integration.id,
            "user_id": integration.user_id,
            "user_email": integration.user_email,
            "github_owner": integration.github_owner,
            "github_repo": integration.github_repo,
            "github_full_name": integration.github_full_name,
            "github_repository_id": integration.github_repository_id,
            "github_installation_id": integration.github_installation_id,
            "auto_deploy_enabled": integration.auto_deploy_enabled,
            "sc_project_id": integration.sc_project_id,
            "sc_repo_name": integration.sc_repo_name,
            "sc_clone_url": integration.sc_clone_url,
            "sc_repo_id": integration.sc_repo_id,
            "build_project_id": integration.build_project_id,
            "deploy_project_id": integration.deploy_project_id,
            "pipeline_id": integration.pipeline_id,
            "registry_url": integration.registry_url,
            "image_repository": integration.image_repository,
            "branch": integration.branch,
            "notes": integration.notes,
            "created_at": integration.created_at.isoformat() if integration.created_at else None,
            "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
        },
        "recent_deployments": [
            {
                "id": d.id,
                "github_commit_sha": d.github_commit_sha,
                "github_commit_message": d.github_commit_message,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "error_message": d.error_message,
                "error_stage": d.error_stage,
            }
            for d in deployments
        ]
    }
