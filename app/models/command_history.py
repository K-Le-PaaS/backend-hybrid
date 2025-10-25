"""명령어 히스토리 모델"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from pydantic import BaseModel
from .base import Base

# 한국 표준시 (KST) 타임존
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """현재 한국 시간(KST) 반환"""
    return datetime.now(KST).replace(tzinfo=None)  # SQLite는 timezone-naive datetime 사용


class CommandHistory(Base):
    """명령어 히스토리 테이블"""
    __tablename__ = "command_history"

    id = Column(Integer, primary_key=True, index=True)
    command_text = Column(Text, nullable=False, comment="사용자가 입력한 명령어")
    tool = Column(String(100), nullable=False, comment="실행된 도구명")
    args = Column(JSON, comment="명령어 인자")
    result = Column(JSON, comment="실행 결과")
    status = Column(String(20), nullable=False, comment="실행 상태 (success, error, pending)")
    error_message = Column(Text, comment="에러 메시지")
    user_id = Column(String(100), comment="사용자 ID")
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)


class CommandHistoryCreate(BaseModel):
    """명령어 히스토리 생성 모델"""
    command_text: str
    tool: str
    args: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    status: str = "pending"
    error_message: Optional[str] = None
    user_id: Optional[str] = None


class CommandHistoryResponse(BaseModel):
    """명령어 히스토리 응답 모델"""
    id: int
    command_text: str
    tool: str
    args: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    status: str
    error_message: Optional[str]
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
