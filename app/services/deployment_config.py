"""
Deployment Configuration Service

Manages persistent deployment configuration like replica counts.
"""
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
import structlog

from ..models.deployment_config import DeploymentConfig

logger = structlog.get_logger(__name__)


class DeploymentConfigService:
    """
    Service for managing deployment configurations.

    Provides methods to get and set desired replica counts
    that persist across deployments and rollbacks.
    """

    def get_replica_count(
        self,
        db: Session,
        owner: str,
        repo: str
    ) -> int:
        """
        Get desired replica count for a repository.

        Priority:
        1. DB stored value (explicit desired state)
        2. Default value (1)

        Args:
            db: Database session
            owner: GitHub repository owner
            repo: GitHub repository name

        Returns:
            Desired replica count (defaults to 1 if not configured)
        """
        config = db.query(DeploymentConfig).filter(
            DeploymentConfig.github_owner == owner,
            DeploymentConfig.github_repo == repo
        ).first()

        if config:
            logger.info(
                "deployment_config_found",
                owner=owner,
                repo=repo,
                replicas=config.replica_count,
                last_scaled_at=config.last_scaled_at
            )
            return config.replica_count

        logger.info(
            "deployment_config_not_found_using_default",
            owner=owner,
            repo=repo,
            default_replicas=1
        )
        return 1

    def set_replica_count(
        self,
        db: Session,
        owner: str,
        repo: str,
        replica_count: int,
        user_id: str
    ) -> DeploymentConfig:
        """
        Save desired replica count after scaling operation.

        Creates new config if it doesn't exist, updates if it does.

        Args:
            db: Database session
            owner: GitHub repository owner
            repo: GitHub repository name
            replica_count: Desired number of replicas
            user_id: User who performed the scaling

        Returns:
            Updated or created DeploymentConfig instance
        """
        config = db.query(DeploymentConfig).filter(
            DeploymentConfig.github_owner == owner,
            DeploymentConfig.github_repo == repo
        ).first()

        if config:
            old_count = config.replica_count
            config.replica_count = replica_count
            config.last_scaled_at = datetime.now(timezone.utc)
            config.last_scaled_by = user_id
            config.updated_at = datetime.now(timezone.utc)

            logger.info(
                "deployment_config_updated",
                owner=owner,
                repo=repo,
                old_replicas=old_count,
                new_replicas=replica_count,
                user_id=user_id
            )
        else:
            config = DeploymentConfig(
                github_owner=owner,
                github_repo=repo,
                replica_count=replica_count,
                last_scaled_at=datetime.now(timezone.utc),
                last_scaled_by=user_id
            )
            db.add(config)

            logger.info(
                "deployment_config_created",
                owner=owner,
                repo=repo,
                replicas=replica_count,
                user_id=user_id
            )

        db.commit()
        db.refresh(config)
        return config

    def get_config(
        self,
        db: Session,
        owner: str,
        repo: str
    ) -> Optional[DeploymentConfig]:
        """
        Get full deployment configuration.

        Args:
            db: Database session
            owner: GitHub repository owner
            repo: GitHub repository name

        Returns:
            DeploymentConfig instance or None if not found
        """
        return db.query(DeploymentConfig).filter(
            DeploymentConfig.github_owner == owner,
            DeploymentConfig.github_repo == repo
        ).first()

    def delete_config(
        self,
        db: Session,
        owner: str,
        repo: str
    ) -> bool:
        """
        Delete deployment configuration.

        Args:
            db: Database session
            owner: GitHub repository owner
            repo: GitHub repository name

        Returns:
            True if deleted, False if not found
        """
        config = self.get_config(db, owner, repo)
        if config:
            db.delete(config)
            db.commit()
            logger.info(
                "deployment_config_deleted",
                owner=owner,
                repo=repo
            )
            return True
        return False
