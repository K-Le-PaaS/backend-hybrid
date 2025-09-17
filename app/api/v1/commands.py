from typing import Any, Dict

from fastapi import APIRouter

from ...services.commands import CommandRequest, plan_command, execute_command


router = APIRouter()


@router.post("/commands/execute", response_model=dict)
async def commands_execute(body: CommandRequest) -> Dict[str, Any]:
    plan = plan_command(body)
    result = await execute_command(plan)
    return {"plan": {"tool": plan.tool, "args": plan.args}, "result": result}


