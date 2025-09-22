"""
OAuth2 인증 모듈
"""
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings

class OAuth2Manager:
    """OAuth2 인증을 담당하는 클래스"""
    
    def __init__(self):
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")
        self.google_client_id = settings.google_client_id
        self.google_client_secret = settings.google_client_secret
        self.github_client_id = settings.github_client_id
        self.github_client_secret = settings.github_client_secret
    
    async def verify_google_token(self, token: str) -> Dict[str, Any]:
        """Google OAuth2 토큰 검증"""
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://www.googleapis.com/oauth2/v1/userinfo?access_token={token}"
                )
                
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid Google token"
                    )
                
                user_info = response.json()
                
                return {
                    "provider": "google",
                    "provider_id": user_info.get("id"),
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "picture": user_info.get("picture"),
                    "verified": user_info.get("verified_email", False)
                }
                
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Google token verification failed: {str(e)}"
            )
    
    async def verify_github_token(self, token: str) -> Dict[str, Any]:
        """GitHub OAuth2 토큰 검증"""
        try:
            import httpx
            
            headers = {"Authorization": f"token {token}"}
            
            async with httpx.AsyncClient() as client:
                # 사용자 정보 가져오기
                user_response = await client.get(
                    "https://api.github.com/user",
                    headers=headers
                )
                
                if user_response.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid GitHub token"
                    )
                
                user_info = user_response.json()
                
                # 이메일 정보 가져오기
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers=headers
                )
                
                emails = email_response.json() if email_response.status_code == 200 else []
                primary_email = next(
                    (email["email"] for email in emails if email.get("primary")), 
                    user_info.get("email")
                )
                
                return {
                    "provider": "github",
                    "provider_id": str(user_info.get("id")),
                    "email": primary_email,
                    "name": user_info.get("name") or user_info.get("login"),
                    "picture": user_info.get("avatar_url"),
                    "verified": True  # GitHub는 이메일 인증이 필요
                }
                
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"GitHub token verification failed: {str(e)}"
            )
    
    async def get_oauth2_user(self, provider: str, token: str) -> Dict[str, Any]:
        """OAuth2 제공자별 사용자 정보 가져오기"""
        if provider == "google":
            return await self.verify_google_token(token)
        elif provider == "github":
            return await self.verify_github_token(token)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported OAuth2 provider: {provider}"
            )
    
    def get_authorization_url(self, provider: str, redirect_uri: str) -> str:
        """OAuth2 인증 URL 생성"""
        if provider == "google":
            return (
                f"https://accounts.google.com/o/oauth2/v2/auth"
                f"?client_id={self.google_client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&scope=openid email profile"
                f"&response_type=code"
                f"&access_type=offline"
            )
        elif provider == "github":
            return (
                f"https://github.com/login/oauth/authorize"
                f"?client_id={self.github_client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&scope=user:email"
                f"&response_type=code"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported OAuth2 provider: {provider}"
            )
