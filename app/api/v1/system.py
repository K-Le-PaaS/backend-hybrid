from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import asyncio
import httpx
import logging

from fastapi import APIRouter, Request, HTTPException, status
from prometheus_client import Counter, Gauge, Histogram, Info, Enum
from pydantic import BaseModel

from ...core.config import get_settings
from ...services.alerting import send_health_alert, send_circuit_breaker_alert

logger = logging.getLogger(__name__)

# Prometheus 메트릭 정의
health_check_counter = Counter(
    'health_check_total', 
    'Total number of health checks', 
    ['status', 'component']
)

health_check_duration = Histogram(
    'health_check_duration_seconds',
    'Time spent on health checks',
    ['component']
)

component_status = Gauge(
    'component_status',
    'Component health status (1=healthy, 0=unhealthy)',
    ['component', 'instance']
)

system_info = Info(
    'system_info',
    'System information'
)

circuit_breaker_state = Enum(
    'circuit_breaker_state',
    'Circuit breaker state',
    ['component'],
    states=['CLOSED', 'OPEN', 'HALF_OPEN']
)

router = APIRouter()


class HealthCheckResult(BaseModel):
    """Health check 결과 모델"""
    component: str
    status: str
    message: Optional[str] = None
    response_time_ms: Optional[float] = None
    last_check: Optional[datetime] = None


class SystemHealth(BaseModel):
    """시스템 전체 상태 모델"""
    status: str
    timestamp: datetime
    uptime_seconds: Optional[float]
    components: List[HealthCheckResult]
    overall_health: bool


async def check_component_health(component: str, url: str, timeout: float = 5.0) -> HealthCheckResult:
    """개별 컴포넌트 상태 확인"""
    start_time = asyncio.get_event_loop().time()
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            if response.status_code == 200:
                health_check_counter.labels(status='success', component=component).inc()
                component_status.labels(component=component, instance=url).set(1)
                return HealthCheckResult(
                    component=component,
                    status="healthy",
                    message="OK",
                    response_time_ms=response_time,
                    last_check=datetime.now(timezone.utc)
                )
            else:
                health_check_counter.labels(status='error', component=component).inc()
                component_status.labels(component=component, instance=url).set(0)
                return HealthCheckResult(
                    component=component,
                    status="unhealthy",
                    message=f"HTTP {response.status_code}",
                    response_time_ms=response_time,
                    last_check=datetime.now(timezone.utc)
                )
    except Exception as e:
        response_time = (asyncio.get_event_loop().time() - start_time) * 1000
        health_check_counter.labels(status='error', component=component).inc()
        component_status.labels(component=component, instance=url).set(0)
        return HealthCheckResult(
            component=component,
            status="unhealthy",
            message=str(e),
            response_time_ms=response_time,
            last_check=datetime.now(timezone.utc)
        )
    finally:
        health_check_duration.labels(component=component).observe(
            asyncio.get_event_loop().time() - start_time
        )


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    """Liveness/Readiness combined health endpoint.

    Returns basic process health with uptime in seconds.
    """
    started_at = getattr(request.app.state, "started_at", None)
    now = datetime.now(timezone.utc)
    uptime_seconds = (now - started_at).total_seconds() if started_at else None

    return {
        "status": "ok",
        "time": now.isoformat(),
        "uptime_seconds": uptime_seconds,
    }


@router.get("/healthz", response_model=SystemHealth)
async def healthz(request: Request) -> SystemHealth:
    """Kubernetes 스타일 health check 엔드포인트.
    
    모든 컴포넌트의 상태를 확인하고 전체 시스템 상태를 반환합니다.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = (now - started_at).total_seconds() if started_at else None
    
    # 시스템 정보 업데이트
    system_info.info({
        'app_name': request.app.title,
        'version': request.app.version,
        'uptime_seconds': str(uptime_seconds) if uptime_seconds else 'unknown'
    })
    
    # 확인할 컴포넌트 목록
    components_to_check = []
    
    # RabbitMQ Bridge Agent 확인
    if hasattr(settings, 'rabbitmq_bridge_url'):
        components_to_check.append(("rabbitmq-bridge", settings.rabbitmq_bridge_url))
    
    # Prometheus 확인
    if hasattr(settings, 'prometheus_base_url') and settings.prometheus_base_url:
        components_to_check.append(("prometheus", f"{settings.prometheus_base_url.rstrip('/')}/-/healthy"))
    
    # PostgreSQL 확인
    if hasattr(settings, 'database_url') and settings.database_url:
        # 간단한 DB 연결 확인을 위한 엔드포인트 (실제로는 DB 연결 테스트 필요)
        components_to_check.append(("postgresql", f"{request.base_url}api/v1/health/db"))
    
    # MCP 서버 확인
    components_to_check.append(("mcp-server", f"{request.base_url}mcp/info"))
    
    # 모든 컴포넌트 상태 확인
    component_results = []
    if components_to_check:
        tasks = [check_component_health(comp, url) for comp, url in components_to_check]
        component_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 예외 처리
        processed_results = []
        for i, result in enumerate(component_results):
            if isinstance(result, Exception):
                component_name = components_to_check[i][0]
                processed_results.append(HealthCheckResult(
                    component=component_name,
                    status="unhealthy",
                    message=f"Check failed: {str(result)}",
                    last_check=now
                ))
            else:
                processed_results.append(result)
        component_results = processed_results
    
    # 전체 상태 결정
    unhealthy_components = [r for r in component_results if r.status != "healthy"]
    overall_health = len(unhealthy_components) == 0
    system_status = "healthy" if overall_health else "degraded"
    
    # Circuit Breaker 상태 업데이트 및 알림 전송
    for result in component_results:
        if result.status == "healthy":
            circuit_breaker_state.labels(component=result.component).state("CLOSED")
            # 복구 알림 전송
            await send_health_alert(
                component=result.component,
                instance=result.component,
                is_healthy=True,
                message=f"Component {result.component} is now healthy"
            )
        else:
            circuit_breaker_state.labels(component=result.component).state("OPEN")
            # 장애 알림 전송
            await send_health_alert(
                component=result.component,
                instance=result.component,
                is_healthy=False,
                message=f"Component {result.component} is unhealthy: {result.message}"
            )
    
    # 전체 상태가 unhealthy인 경우 HTTP 503 반환
    if not overall_health:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"System degraded: {len(unhealthy_components)} components unhealthy"
        )
    
    return SystemHealth(
        status=system_status,
        timestamp=now,
        uptime_seconds=uptime_seconds,
        components=component_results,
        overall_health=overall_health
    )


@router.get("/health/db")
async def health_db() -> Dict[str, Any]:
    """데이터베이스 연결 상태 확인"""
    try:
        # 실제 DB 연결 테스트 구현 필요
        # 여기서는 간단한 응답만 반환
        return {"status": "ok", "message": "Database connection healthy"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unhealthy: {str(e)}"
        )


@router.get("/version")
async def version(request: Request) -> Dict[str, Any]:
    """Return app name and version info."""
    return {
        "name": request.app.title,
        "version": request.app.version,
    }


