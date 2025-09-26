from __future__ import annotations

"""
RBAC 보안 의존성

 - Bearer 토큰(JWT)에서 사용자/역할을 추출
 - 역할 → 권한 매핑 후 권한 가드 제공
 - 권한 확인 시 감사 로그 기록
"""

from typing import Callable, List

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .permissions import PermissionManager, Permission, Role
from .audit import AuditLogger

# JWT 시크릿/알고리즘은 기존 OAuth2 모듈의 설정을 사용
from ..api.v1.oauth2 import JWT_SECRET, JWT_ALGORITHM


bearer_scheme = HTTPBearer(auto_error=True)
permission_manager = PermissionManager()
audit_logger = AuditLogger()


def _parse_roles(raw_roles: List[str] | None) -> List[str]:
    if not raw_roles:
        return [Role.DEVELOPER.value]
    # 유효한 Role 값만 유지
    role_values = {r.value for r in Role}
    return [r for r in raw_roles if r in role_values]


async def get_current_user_permissions(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> List[str]:
    """JWT에서 roles를 추출해 권한 문자열 목록을 반환합니다."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="토큰이 만료되었습니다")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다")

    user_id = str(payload.get("sub")) if payload.get("sub") is not None else None
    roles = _parse_roles(payload.get("roles"))

    # 역할 → 권한 매핑
    role_enums = []
    for r in roles:
        try:
            role_enums.append(Role(r))
        except Exception:
            continue
    perms = permission_manager.get_permissions_for_roles(role_enums)
    perm_strings = [p.value for p in perms]

    # 접근 시도 자체를 감사 로깅(리소스/액션은 구체 가드에서 기록)
    audit_logger.log_event(
        event_type=audit_logger.AuditEventType.RESOURCE_ACCESSED if hasattr(audit_logger, "AuditEventType") else None,  # type: ignore[arg-type]
        user_id=user_id,
        details={"path": request.url.path, "method": request.method, "roles": roles},
        request=request,
    )
    return perm_strings


def require_permissions(*required: Permission) -> Callable[[List[str]], None]:
    """엔드포인트에서 필요한 권한을 선언하는 의존성 팩토리."""

    async def _checker(
        request: Request,
        user_permissions: List[str] = Depends(get_current_user_permissions),
    ) -> None:
        user_id = None
        # user_id 추출을 위해 토큰을 다시 해석하지 않고 헤더에서 재사용
        credentials: HTTPAuthorizationCredentials = await bearer_scheme(request)  # type: ignore[assignment]
        try:
            payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = str(payload.get("sub")) if payload.get("sub") is not None else None
        except Exception:
            pass

        required_values = [p.value for p in required]
        granted = any(p in user_permissions for p in required_values)

        # 감사 로깅
        try:
            audit_logger.log_permission_check(
                user_id=user_id or "unknown",
                resource=request.url.path,
                action=",".join(required_values),
                granted=granted,
                request=request,
            )
        except Exception:
            # 감사 로깅 실패는 접근 결정에 영향 주지 않음
            pass

        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required one of: {', '.join(required_values)}",
            )

    return _checker









