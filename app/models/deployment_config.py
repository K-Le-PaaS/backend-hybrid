"""
Deployment Configuration Model

Stores desired state for deployments including replica count.
This serves as the source of truth for deployment configurations
that should persist across deployments and rollbacks.
"""
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from datetime import datetime, timezone
from .base import Base


class DeploymentConfig(Base):
    """
    Deployment configuration for repositories.

    Stores desired state like replica count that should persist
    across deployments, rollbacks, and restarts.
    """
    __tablename__ = "deployment_configs"

    id = Column(Integer, primary_key=True, index=True)

    # Repository identification
    github_owner = Column(String, nullable=False, index=True)
    github_repo = Column(String, nullable=False, index=True)

    # Deployment configuration
    replica_count = Column(Integer, default=1, nullable=False)

    # Audit fields
    last_scaled_at = Column(DateTime, nullable=True)
    last_scaled_by = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Unique constraint: one config per repository
    __table_args__ = (
        UniqueConstraint('github_owner', 'github_repo', name='uq_owner_repo'),
    )

    def __repr__(self):
        return (
            f"<DeploymentConfig(id={self.id}, "
            f"repo={self.github_owner}/{self.github_repo}, "
            f"replicas={self.replica_count})>"
        )
