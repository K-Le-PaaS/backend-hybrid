"""
Rollback API Endpoints

배포 롤백을 위한 REST API 엔드포인트
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import structlog

from ...database import get_db
from ...services.rollback import (
    rollback_to_commit,
    rollback_to_previous,
    get_rollback_candidates
)

router = APIRouter()
logger = structlog.get_logger(__name__)


# Request/Response Models
class RollbackToCommitRequest(BaseModel):
    """특정 커밋으로 롤백 요청"""
    owner: str = Field(..., description="GitHub 저장소 소유자")
    repo: str = Field(..., description="GitHub 저장소 이름")
    target_commit_sha: str = Field(..., description="롤백할 커밋 SHA")
    user_id: str = Field(default="api_user", description="사용자 ID")


class RollbackToPreviousRequest(BaseModel):
    """N번 전 배포로 롤백 요청"""
    owner: str = Field(..., description="GitHub 저장소 소유자")
    repo: str = Field(..., description="GitHub 저장소 이름")
    steps_back: int = Field(default=1, ge=1, le=10, description="몇 번 전으로 롤백할지 (1-10)")
    user_id: str = Field(default="api_user", description="사용자 ID")


class RollbackCandidatesRequest(BaseModel):
    """롤백 가능한 배포 목록 조회 요청"""
    owner: str = Field(..., description="GitHub 저장소 소유자")
    repo: str = Field(..., description="GitHub 저장소 이름")
    limit: int = Field(default=10, ge=1, le=50, description="조회할 최대 개수 (1-50)")


class RollbackResponse(BaseModel):
    """롤백 응답"""
    status: str
    action: str
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class RollbackCandidatesResponse(BaseModel):
    """롤백 후보 목록 응답"""
    owner: str
    repo: str
    total_candidates: int
    candidates: List[Dict[str, Any]]


# API Endpoints
@router.post("/rollback/commit", response_model=RollbackResponse)
async def rollback_by_commit(
    request: RollbackToCommitRequest,
    db: Session = Depends(get_db)
) -> RollbackResponse:
    """
    특정 커밋 SHA로 롤백

    Example:
        POST /api/v1/rollback/commit
        {
            "owner": "myorg",
            "repo": "myapp",
            "target_commit_sha": "abc1234",
            "user_id": "user123"
        }
    """
    try:
        logger.info(
            "rollback_by_commit_start",
            owner=request.owner,
            repo=request.repo,
            commit_sha=request.target_commit_sha,
            user_id=request.user_id
        )

        result = await rollback_to_commit(
            owner=request.owner,
            repo=request.repo,
            target_commit_sha=request.target_commit_sha,
            db=db,
            user_id=request.user_id
        )

        logger.info(
            "rollback_by_commit_success",
            owner=request.owner,
            repo=request.repo,
            commit_sha=request.target_commit_sha
        )

        return RollbackResponse(
            status="success",
            action="rollback_to_commit",
            message=f"커밋 {request.target_commit_sha[:7]}로 롤백했습니다.",
            result=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "rollback_by_commit_error",
            error=str(e),
            owner=request.owner,
            repo=request.repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"롤백 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/rollback/previous", response_model=RollbackResponse)
async def rollback_by_steps(
    request: RollbackToPreviousRequest,
    db: Session = Depends(get_db)
) -> RollbackResponse:
    """
    N번 전 배포로 롤백

    Example:
        POST /api/v1/rollback/previous
        {
            "owner": "myorg",
            "repo": "myapp",
            "steps_back": 3,
            "user_id": "user123"
        }
    """
    try:
        logger.info(
            "rollback_by_steps_start",
            owner=request.owner,
            repo=request.repo,
            steps_back=request.steps_back,
            user_id=request.user_id
        )

        result = await rollback_to_previous(
            owner=request.owner,
            repo=request.repo,
            steps_back=request.steps_back,
            db=db,
            user_id=request.user_id
        )

        logger.info(
            "rollback_by_steps_success",
            owner=request.owner,
            repo=request.repo,
            steps_back=request.steps_back
        )

        return RollbackResponse(
            status="success",
            action="rollback_to_previous",
            message=f"{request.steps_back}번 전 배포로 롤백했습니다.",
            result=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "rollback_by_steps_error",
            error=str(e),
            owner=request.owner,
            repo=request.repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"롤백 처리 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/rollback/candidates", response_model=RollbackCandidatesResponse)
async def get_candidates(
    request: RollbackCandidatesRequest,
    db: Session = Depends(get_db)
) -> RollbackCandidatesResponse:
    """
    롤백 가능한 배포 목록 조회

    Example:
        POST /api/v1/rollback/candidates
        {
            "owner": "myorg",
            "repo": "myapp",
            "limit": 10
        }
    """
    try:
        logger.info(
            "get_rollback_candidates_start",
            owner=request.owner,
            repo=request.repo,
            limit=request.limit
        )

        candidates = await get_rollback_candidates(
            owner=request.owner,
            repo=request.repo,
            db=db,
            limit=request.limit
        )

        logger.info(
            "get_rollback_candidates_success",
            owner=request.owner,
            repo=request.repo,
            count=candidates["total_candidates"]
        )

        return RollbackCandidatesResponse(**candidates)

    except Exception as e:
        logger.error(
            "get_rollback_candidates_error",
            error=str(e),
            owner=request.owner,
            repo=request.repo
        )
        raise HTTPException(
            status_code=500,
            detail=f"롤백 후보 조회 중 오류가 발생했습니다: {str(e)}"
        )


# Convenience GET endpoints (query parameters)
@router.get("/rollback/candidates/{owner}/{repo}")
async def get_candidates_by_path(
    owner: str,
    repo: str,
    limit: int = 10,
    db: Session = Depends(get_db)
) -> RollbackCandidatesResponse:
    """
    롤백 가능한 배포 목록 조회 (GET 버전)

    Example:
        GET /api/v1/rollback/candidates/myorg/myapp?limit=10
    """
    request = RollbackCandidatesRequest(owner=owner, repo=repo, limit=limit)
    return await get_candidates(request, db)
