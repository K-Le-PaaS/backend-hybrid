from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.tutorial_script import tutorial_state_manager


router = APIRouter()


class TutorialStartRequest(BaseModel):
    session_id: str


class TutorialUserInputRequest(BaseModel):
    session_id: str
    user_input: str


@router.post("/tutorial/start", response_model=dict)
async def tutorial_start(request: TutorialStartRequest) -> Dict[str, Any]:
    """튜토리얼 시작"""
    result = tutorial_state_manager.start_tutorial(request.session_id)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to start tutorial")
    return result


@router.get("/tutorial/current", response_model=dict)
async def tutorial_get_current(session_id: str) -> Dict[str, Any]:
    """현재 튜토리얼 상태 조회"""
    result = tutorial_state_manager.get_current_step(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    return result


@router.post("/tutorial/next", response_model=dict)
async def tutorial_next(session_id: str) -> Dict[str, Any]:
    """다음 단계로 진행"""
    result = tutorial_state_manager.next_step(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tutorial session not found or already completed")
    return result


@router.post("/tutorial/complete", response_model=dict)
async def tutorial_complete(session_id: str) -> Dict[str, Any]:
    """튜토리얼 완료"""
    result = tutorial_state_manager.complete_tutorial(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    return result


@router.post("/tutorial/input", response_model=dict)
async def tutorial_add_input(request: TutorialUserInputRequest) -> Dict[str, Any]:
    """사용자 입력 추가"""
    success = tutorial_state_manager.add_user_input(request.session_id, request.user_input)
    if not success:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    
    # 입력 후 현재 상태 반환
    result = tutorial_state_manager.get_current_step(request.session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    return result


@router.post("/tutorial/error", response_model=dict)
async def tutorial_add_error(session_id: str, error_message: str) -> Dict[str, Any]:
    """에러 추가"""
    success = tutorial_state_manager.add_error(session_id, error_message)
    if not success:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    
    # 에러 후 현재 상태 반환
    result = tutorial_state_manager.get_current_step(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    return result


@router.delete("/tutorial/reset", response_model=dict)
async def tutorial_reset(session_id: str) -> Dict[str, Any]:
    """튜토리얼 세션 리셋"""
    success = tutorial_state_manager.reset_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tutorial session not found")
    return {"message": "Tutorial session reset successfully"}


