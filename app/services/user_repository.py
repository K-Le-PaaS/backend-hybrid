"""
사용자별 연동된 리포지토리 관리 서비스
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from ..models.user_repository import UserRepository
from ..models.base import Base
from ..database import get_db
from ..models.user_project_integration import UserProjectIntegration


async def get_user_repositories(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """사용자의 연동된 리포지토리 목록 조회 (user_project_integration 테이블 사용)"""
    
    repositories = db.query(UserProjectIntegration).filter(
        UserProjectIntegration.user_id == user_id
    ).all()
    
    # UserProjectIntegration을 UserRepository 형식으로 변환
    result = []
    for repo in repositories:
        result.append({
            "id": str(repo.id),
            "name": repo.github_repo,
            "fullName": repo.github_full_name,
            "connected": True,
            "lastSync": repo.updated_at.isoformat() if repo.updated_at else None,
            "branch": repo.branch or "main",
            "status": "healthy",  # 기본값
            "autoDeployEnabled": repo.auto_deploy_enabled or False,
            "webhookConfigured": bool(repo.github_webhook_secret),
            "installation_id": repo.github_installation_id,
        })
    
    return result


async def add_user_repository(
    db: Session, 
    user_id: str, 
    user_email: str,
    repository_owner: str,
    repository_name: str,
    repository_full_name: str,
    repository_id: str,
    branch: str = "main",
    installation_id: Optional[str] = None
) -> Dict[str, Any]:
    """사용자에게 리포지토리 연동 추가"""
    
    # 중복 확인
    existing = db.query(UserRepository).filter(
        and_(
            UserRepository.user_id == user_id,
            UserRepository.repository_full_name == repository_full_name
        )
    ).first()
    
    if existing:
        return {
            "status": "success",
            "message": "리포지토리가 이미 연동되어 있습니다.",
            "repository": repository_full_name
        }
    
    # 새 리포지토리 추가
    new_repo = UserRepository(
        user_id=user_id,
        user_email=user_email,
        repository_owner=repository_owner,
        repository_name=repository_name,
        repository_full_name=repository_full_name,
        repository_id=repository_id,
        branch=branch,
        installation_id=installation_id
    )
    
    db.add(new_repo)
    db.commit()
    db.refresh(new_repo)
    
    return {
        "status": "success",
        "message": "리포지토리가 성공적으로 연동되었습니다.",
        "repository": repository_full_name,
        "data": new_repo.to_dict()
    }


async def remove_user_repository(
    db: Session, 
    user_id: str, 
    repository_full_name: str
) -> Dict[str, Any]:
    """사용자의 리포지토리 연동 제거"""
    
    repository = db.query(UserRepository).filter(
        and_(
            UserRepository.user_id == user_id,
            UserRepository.repository_full_name == repository_full_name
        )
    ).first()
    
    if not repository:
        return {
            "status": "error",
            "message": "연동된 리포지토리를 찾을 수 없습니다."
        }
    
    db.delete(repository)
    db.commit()
    
    return {
        "status": "success",
        "message": "리포지토리 연동이 제거되었습니다.",
        "repository": repository_full_name
    }


async def update_repository_sync(
    db: Session,
    user_id: str,
    repository_full_name: str,
    last_sync: Optional[str] = None,
    status: str = "healthy"
) -> Dict[str, Any]:
    """리포지토리 동기화 정보 업데이트"""
    
    repository = db.query(UserRepository).filter(
        and_(
            UserRepository.user_id == user_id,
            UserRepository.repository_full_name == repository_full_name
        )
    ).first()
    
    if not repository:
        return {
            "status": "error",
            "message": "연동된 리포지토리를 찾을 수 없습니다."
        }
    
    if last_sync:
        from datetime import datetime
        repository.last_sync = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
    
    repository.status = status
    db.commit()
    
    return {
        "status": "success",
        "message": "리포지토리 정보가 업데이트되었습니다.",
        "data": repository.to_dict()
    }






