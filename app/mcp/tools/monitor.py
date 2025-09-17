from typing import Any, Dict

try:
    from fastapi_mcp import mcp_tool  # type: ignore
except Exception:  # noqa: BLE001
    def mcp_tool(*args: Any, **kwargs: Any):  # type: ignore
        def wrapper(func):
            return func
        return wrapper

from pydantic import BaseModel, Field

from ...services.monitoring import query_prometheus


class QueryInput(BaseModel):
    query: str = Field(min_length=1)


@mcp_tool(
    name="query_metrics",
    description="Query Prometheus metrics via HTTP API",
    input_model=QueryInput,
)
async def query_metrics(input_data: QueryInput) -> Dict[str, Any]:
    return await query_prometheus(input_data)


