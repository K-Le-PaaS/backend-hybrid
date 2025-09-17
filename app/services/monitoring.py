from typing import Any, Dict

import httpx
from pydantic import BaseModel, Field

from ..core.config import get_settings


class PromQuery(BaseModel):
    query: str = Field(min_length=1)


async def query_prometheus(data: PromQuery) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.prometheus_base_url:
        return {"status": "skipped", "reason": "prometheus_base_url not set"}
    url = settings.prometheus_base_url.rstrip("/") + "/api/v1/query"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params={"query": data.query})
        resp.raise_for_status()
        return resp.json()


