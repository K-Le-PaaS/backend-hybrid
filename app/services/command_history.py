"""명령어 히스토리 서비스"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import logging
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models.command_history import CommandHistory, CommandHistoryCreate, CommandHistoryResponse

logger = logging.getLogger(__name__)


async def save_command_history(
    db: Session,
    command_text: str,
    tool: str,
    args: Dict[str, Any],
    result: Optional[Dict[str, Any]] = None,
    status: str = "pending",
    error_message: Optional[str] = None,
    user_id: Optional[str] = None
) -> CommandHistoryResponse:
    """명령어 히스토리를 저장합니다."""
    try:
        command_history = CommandHistory(
            command_text=command_text,
            tool=tool,
            args=args,
            result=result,
            status=status,
            error_message=error_message,
            user_id=user_id
        )
        
        db.add(command_history)
        db.commit()
        db.refresh(command_history)
        
        logger.info(f"Command history saved: {command_history.id}")
        
        return CommandHistoryResponse(
            id=command_history.id,
            command_text=command_history.command_text,
            tool=command_history.tool,
            args=command_history.args,
            result=command_history.result,
            status=command_history.status,
            error_message=command_history.error_message,
            user_id=command_history.user_id,
            created_at=command_history.created_at,
            updated_at=command_history.updated_at
        )
        
    except Exception as e:
        logger.error(f"Failed to save command history: {e}")
        db.rollback()
        raise


async def get_command_history(
    db: Session,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[CommandHistoryResponse]:
    """명령어 히스토리를 조회합니다."""
    try:
        query = db.query(CommandHistory)
        
        if user_id:
            query = query.filter(CommandHistory.user_id == user_id)
        
        command_histories = query.order_by(desc(CommandHistory.created_at)).offset(offset).limit(limit).all()
        
        return [
            CommandHistoryResponse(
                id=ch.id,
                command_text=ch.command_text,
                tool=ch.tool,
                args=ch.args,
                result=ch.result,
                status=ch.status,
                error_message=ch.error_message,
                user_id=ch.user_id,
                created_at=ch.created_at,
                updated_at=ch.updated_at
            )
            for ch in command_histories
        ]
        
    except Exception as e:
        logger.error(f"Failed to get command history: {e}")
        raise


async def get_command_by_id(db: Session, command_id: int) -> Optional[CommandHistoryResponse]:
    """특정 명령어 히스토리를 조회합니다."""
    try:
        command_history = db.query(CommandHistory).filter(CommandHistory.id == command_id).first()
        
        if not command_history:
            return None
        
        return CommandHistoryResponse(
            id=command_history.id,
            command_text=command_history.command_text,
            tool=command_history.tool,
            args=command_history.args,
            result=command_history.result,
            status=command_history.status,
            error_message=command_history.error_message,
            user_id=command_history.user_id,
            created_at=command_history.created_at,
            updated_at=command_history.updated_at
        )
        
    except Exception as e:
        logger.error(f"Failed to get command by id {command_id}: {e}")
        raise


async def update_command_status(
    db: Session,
    command_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None
) -> Optional[CommandHistoryResponse]:
    """명령어 실행 상태를 업데이트합니다."""
    try:
        command_history = db.query(CommandHistory).filter(CommandHistory.id == command_id).first()
        
        if not command_history:
            return None
        
        command_history.status = status
        if result is not None:
            command_history.result = result
        if error_message is not None:
            command_history.error_message = error_message
        command_history.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(command_history)
        
        return CommandHistoryResponse(
            id=command_history.id,
            command_text=command_history.command_text,
            tool=command_history.tool,
            args=command_history.args,
            result=command_history.result,
            status=command_history.status,
            error_message=command_history.error_message,
            user_id=command_history.user_id,
            created_at=command_history.created_at,
            updated_at=command_history.updated_at
        )
        
    except Exception as e:
        logger.error(f"Failed to update command status {command_id}: {e}")
        db.rollback()
        raise

