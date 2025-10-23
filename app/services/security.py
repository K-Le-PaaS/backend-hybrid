from __future__ import annotations

from typing import Callable, Iterable, List, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from ..core.config import get_settings


security = HTTPBearer(auto_error=False)  # auto_error=False로 설정하여 토큰 없어도 에러 안남


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """
    JWT 토큰에서 사용자 ID를 추출합니다.
    토큰이 없거나 유효하지 않으면 None을 반환합니다.

    Returns:
        user_id (Optional[str]): 토큰에서 추출한 사용자 ID, 또는 None
    """
    import logging
    logger = logging.getLogger(__name__)

    if not credentials:
        logger.warning("No JWT credentials provided - returning None")
        return None

    try:
        settings = get_settings()
        token = credentials.credentials
        # 환경변수에서 JWT 시크릿 키 가져오기
        JWT_SECRET = settings.secret_key or "your-secret-key"

        # 디버깅: 토큰 디코딩 (검증 없이)
        try:
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            logger.info(f"JWT payload (unverified): {unverified_payload}")
        except Exception as e:
            logger.warning(f"Failed to decode JWT without verification: {e}")

        # 정식 디코딩
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"]
        )
        logger.info(f"JWT payload (verified): {payload}")

        # 'sub' 클레임에서 user_id 추출
        user_id = payload.get("sub")
        logger.info(f"Extracted user_id from JWT: {user_id}")
        return user_id

    except jwt.ExpiredSignatureError as e:
        logger.error(f"JWT token expired: {e}")
        return None
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding JWT: {e}")
        return None


def get_token_scopes(request: Request) -> List[str]:
    # Minimal placeholder: read comma-separated scopes from header for tests
    # In production, decode JWT / OAuth token scopes.
    header = request.headers.get("X-Scopes", "")
    scopes = [s.strip() for s in header.split(",") if s.strip()]
    return scopes


def require_scopes(required: Iterable[str]) -> Callable[[List[str]], None]:
    req_set = set(required)

    def _checker(scopes: List[str] = Depends(get_token_scopes)) -> None:
        have = set(scopes)
        if not req_set.issubset(have):
            missing = ",".join(sorted(req_set - have))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"insufficient_scope: missing {missing}",
            )

    return _checker




