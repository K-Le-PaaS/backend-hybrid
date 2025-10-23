"""
OAuth2 인증 API
Google, GitHub OAuth2 로그인을 위한 엔드포인트
"""

from fastapi import APIRouter, HTTPException, Query, Depends
import logging
from fastapi.responses import RedirectResponse
from typing import Optional, Dict, Any
import httpx
import secrets
from urllib.parse import urlencode
import jwt
from datetime import datetime, timedelta
from pydantic import BaseModel

from ...core.config import get_settings

# Pydantic 모델
class OAuth2LoginRequest(BaseModel):
    provider: str
    code: str
    redirect_uri: str

router = APIRouter(prefix="/auth/oauth2", tags=["oauth2"])
logger = logging.getLogger("app.api.oauth2")

# JWT 설정
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

def get_jwt_secret() -> str:
    """환경변수에서 JWT 시크릿 키를 가져옵니다."""
    settings = get_settings()
    return settings.secret_key or "your-secret-key"


class OAuth2Manager:
    """OAuth2 인증을 담당하는 클래스"""
    
    def __init__(self):
        settings = get_settings()
        # 테스트용 기본값 설정
        self.google_client_id = settings.google_client_id or "test-google-client-id"
        self.google_client_secret = settings.google_client_secret or "test-google-client-secret"
        self.github_client_id = settings.github_client_id or "test-github-client-id"
        self.github_client_secret = settings.github_client_secret or "test-github-client-secret"
    
    async def verify_google_token(self, token: str) -> Dict[str, Any]:
        """Google OAuth2 토큰 검증"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://www.googleapis.com/oauth2/v1/userinfo?access_token={token}"
                )
                
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=401,
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
                status_code=401,
                detail=f"Google token verification failed: {str(e)}"
            )
    
    async def verify_github_token(self, token: str) -> Dict[str, Any]:
        """GitHub OAuth2 토큰 검증"""
        try:
            headers = {
                "Authorization": f"token {token}",
                "User-Agent": "K-Le-PaaS/1.0",
                "Accept": "application/vnd.github.v3+json"
            }
            print(f"GitHub 토큰 검증 시도: {token[:10]}...")
            
            async with httpx.AsyncClient() as client:
                # 사용자 정보 가져오기
                user_response = await client.get(
                    "https://api.github.com/user",
                    headers=headers
                )
                
                print(f"GitHub API 응답 상태: {user_response.status_code}")
                if user_response.status_code != 200:
                    error_text = user_response.text
                    print(f"GitHub API 에러: {error_text}")
                    raise HTTPException(
                        status_code=401,
                        detail=f"GitHub token verification failed: {user_response.status_code}: {error_text}"
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
                status_code=401,
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
                status_code=400,
                detail=f"Unsupported OAuth2 provider: {provider}"
            )
    
    def get_authorization_url(self, provider: str, redirect_uri: str) -> str:
        """OAuth2 인증 URL 생성"""
        # state 파라미터에 provider 정보 포함
        state = f"provider={provider}"
        
        if provider == "google":
            return (
                f"https://accounts.google.com/o/oauth2/v2/auth"
                f"?client_id={self.google_client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&scope=openid email profile"
                f"&response_type=code"
                f"&access_type=offline"
                f"&state={state}"
            )
        elif provider == "github":
            return (
                f"https://github.com/login/oauth/authorize"
                f"?client_id={self.github_client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&scope=user:email"
                f"&response_type=code"
                f"&state={state}"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported OAuth2 provider: {provider}"
            )


@router.get("/url/{provider}")
async def get_oauth2_url(
    provider: str,
    redirect_uri: str = Query(..., description="리디렉션 URI")
):
    """OAuth2 인증 URL 생성"""
    if provider not in ["google", "github"]:
        raise HTTPException(status_code=400, detail="지원하지 않는 제공자입니다")
    
    # Allow flexible redirect_uri as configured in frontend (e.g., /oauth2-callback)
    # Validation should be enforced in the OAuth provider console configuration.
    
    logger.info("OAuth2 get_oauth2_url", extra={"provider": provider, "redirect_uri": redirect_uri})
    oauth2_manager = OAuth2Manager()
    auth_url = oauth2_manager.get_authorization_url(provider, redirect_uri)
    logger.info("OAuth2 authorization_url_generated", extra={"provider": provider, "redirect_uri": redirect_uri, "auth_url": auth_url})
    
    return {
        "auth_url": auth_url,
        "provider": provider,
        "redirect_uri": redirect_uri
    }


@router.post("/login")
async def oauth2_login(request: OAuth2LoginRequest):
    """OAuth2 로그인 처리"""
    provider = request.provider
    code = request.code
    redirect_uri = request.redirect_uri
    
    if provider not in ["google", "github"]:
        raise HTTPException(status_code=400, detail="지원하지 않는 제공자입니다")
    
    try:
        logger.info("OAuth2 login start", extra={"provider": provider, "redirect_uri": redirect_uri})
        oauth2_manager = OAuth2Manager()
        
        # 인증 코드를 액세스 토큰으로 교환
        if provider == "google":
            token_response = await exchange_google_code(code, redirect_uri)
        else:  # github
            token_response = await exchange_github_code(code, redirect_uri)
        
        # 사용자 정보 조회
        user_info = await oauth2_manager.get_oauth2_user(provider, token_response["access_token"])
        
        # JWT 토큰 생성
        jwt_token = create_jwt_token(user_info)
        
        logger.info("OAuth2 login success", extra={"provider": provider, "redirect_uri": redirect_uri})
        return {
            "success": True,
            "access_token": jwt_token,
            "user": user_info,
            "message": f"{provider.title()} 로그인이 성공했습니다!"
        }
        
    except Exception as e:
        logger.exception("OAuth2 login failed", extra={"provider": provider, "redirect_uri": redirect_uri})
        raise HTTPException(status_code=500, detail=f"OAuth2 로그인 실패: {str(e)}")


async def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Google 인증 코드를 액세스 토큰으로 교환"""
    settings = get_settings()
    
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth2 설정이 없습니다")
    
    logger.info("Google token exchange", extra={"redirect_uri": redirect_uri, "code_prefix": code[:8]})
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            }
        )
        
        if response.status_code != 200:
            error_detail = response.text
            raise HTTPException(status_code=400, detail=f"Google 토큰 교환 실패: {error_detail}")
        
        return response.json()


async def exchange_github_code(code: str, redirect_uri: str) -> dict:
    """GitHub 인증 코드를 액세스 토큰으로 교환"""
    settings = get_settings()
    
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth2 설정이 없습니다")
    
    logger.info("GitHub token exchange", extra={"redirect_uri": redirect_uri, "code_prefix": code[:8]})
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri
            },
            headers={"Accept": "application/json"}
        )
        
        logger.info("GitHub token exchange response", extra={"status_code": response.status_code})
        
        if response.status_code != 200:
            error_detail = response.text
            raise HTTPException(status_code=400, detail=f"GitHub 토큰 교환 실패: {error_detail}")
        
        return response.json()


def create_jwt_token(user_info: Dict[str, Any]) -> str:
    """JWT 토큰 생성"""
    payload = {
        "sub": user_info.get("provider_id"),
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "provider": user_info.get("provider"),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


@router.get("/user")
async def get_current_user(token: str = Query(..., description="JWT 토큰")):
    """현재 사용자 정보 조회"""
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return {
            "success": True,
            "user": {
                "id": payload.get("sub"),
                "email": payload.get("email"),
                "name": payload.get("name"),
                "provider": payload.get("provider")
            }
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
