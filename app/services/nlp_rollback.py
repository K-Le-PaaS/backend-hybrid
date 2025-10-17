"""
Natural Language Processing for Rollback Commands

자연어 롤백 명령을 파싱하고 처리하는 서비스
"""

import re
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException
import structlog

from .rollback import (
    rollback_to_commit,
    rollback_to_previous,
    get_rollback_candidates
)

logger = structlog.get_logger(__name__)


class RollbackCommandParser:
    """자연어 롤백 명령 파서"""

    # 롤백 키워드 패턴
    ROLLBACK_KEYWORDS = [
        "롤백", "rollback", "되돌리", "revert", "복구", "restore",
        "이전", "previous", "돌아가"
    ]

    # N번 전 패턴
    STEPS_BACK_PATTERNS = [
        r'(\d+)\s*번\s*전',  # "3번 전"
        r'(\d+)\s*steps?\s*back',  # "3 steps back"
        r'(\d+)\s*deployments?\s*ago',  # "3 deployments ago"
        r'(\d+)\s*versions?\s*ago',  # "3 versions ago"
    ]

    # 커밋 해시 패턴 (7-40자 hex)
    COMMIT_HASH_PATTERN = r'\b[0-9a-f]{7,40}\b'

    # 특정 키워드 패턴
    PREVIOUS_KEYWORDS = ["이전", "previous", "last", "최근"]
    LATEST_KEYWORDS = ["최신", "latest", "current"]

    @classmethod
    def is_rollback_command(cls, command: str) -> bool:
        """명령어가 롤백 관련인지 확인"""
        command_lower = command.lower()
        return any(keyword in command_lower for keyword in cls.ROLLBACK_KEYWORDS)

    @classmethod
    def parse_rollback_command(cls, command: str) -> Dict[str, Any]:
        """
        자연어 롤백 명령을 파싱하여 구조화된 데이터로 변환

        Returns:
            {
                "type": "steps_back" | "commit_sha" | "previous" | "list_candidates",
                "value": int | str | None,
                "confidence": float
            }
        """
        command_lower = command.lower()

        # 1. N번 전 패턴 매칭
        for pattern in cls.STEPS_BACK_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                steps = int(match.group(1))
                return {
                    "type": "steps_back",
                    "value": steps,
                    "confidence": 0.95
                }

        # 2. 커밋 해시 패턴 매칭
        match = re.search(cls.COMMIT_HASH_PATTERN, command_lower)
        if match:
            commit_sha = match.group(0)
            return {
                "type": "commit_sha",
                "value": commit_sha,
                "confidence": 0.90
            }

        # 3. "이전" 키워드
        if any(keyword in command_lower for keyword in cls.PREVIOUS_KEYWORDS):
            return {
                "type": "previous",
                "value": 1,  # 기본값: 1번 전
                "confidence": 0.85
            }

        # 4. 후보 목록 요청
        list_keywords = ["목록", "list", "show", "보여", "candidates", "옵션", "options"]
        if any(keyword in command_lower for keyword in list_keywords):
            return {
                "type": "list_candidates",
                "value": None,
                "confidence": 0.80
            }

        # 5. 매칭 실패 - 후보 목록 제공
        return {
            "type": "list_candidates",
            "value": None,
            "confidence": 0.5
        }


async def process_rollback_command(
    command: str,
    user_id: str,
    owner: str,
    repo: str,
    db: Session
) -> Dict[str, Any]:
    """
    자연어 롤백 명령을 처리하여 실제 롤백 수행

    Args:
        command: 자연어 롤백 명령 (예: "3번 전으로 롤백", "abc1234로 롤백")
        user_id: 사용자 ID
        owner: GitHub 저장소 소유자
        repo: GitHub 저장소 이름
        db: 데이터베이스 세션

    Returns:
        롤백 결과 또는 후보 목록
    """
    logger.info("nlp_rollback_command", command=command, owner=owner, repo=repo, user_id=user_id)

    # 1. 명령어 파싱
    parsed = RollbackCommandParser.parse_rollback_command(command)
    logger.info("nlp_rollback_parsed", parsed=parsed)

    # 2. 파싱 결과에 따라 처리
    try:
        if parsed["type"] == "steps_back":
            steps = parsed["value"]
            logger.info("nlp_rollback_executing", type="steps_back", steps=steps)
            result = await rollback_to_previous(
                owner=owner,
                repo=repo,
                steps_back=steps,
                db=db,
                user_id=user_id
            )
            return {
                "status": "success",
                "action": "rollback",
                "method": "steps_back",
                "steps": steps,
                "result": result,
                "message": f"{steps}번 전 배포로 롤백했습니다."
            }

        elif parsed["type"] == "commit_sha":
            commit_sha = parsed["value"]
            logger.info("nlp_rollback_executing", type="commit_sha", commit_sha=commit_sha)
            result = await rollback_to_commit(
                owner=owner,
                repo=repo,
                target_commit_sha=commit_sha,
                db=db,
                user_id=user_id
            )
            return {
                "status": "success",
                "action": "rollback",
                "method": "commit_sha",
                "commit_sha": commit_sha,
                "result": result,
                "message": f"커밋 {commit_sha[:7]}로 롤백했습니다."
            }

        elif parsed["type"] == "previous":
            logger.info("nlp_rollback_executing", type="previous")
            result = await rollback_to_previous(
                owner=owner,
                repo=repo,
                steps_back=1,
                db=db,
                user_id=user_id
            )
            return {
                "status": "success",
                "action": "rollback",
                "method": "previous",
                "result": result,
                "message": "이전 배포로 롤백했습니다."
            }

        elif parsed["type"] == "list_candidates":
            logger.info("nlp_rollback_listing_candidates")
            candidates = await get_rollback_candidates(
                owner=owner,
                repo=repo,
                db=db,
                limit=10
            )
            return {
                "status": "need_clarification",
                "action": "list_candidates",
                "candidates": candidates,
                "message": "롤백할 버전을 선택해주세요:",
                "suggestion": "예시: '3번 전으로 롤백' 또는 'abc1234로 롤백'"
            }

        else:
            logger.warning("nlp_rollback_unknown_type", parsed_type=parsed["type"])
            return {
                "status": "error",
                "message": "롤백 명령을 이해하지 못했습니다. 다시 시도해주세요.",
                "examples": [
                    "이전 버전으로 롤백해줘",
                    "3번 전으로 롤백",
                    "커밋 abc1234로 롤백"
                ]
            }

    except HTTPException as e:
        logger.error("nlp_rollback_http_error", status_code=e.status_code, detail=e.detail)
        return {
            "status": "error",
            "error_code": e.status_code,
            "message": str(e.detail)
        }

    except Exception as e:
        logger.error("nlp_rollback_unexpected_error", error=str(e), error_type=type(e).__name__)
        return {
            "status": "error",
            "message": f"롤백 처리 중 오류가 발생했습니다: {str(e)}"
        }


def extract_repository_from_command(command: str) -> Optional[tuple[str, str]]:
    """
    명령어에서 저장소 정보 추출 (선택적)

    Examples:
        "owner/repo를 3번 전으로 롤백" -> ("owner", "repo")
        "rollback owner/repo to abc1234" -> ("owner", "repo")

    Returns:
        (owner, repo) 튜플 또는 None
    """
    # owner/repo 패턴 매칭
    pattern = r'\b([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)\b'
    match = re.search(pattern, command)
    if match:
        return (match.group(1), match.group(2))
    return None
