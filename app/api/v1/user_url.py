"""
사용자 배포 URL 관리 API

배포된 애플리케이션의 사용자 서비스 URL을 관리하는 엔드포인트를 제공합니다.
"""

from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db
from ...services.pipeline_user_url import (
    get_deployment_url,
    get_all_deployment_urls_for_user,
    upsert_deployment_url
)


router = APIRouter()


class UpdateUrlRequest(BaseModel):
    """URL 업데이트 요청 모델"""
    url: str = Field(..., min_length=1, description="새로운 배포 URL (HTTPS 포함)")


class DeploymentUrlResponse(BaseModel):
    """배포 URL 응답 모델"""
    id: int
    user_id: str
    github_owner: str
    github_repo: str
    url: str
    is_user_modified: bool
    created_at: str
    updated_at: str


@router.get("/user-urls", response_model=List[DeploymentUrlResponse])
async def get_user_deployment_urls(
    user_id: str,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    사용자의 모든 배포 URL을 조회합니다.

    Args:
        user_id: 사용자 ID (쿼리 파라미터)
        db: 데이터베이스 세션

    Returns:
        배포 URL 목록
    """
    try:
        deployment_urls = get_all_deployment_urls_for_user(db, user_id)

        # 응답 형식으로 변환
        return [url.to_dict() for url in deployment_urls]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get deployment URLs: {str(e)}"
        )


@router.get("/user-urls/{owner}/{repo}", response_model=DeploymentUrlResponse)
async def get_repository_deployment_url(
    owner: str,
    repo: str,
    user_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    특정 레포지토리의 배포 URL을 조회합니다.

    Args:
        owner: GitHub 저장소 소유자
        repo: GitHub 저장소 이름
        user_id: 사용자 ID (쿼리 파라미터)
        db: 데이터베이스 세션

    Returns:
        배포 URL 정보
    """
    try:
        deployment_url = get_deployment_url(db, user_id, owner, repo)

        if not deployment_url:
            raise HTTPException(
                status_code=404,
                detail=f"Deployment URL not found for {owner}/{repo}"
            )

        return deployment_url.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get deployment URL: {str(e)}"
        )


@router.put("/user-urls/{owner}/{repo}", response_model=DeploymentUrlResponse)
async def update_repository_deployment_url(
    owner: str,
    repo: str,
    user_id: str,
    body: UpdateUrlRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    특정 레포지토리의 배포 URL을 업데이트합니다.

    사용자가 직접 URL을 변경하는 경우 사용합니다.

    Args:
        owner: GitHub 저장소 소유자
        repo: GitHub 저장소 이름
        user_id: 사용자 ID (쿼리 파라미터)
        body: URL 업데이트 요청
        db: 데이터베이스 세션

    Returns:
        업데이트된 배포 URL 정보
    """
    try:
        # URL 업데이트 (사용자 수정으로 표시)
        deployment_url = upsert_deployment_url(
            db=db,
            user_id=user_id,
            github_owner=owner,
            github_repo=repo,
            url=body.url,
            is_user_modified=True  # 사용자가 직접 수정
        )

        return deployment_url.to_dict()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update deployment URL: {str(e)}"
        )


@router.delete("/user-urls/{owner}/{repo}")
async def delete_repository_deployment_url(
    owner: str,
    repo: str,
    user_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    특정 레포지토리의 배포 URL을 삭제합니다.

    Args:
        owner: GitHub 저장소 소유자
        repo: GitHub 저장소 이름
        user_id: 사용자 ID (쿼리 파라미터)
        db: 데이터베이스 세션

    Returns:
        삭제 성공 메시지
    """
    try:
        deployment_url = get_deployment_url(db, user_id, owner, repo)

        if not deployment_url:
            raise HTTPException(
                status_code=404,
                detail=f"Deployment URL not found for {owner}/{repo}"
            )

        db.delete(deployment_url)
        db.commit()

        return {
            "status": "success",
            "message": f"Deployment URL deleted for {owner}/{repo}"
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete deployment URL: {str(e)}"
        )
