from __future__ import annotations

import time
from typing import Any, Dict, Optional

import jwt
import httpx

from ..core.config import get_settings


class GitHubAppAuth:
    """GitHub App 인증을 위한 JWT 생성 및 설치 토큰 관리"""
    
    def __init__(self):
        self.settings = get_settings()
        self._installation_tokens: Dict[str, Dict[str, Any]] = {}
    
    def _load_private_key_text(self) -> str:
        """Private Key 파일에서 내용을 읽어옵니다."""
        if self.settings.github_app_private_key:
            return self.settings.github_app_private_key
        
        if not self.settings.github_app_private_key_file:
            raise ValueError("GitHub App Private Key 파일이 설정되지 않았습니다")
        
        try:
            with open(self.settings.github_app_private_key_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"Private Key 파일 읽기 실패: {e}")

    def generate_jwt(self) -> str:
        """GitHub App JWT 생성 (RS256 알고리즘)"""
        if not self.settings.github_app_id:
            raise ValueError("GitHub App ID가 설정되지 않았습니다")
        
        now = int(time.time())
        payload = {
            "iat": now - 60,  # 60초 전에 발급 (클럭 드리프트 허용)
            "exp": now + (10 * 60),  # 10분 후 만료
            "iss": self.settings.github_app_id
        }
        
        try:
            # Private Key를 파일에서 읽어서 PEM 형식으로 파싱
            private_key_text = self._load_private_key_text()
            private_key = private_key_text.encode('utf-8')
            token = jwt.encode(payload, private_key, algorithm="RS256")
            return token
        except Exception as e:
            raise ValueError(f"JWT 생성 실패: {e}")
    
    async def get_installation_token(self, installation_id: str) -> str:
        """설치 토큰 가져오기 (캐시된 토큰이 유효하면 재사용)"""
        # 캐시된 토큰 확인
        if installation_id in self._installation_tokens:
            token_data = self._installation_tokens[installation_id]
            if token_data["expires_at"] > time.time() + 60:  # 1분 여유
                return token_data["token"]
        
        # 새 토큰 요청
        jwt_token = self.generate_jwt()
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )
            
            if response.status_code != 201:
                raise ValueError(f"설치 토큰 요청 실패: {response.status_code} - {response.text}")
            
            token_data = response.json()
            
            # 토큰 캐시
            self._installation_tokens[installation_id] = {
                "token": token_data["token"],
                "expires_at": time.time() + 3600  # 1시간 후 만료
            }
            
            return token_data["token"]
    
    async def get_app_installations(self) -> list[Dict[str, Any]]:
        """GitHub App 설치 목록 조회 (API가 리스트 또는 객체를 반환해도 안전하게 처리)"""
        jwt_token = self.generate_jwt()
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )
            
            if response.status_code != 200:
                raise ValueError(f"설치 목록 조회 실패: {response.status_code} - {response.text}")
            
            body = response.json()
            if isinstance(body, list):
                return body
            if isinstance(body, dict):
                return body.get("installations", [])
            return []
    
    async def get_installation_token_for_repo(self, owner: str, repo: str, db_session=None) -> tuple[str, str]:
        """특정 레포지토리에 대한 GitHub App 설치 토큰을 조회 (DB 우선 + API 폴백)"""
        
        # 1. DB에서 먼저 조회 (빠른 응답)
        if db_session:
            try:
                from ...models.user_project_integration import UserProjectIntegration
                integration = db_session.query(UserProjectIntegration).filter(
                    UserProjectIntegration.github_owner == owner,
                    UserProjectIntegration.github_repo == repo
                ).first()
                
                if integration and integration.github_installation_id:
                    try:
                        # DB에 있는 installation_id로 토큰 획득 시도
                        token = await self.get_installation_token(str(integration.github_installation_id))
                        return token, str(integration.github_installation_id)
                    except Exception:
                        # 토큰 획득 실패 시 API로 폴백
                        pass
            except Exception:
                # DB 조회 실패 시 API로 폴백
                pass
        
        # 2. DB에 없거나 실패한 경우 GitHub API로 실시간 조회
        jwt_token = self.generate_jwt()
        
        async with httpx.AsyncClient(timeout=10) as client:
            # 설치 목록 조회
            installations_response = await client.get(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )
            
            if installations_response.status_code != 200:
                raise ValueError(f"설치 목록 조회 실패: {installations_response.status_code}")
            
            installations = installations_response.json()
            if not isinstance(installations, list):
                installations = installations.get("installations", [])
            
            # 각 설치에 대해 레포지토리 접근 권한 확인
            for installation in installations:
                installation_id = installation.get("id")
                if not installation_id:
                    continue
                
                try:
                    # 설치 토큰으로 레포지토리 접근 시도
                    installation_token = await self.get_installation_token(str(installation_id))
                    
                    # 특정 레포지토리에 접근 가능한지 확인
                    repo_response = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}",
                        headers={
                            "Authorization": f"Bearer {installation_token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"
                        }
                    )
                    
                    if repo_response.status_code == 200:
                        # 레포지토리에 접근 가능함
                        # DB에 설치 정보 저장 (다음번 빠른 조회를 위해)
                        if db_session:
                            try:
                                from ...services.user_project_integration import upsert_integration
                                upsert_integration(
                                    db=db_session,
                                    user_id="system",  # 시스템 레벨 저장
                                    owner=owner,
                                    repo=repo,
                                    repository_id=None,
                                    installation_id=str(installation_id),
                                    sc_project_id=None,
                                    sc_repo_name=None,
                                )
                            except Exception:
                                # DB 저장 실패해도 토큰은 반환
                                pass
                        
                        return installation_token, str(installation_id)
                        
                except Exception:
                    # 이 설치에서 토큰 획득 실패, 다음 설치 시도
                    continue
            
            # 레포지토리에 접근 가능한 설치를 찾지 못함
            raise ValueError(f"GitHub App이 레포지토리 '{owner}/{repo}'에 설치되지 않았습니다.")
    
    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """GitHub App 웹훅 서명 검증"""
        if not self.settings.github_app_webhook_secret:
            return False
        
        import hmac
        import hashlib
        
        expected_signature = hmac.new(
            self.settings.github_app_webhook_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # GitHub는 "sha256=" 접두사를 사용
        expected_signature = f"sha256={expected_signature}"
        
        return hmac.compare_digest(signature, expected_signature)


# 전역 인스턴스
github_app_auth = GitHubAppAuth()
