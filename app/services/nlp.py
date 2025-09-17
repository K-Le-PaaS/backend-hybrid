from typing import Any, Dict

from pydantic import BaseModel, Field

from ..llm.gemini import GeminiClient


class InterpretRequest(BaseModel):
    prompt: str = Field(min_length=1)


async def interpret_prompt(data: InterpretRequest) -> Dict[str, Any]:
    client = GeminiClient()
    result = await client.interpret(data.prompt)
    return result


