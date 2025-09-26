from __future__ import annotations

import time
from typing import Any, Dict, Optional, List

import jwt
import httpx

from ..core.config import get_settings


class GitHubAppAuth:
    """GitHub App 인증을 위한 JWT 생성 및 설치 토큰 관리"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._installation_tokens: Dict[str, Dict[str, Any]] = {}

    def _load_private_key_text(self) -> str:
        """환경변수/파일/B64에서 PEM 텍스트를 로드한다."""
        # 1) 직접 값
        if self.settings.github_app_private_key:
            return self.settings.github_app_private_key

        # 2) 파일 경로
        import os
        pk_file = os.environ.get("KLEPAAS_GITHUB_APP_PRIVATE_KEY_FILE")
        if pk_file and os.path.exists(pk_file):
            with open(pk_file, "r", encoding="utf-8") as f:
                return f.read()

        # 3) Base64 값
        pk_b64 = os.environ.get("KLEPAAS_GITHUB_APP_PRIVATE_KEY_B64")
        if pk_b64:
            import base64
            return base64.b64decode(pk_b64).decode("utf-8")

        raise ValueError("GitHub App Private Key가 설정되지 않았습니다")

    def generate_jwt(self) -> str:
        """GitHub App JWT 생성 (RS256)"""
        if not self.settings.github_app_id:
            raise ValueError("GitHub App ID와 Private Key가 설정되지 않았습니다")

        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + (10 * 60), "iss": self.settings.github_app_id}

        private_key_text = self._load_private_key_text()
        try:
            token = jwt.encode(payload, private_key_text, algorithm="RS256")
            return token
        except Exception as e:
            raise ValueError(f"JWT 생성 실패: {e}")

    async def get_installation_token(self, installation_id: str, *, force_refresh: bool = False) -> str:
        """설치 토큰 가져오기 (캐시 고려)"""
        if not force_refresh and installation_id in self._installation_tokens:
            token_data = self._installation_tokens[installation_id]
            if token_data.get("expires_at", 0) > time.time() + 60:
                return token_data["token"]

        jwt_token = self.generate_jwt()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if resp.status_code != 201:
                raise ValueError(f"설치 토큰 요청 실패: {resp.status_code} - {resp.text}")
            data = resp.json()
            token = data.get("token")
            self._installation_tokens[installation_id] = {
                "token": token,
                "expires_at": time.time() + 3600,
            }
            return token

    async def get_app_installations(self) -> List[Dict[str, Any]]:
        """GitHub App 설치 목록 조회 (API가 리스트 또는 객체를 반환해도 안전하게 처리)"""
        jwt_token = self.generate_jwt()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"설치 목록 조회 실패: {resp.status_code} - {resp.text}")
            body = resp.json()
            if isinstance(body, list):
                return body
            if isinstance(body, dict):
                return body.get("installations", [])
            return []

    def verify_webhook_signature(self, payload: bytes, signature: str | None) -> bool:
        """GitHub App 웹훅 서명 검증"""
        if not self.settings.github_app_webhook_secret or not signature:
            return False
        import hmac, hashlib
        expected = hmac.new(self.settings.github_app_webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, f"sha256={expected}")


# 전역 인스턴스
github_app_auth = GitHubAppAuth()
