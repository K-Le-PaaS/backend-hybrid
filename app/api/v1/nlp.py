from typing import Any, Dict

from fastapi import APIRouter

from ...services.nlp import InterpretRequest, interpret_prompt


router = APIRouter()


@router.post("/nlp/interpret", response_model=dict)
async def nlp_interpret(body: InterpretRequest) -> Dict[str, Any]:
    return await interpret_prompt(body)


