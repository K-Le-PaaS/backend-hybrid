"""
대화형 인터랙션 세션 관리

Redis를 사용하여 멀티턴 대화 상태를 관리하고,
확인 대기, 비용 추정 등의 상태를 추적합니다.
"""

from enum import Enum
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
import structlog


class DateTimeEncoder(json.JSONEncoder):
    """datetime 객체를 JSON 직렬화 가능한 형태로 변환하는 커스텀 인코더"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

logger = structlog.get_logger(__name__)


class ConversationState(Enum):
    """대화 상태"""
    IDLE = "idle"
    INTERPRETING = "interpreting"
    ESTIMATING = "estimating"
    WAITING_CONFIRMATION = "waiting_confirmation"
    IN_PROGRESS = "in_progress"  # 대화형 플로우 진행 중 (예: 도메인 변경)
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class ConversationManager:
    """대화 세션 관리자"""

    def __init__(self, redis_client):
        """
        Args:
            redis_client: Redis 클라이언트 인스턴스
        """
        self.redis = redis_client
        self.ttl = 1800  # 30분 (세션 만료 시간)

    def _get_key(self, user_id: str, session_id: str) -> str:
        """Redis 키 생성"""
        return f"conversation:{user_id}:{session_id}"

    async def create_session(self, user_id: str) -> str:
        """
        새 대화 세션 생성

        Args:
            user_id: 사용자 ID

        Returns:
            생성된 세션 ID
        """
        session_id = str(uuid.uuid4())
        key = self._get_key(user_id, session_id)

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "state": ConversationState.IDLE.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "conversation_history": [],
            "pending_action": None,
            "context": {}
        }

        self.redis.setex(
            key,
            self.ttl,
            json.dumps(session_data, ensure_ascii=False, cls=DateTimeEncoder)
        )

        logger.info(
            "conversation_session_created",
            user_id=user_id,
            session_id=session_id
        )

        return session_id

    async def get_session(
        self,
        user_id: str,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        세션 조회

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID

        Returns:
            세션 데이터 또는 None
        """
        key = self._get_key(user_id, session_id)
        data = self.redis.get(key)

        if not data:
            logger.warning(
                "conversation_session_not_found",
                user_id=user_id,
                session_id=session_id
            )
            return None

        return json.loads(data)

    async def update_state(
        self,
        user_id: str,
        session_id: str,
        new_state: ConversationState,
        pending_action: Optional[Dict] = None
    ):
        """
        세션 상태 업데이트

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
            new_state: 새로운 상태
            pending_action: 대기 중인 작업 정보 (선택)
        """
        session = await self.get_session(user_id, session_id)
        if not session:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        old_state = session["state"]
        session["state"] = new_state.value
        session["updated_at"] = datetime.now().isoformat()

        if pending_action is not None:
            session["pending_action"] = pending_action

        key = self._get_key(user_id, session_id)
        self.redis.setex(
            key,
            self.ttl,
            json.dumps(session, ensure_ascii=False, cls=DateTimeEncoder)
        )

        logger.info(
            "conversation_state_updated",
            user_id=user_id,
            session_id=session_id,
            old_state=old_state,
            new_state=new_state.value
        )

    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,  # "user" or "assistant"
        content: str,
        action: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        """
        대화 히스토리에 메시지 추가

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
            role: 메시지 역할 ("user" 또는 "assistant")
            content: 메시지 내용
            action: 액션 타입 (선택)
            metadata: 추가 메타데이터 (선택)
        """
        session = await self.get_session(user_id, session_id)
        if not session:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        if action:
            message["action"] = action

        if metadata:
            message["metadata"] = metadata

        session["conversation_history"].append(message)
        session["updated_at"] = datetime.now().isoformat()

        key = self._get_key(user_id, session_id)
        self.redis.setex(
            key,
            self.ttl,
            json.dumps(session, ensure_ascii=False, cls=DateTimeEncoder)
        )

        logger.debug(
            "conversation_message_added",
            user_id=user_id,
            session_id=session_id,
            role=role,
            action=action
        )

    async def update_context(
        self,
        user_id: str,
        session_id: str,
        context_updates: Dict[str, Any]
    ):
        """
        대화 컨텍스트 업데이트

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
            context_updates: 업데이트할 컨텍스트 정보
        """
        session = await self.get_session(user_id, session_id)
        if not session:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        session["context"].update(context_updates)
        session["updated_at"] = datetime.now().isoformat()

        key = self._get_key(user_id, session_id)
        self.redis.setex(
            key,
            self.ttl,
            json.dumps(session, ensure_ascii=False, cls=DateTimeEncoder)
        )

    async def get_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        대화 히스토리 조회

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
            limit: 최대 메시지 수 (선택)

        Returns:
            메시지 리스트
        """
        session = await self.get_session(user_id, session_id)
        if not session:
            return []

        history = session["conversation_history"]

        if limit:
            return history[-limit:]

        return history

    async def clear_pending_action(
        self,
        user_id: str,
        session_id: str
    ):
        """
        대기 중인 작업 정보 제거

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
        """
        session = await self.get_session(user_id, session_id)
        if not session:
            return

        session["pending_action"] = None
        session["updated_at"] = datetime.now().isoformat()

        key = self._get_key(user_id, session_id)
        self.redis.setex(
            key,
            self.ttl,
            json.dumps(session, ensure_ascii=False, cls=DateTimeEncoder)
        )

    async def delete_session(
        self,
        user_id: str,
        session_id: str
    ):
        """
        세션 삭제

        Args:
            user_id: 사용자 ID
            session_id: 세션 ID
        """
        key = self._get_key(user_id, session_id)
        self.redis.delete(key)

        logger.info(
            "conversation_session_deleted",
            user_id=user_id,
            session_id=session_id
        )
