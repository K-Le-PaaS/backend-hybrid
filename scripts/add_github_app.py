#!/usr/bin/env python3
"""
GitHub App 설치 정보를 데이터베이스에 수동으로 추가하는 스크립트
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.database import SessionLocal
from app.models.user_repository import UserRepository
from app.models.user_project_integration import UserProjectIntegration

def add_github_app_installation():
    """GitHub App 설치 정보를 데이터베이스에 추가"""
    
    # 사용자 입력 받기
    user_id = input("사용자 ID를 입력하세요 (예: google_123456789): ")
    user_email = input("사용자 이메일을 입력하세요: ")
    owner = input("GitHub 소유자명을 입력하세요 (예: K-Le-PaaS): ")
    repo_name = input("레포지토리명을 입력하세요 (예: test01): ")
    installation_id = input("GitHub App Installation ID를 입력하세요: ")
    
    db = SessionLocal()
    
    try:
        # 1. UserRepository 테이블에 추가
        full_name = f"{owner}/{repo_name}"
        
        # 중복 확인
        existing_repo = db.query(UserRepository).filter(
            UserRepository.user_id == user_id,
            UserRepository.repository_full_name == full_name
        ).first()
        
        if not existing_repo:
            new_repo = UserRepository(
                user_id=user_id,
                user_email=user_email,
                repository_owner=owner,
                repository_name=repo_name,
                repository_full_name=full_name,
                repository_id="123456789",  # 임시 ID
                branch="main",
                installation_id=installation_id
            )
            db.add(new_repo)
            print(f"✅ UserRepository에 {full_name} 추가됨")
        else:
            print(f"ℹ️ UserRepository에 {full_name} 이미 존재함")
        
        # 2. UserProjectIntegration 테이블에 추가
        existing_integration = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.user_id == user_id,
            UserProjectIntegration.github_owner == owner,
            UserProjectIntegration.github_repo == repo_name
        ).first()
        
        if not existing_integration:
            new_integration = UserProjectIntegration(
                user_id=user_id,
                user_email=user_email,
                github_owner=owner,
                github_repo=repo_name,
                github_full_name=full_name,
                github_installation_id=installation_id,
                branch="main",
                auto_deploy_enabled=True
            )
            db.add(new_integration)
            print(f"✅ UserProjectIntegration에 {full_name} 추가됨")
        else:
            print(f"ℹ️ UserProjectIntegration에 {full_name} 이미 존재함")
        
        db.commit()
        print("🎉 GitHub App 설치 정보가 성공적으로 추가되었습니다!")
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("GitHub App 설치 정보 추가 도구")
    print("=" * 40)
    add_github_app_installation()
