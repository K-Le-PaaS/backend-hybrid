from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ...services.tutorial import (
    start_session,
    get_session,
    next_step,
    complete_session,
)


router = APIRouter()


@router.post("/tutorial/start", response_model=dict)
async def tutorial_start(session_id: str) -> Dict[str, Any]:
    return start_session(session_id)


@router.get("/tutorial/get", response_model=dict)
async def tutorial_get(session_id: str) -> Dict[str, Any]:
    sess = get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


@router.post("/tutorial/next", response_model=dict)
async def tutorial_next(session_id: str) -> Dict[str, Any]:
    sess = next_step(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


@router.post("/tutorial/complete", response_model=dict)
async def tutorial_complete(session_id: str) -> Dict[str, Any]:
    sess = complete_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


