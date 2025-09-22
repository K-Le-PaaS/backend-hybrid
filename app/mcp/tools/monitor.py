from typing import Any, Dict

from ...services.monitoring import query_prometheus


async def query_metrics(query: str) -> Dict[str, Any]:
    """Query Prometheus metrics via HTTP API"""
    from pydantic import BaseModel, Field
    
    class QueryInput(BaseModel):
        query: str = Field(min_length=1)
    
    input_data = QueryInput(query=query)
    return await query_prometheus(input_data)


