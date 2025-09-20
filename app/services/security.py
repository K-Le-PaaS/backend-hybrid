from __future__ import annotations

from typing import Callable, Iterable, List
from fastapi import Depends, HTTPException, Request, status


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




