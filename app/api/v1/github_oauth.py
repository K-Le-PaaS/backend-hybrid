"""
GitHub OAuth 2.0 로그인/콜백 엔드포인트
"""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from fastapi.responses import RedirectResponse
import httpx

from ...core.config import get_settings
from ...database import get_db
from sqlalchemy.orm import Session
from ...models.oauth_token import OAuthToken
from ..v1.auth_verify import JWT_SECRET, JWT_ALGORITHM
import jwt


router = APIRouter(prefix="/auth/github", tags=["auth", "github"])


@router.get("/login")
async def github_login(
    redirect_uri: str = Query(..., description="OAuth 콜백 URI"),
    request: Request = None,
):
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(status_code=500, detail="GitHub OAuth 설정이 없습니다")
    # Optional: propagate existing app JWT via state for user binding at callback
    state = ""
    if request is not None:
        try:
            auth = (request.headers.get("authorization") or request.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                state = auth.split(" ", 1)[1]
        except Exception:
            state = ""

    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={redirect_uri}"
        "&scope=user:email"
        "&response_type=code"
        + (f"&state={state}" if state else "")
    )
    return RedirectResponse(url=url, status_code=302)


async def _exchange_code_for_token(code: str) -> str:
    settings = get_settings()
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth 설정이 없습니다")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"GitHub 토큰 교환 실패: {resp.text}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise HTTPException(status_code=400, detail="GitHub 액세스 토큰이 없습니다")
        return token


async def _fetch_github_user(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        headers = {"Authorization": f"token {access_token}"}
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="GitHub 사용자 조회 실패")
        user = user_resp.json()
        email_resp = await client.get("https://api.github.com/user/emails", headers=headers)
        primary_email = None
        if email_resp.status_code == 200:
            emails = email_resp.json() or []
            for e in emails:
                if e.get("primary"):
                    primary_email = e.get("email")
                    break
        return {
            "id": str(user.get("id")),
            "login": user.get("login"),
            "name": user.get("name") or user.get("login"),
            "avatar_url": user.get("avatar_url"),
            "email": primary_email or user.get("email"),
        }


def _store_token(db: Session, user_id: str, access_token: str) -> None:
    existing = db.query(OAuthToken).filter(
        OAuthToken.user_id == user_id, OAuthToken.provider == "github"
    ).first()
    if existing:
        existing.access_token = access_token
    else:
        db.add(
            OAuthToken(
                user_id=user_id,
                provider="github",
                access_token=access_token,
            )
        )
    db.commit()


@router.get("/callback")
async def github_callback(
    code: str = Query(...),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    access_token = await _exchange_code_for_token(code)
    # Determine app user id from state (if provided), else fallback to GitHub user id
    app_user_id: str | None = None
    if state:
        try:
            payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            app_user_id = str(payload.get("sub")) if payload.get("sub") is not None else None
        except Exception:
            app_user_id = None

    if app_user_id:
        _store_token(db, app_user_id, access_token)
    else:
        gh_user = await _fetch_github_user(access_token)
        _store_token(db, str(gh_user["id"]), access_token)
    # 프론트 대시보드로 리다이렉트 (사용자 ID를 쿼리로 전달)
    dashboard_url = f"http://localhost:3000/console"  # 필요 시 환경설정으로 교체
    return RedirectResponse(url=dashboard_url, status_code=302)


