"""
OAuth 액세스 토큰 저장 모델
"""

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from .base import Base


class OAuthToken(Base):
    """사용자별 OAuth 액세스 토큰 저장"""
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(50), nullable=False, index=True)
    access_token = Column(String(2048), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())





