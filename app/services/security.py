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
    if not credentials:
        return None

    try:
        settings = get_settings()
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"]
        )
        return payload.get("sub")  # 'sub' 클레임에 user_id 저장
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
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




