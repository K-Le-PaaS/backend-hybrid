from typing import Any, Dict, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ...services.commands import CommandRequest, plan_command, execute_command
from ...services.security import require_scopes
from ...services.command_history import get_command_history, get_command_by_id
from ...models.command_history import CommandHistoryResponse
from ...database import get_db


router = APIRouter()


@router.post("/commands/execute", response_model=dict)
async def commands_execute(body: CommandRequest) -> Dict[str, Any]:
    plan = plan_command(body)
    result = await execute_command(plan)
    return {"plan": {"tool": plan.tool, "args": plan.args}, "result": result}


@router.get("/commands/history", response_model=List[CommandHistoryResponse])
async def get_commands_history(limit: int = 50, offset: int = 0, db = Depends(get_db)):
    """명령어 실행 이력을 조회합니다."""
    try:
        commands = await get_command_history(db, limit=limit, offset=offset)
        return commands
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get command history: {str(e)}")


@router.get("/commands/history/{command_id}", response_model=CommandHistoryResponse)
async def get_command_detail(command_id: int, db = Depends(get_db)):
    """특정 명령어의 상세 정보를 조회합니다."""
    try:
        command = await get_command_by_id(db, command_id)
        if not command:
            raise HTTPException(status_code=404, detail="Command not found")
        return command
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get command detail: {str(e)}")


@router.get("/commands/status")
async def get_commands_status():
    """명령어 실행 상태를 조회합니다."""
    try:
        return {
            "status": "success",
            "message": "Commands service is running",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get commands status: {str(e)}")


