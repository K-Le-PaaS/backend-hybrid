from typing import Any, Dict

from fastapi import APIRouter

from ...services.monitoring import PromQuery, query_prometheus


router = APIRouter()


@router.post("/monitoring/query", response_model=dict)
async def prom_query(body: PromQuery) -> Dict[str, Any]:
    return await query_prometheus(body)


