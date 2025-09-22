"""
메트릭 엔드포인트
"""
from fastapi import APIRouter, Response
from app.monitoring.metrics import get_metrics, get_metrics_content_type

router = APIRouter()

@router.get("/metrics")
async def metrics():
    """Prometheus 메트릭 엔드포인트"""
    metrics_data = get_metrics()
    return Response(
        content=metrics_data,
        media_type=get_metrics_content_type()
    )
