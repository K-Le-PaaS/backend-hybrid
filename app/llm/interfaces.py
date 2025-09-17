from abc import ABC, abstractmethod
from typing import Any, Dict


class LLMClient(ABC):
    @abstractmethod
    async def interpret(self, prompt: str) -> Dict[str, Any]:
        """Return structured interpretation of the prompt."""
        raise NotImplementedError


