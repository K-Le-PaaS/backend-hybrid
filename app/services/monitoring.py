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


def get_system_metrics() -> Dict[str, Any]:
    """Mock system metrics for dashboard."""
    return {
        "cpu_usage": 45.2,
        "memory_usage": 67.8,
        "disk_usage": 23.1,
        "network_in": 1024,
        "network_out": 2048,
    }


def get_health_status() -> Dict[str, Any]:
    """Mock health status for dashboard."""
    return {
        "status": "healthy",
        "uptime": "99.9%",
        "last_check": "2024-01-01T00:00:00Z",
    }


