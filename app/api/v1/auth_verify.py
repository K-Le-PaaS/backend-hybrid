"""
JWT 토큰 검증 API
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from datetime import datetime
from typing import Dict, Any

from ...core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

# JWT 설정 (oauth2.py와 동일)
JWT_SECRET = "your-secret-key"  # 실제로는 환경변수에서 가져와야 함
JWT_ALGORITHM = "HS256"

@router.get("/verify", response_model=Dict[str, Any])
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """JWT 토큰 검증"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # 토큰이 유효한지 확인
        current_time = datetime.utcnow().timestamp()
        if payload.get("exp", 0) < current_time:
            raise HTTPException(status_code=401, detail="Token expired")
        
        return {
            "valid": True,
            "user_id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "provider": payload.get("provider")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

@router.get("/me", response_model=Dict[str, Any])
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """현재 사용자 정보 조회"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "picture": payload.get("picture"),
            "provider": payload.get("provider")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

