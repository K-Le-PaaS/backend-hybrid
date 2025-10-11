from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

def _ensure_schema(db: Session) -> None:
    try:
        cols = db.execute(text("PRAGMA table_info(user_project_integrations)")).mappings().all()
        col_names = {str(c.get("name")) for c in cols}
        
        # Add missing columns if they don't exist
        if "sc_repo_id" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN sc_repo_id VARCHAR(255)"))
        if "build_project_id" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN build_project_id VARCHAR(255)"))
        if "deploy_project_id" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN deploy_project_id VARCHAR(255)"))
        if "pipeline_id" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN pipeline_id VARCHAR(255)"))
        if "registry_url" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN registry_url VARCHAR(512)"))
        if "image_repository" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN image_repository VARCHAR(512)"))
        if "branch" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN branch VARCHAR(100)"))
        if "auto_deploy_enabled" not in col_names:
            db.execute(text("ALTER TABLE user_project_integrations ADD COLUMN auto_deploy_enabled BOOLEAN DEFAULT 1"))
        
        db.commit()
    except Exception:
        # Best-effort; ignore if migration handled elsewhere
        db.rollback()
        pass
from ..models.user_project_integration import UserProjectIntegration


def upsert_integration(
    db: Session,
    *,
    user_id: str,
    user_email: Optional[str] = None,
    owner: str,
    repo: str,
    repository_id: Optional[str] = None,
    installation_id: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    sc_project_id: Optional[str] = None,
    sc_repo_name: Optional[str] = None,
    sc_clone_url: Optional[str] = None,
    sc_repo_id: Optional[str] = None,
    build_project_id: Optional[str] = None,
    deploy_project_id: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    registry_url: Optional[str] = None,
    image_repository: Optional[str] = None,
    branch: Optional[str] = None,
    auto_deploy_enabled: Optional[bool] = None,
) -> UserProjectIntegration:
    _ensure_schema(db)
    full_name = f"{owner}/{repo}"
    obj = (
        db.query(UserProjectIntegration)
        .filter(UserProjectIntegration.user_id == user_id, UserProjectIntegration.github_full_name == full_name)
        .first()
    )
    if not obj:
        obj = UserProjectIntegration(
            user_id=user_id,
            user_email=user_email,
            github_owner=owner,
            github_repo=repo,
            github_full_name=full_name,
        )
        db.add(obj)

    # update fields if provided
    if repository_id is not None:
        obj.github_repository_id = repository_id
    if installation_id is not None:
        obj.github_installation_id = installation_id
    if webhook_secret is not None:
        obj.github_webhook_secret = webhook_secret
    if sc_project_id is not None:
        obj.sc_project_id = sc_project_id
    if sc_repo_name is not None:
        obj.sc_repo_name = sc_repo_name
    if sc_clone_url is not None:
        obj.sc_clone_url = sc_clone_url
    if sc_repo_id is not None:
        obj.sc_repo_id = sc_repo_id
    if build_project_id is not None:
        obj.build_project_id = build_project_id
    if deploy_project_id is not None:
        obj.deploy_project_id = deploy_project_id
    if pipeline_id is not None:
        obj.pipeline_id = pipeline_id
    if registry_url is not None:
        obj.registry_url = registry_url
    if image_repository is not None:
        obj.image_repository = image_repository
    if branch is not None:
        obj.branch = branch
    if auto_deploy_enabled is not None:
        obj.auto_deploy_enabled = auto_deploy_enabled

    db.commit()
    db.refresh(obj)
    return obj


def get_integration(db: Session, *, user_id: str, owner: str, repo: str) -> Optional[UserProjectIntegration]:
    _ensure_schema(db)
    full_name = f"{owner}/{repo}"
    return (
        db.query(UserProjectIntegration)
        .filter(UserProjectIntegration.user_id == user_id, UserProjectIntegration.github_full_name == full_name)
        .first()
    )


def get_integration_by_installation(db: Session, *, installation_id: str, owner: str, repo: str) -> Optional[UserProjectIntegration]:
    _ensure_schema(db)
    full_name = f"{owner}/{repo}"
    return (
        db.query(UserProjectIntegration)
        .filter(UserProjectIntegration.github_installation_id == installation_id, UserProjectIntegration.github_full_name == full_name)
        .first()
    )


