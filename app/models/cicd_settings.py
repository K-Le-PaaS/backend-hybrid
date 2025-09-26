from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, JSON

from .base import Base


class CICDSettingsModel(Base):
    __tablename__ = "cicd_settings"

    id = Column(String, primary_key=True, default="default")
    build_enabled = Column(Boolean, default=True, nullable=False)
    test_enabled = Column(Boolean, default=True, nullable=False)
    deploy_enabled = Column(Boolean, default=True, nullable=False)
    env_vars = Column(JSON, default=dict)
    secrets_encrypted = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)









