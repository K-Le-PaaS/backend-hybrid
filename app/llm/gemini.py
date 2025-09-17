from typing import Any, Dict

from .interfaces import LLMClient
from ..core.config import get_settings


class GeminiClient(LLMClient):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def interpret(self, prompt: str) -> Dict[str, Any]:
        # Phase 1: Stubbed response to avoid external dependency
        # Later: call Vertex AI Gemini with official SDK / REST
        return {
            "intent": "unknown",
            "entities": {
                "raw": prompt,
            },
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "project": self.settings.gcp_project,
                "location": self.settings.gcp_location,
                "mode": "stub",
            },
        }


