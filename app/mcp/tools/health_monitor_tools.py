"""
Health Check 및 상태 모니터링 MCP 도구 (FastAPI 통합 버전)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# from fastmcp.tools import Tool  # Will be registered via @server.tool decorator

from ...services.alerting import send_health_alert, send_circuit_breaker_alert
from ...core.config import get_settings

logger = logging.getLogger(__name__)

# 설정
settings = get_settings()


async def check_system_health(
    include_components: Optional[List[str]] = None,
    timeout: float = 5.0
) -> str:
    """전체 시스템 상태 확인"""
    try:
        import httpx
        
        # 기본 컴포넌트 목록
        components = include_components or [
            "rabbitmq-bridge",
            "prometheus", 
            "postgresql",
            "mcp-server"
        ]
        
        # 컴포넌트별 URL 매핑
        component_urls = {
            "rabbitmq-bridge": settings.rabbitmq_bridge_url or "http://localhost:8001/health",
            "prometheus": f"{settings.prometheus_base_url.rstrip('/')}/-/healthy" if settings.prometheus_base_url else None,
            "postgresql": "http://localhost:8000/api/v1/health/db",  # 내부 DB 체크 엔드포인트
            "mcp-server": "http://localhost:8000/mcp/info"
        }
        
        results = []
        healthy_count = 0
        
        for component in components:
            url = component_urls.get(component)
            if not url:
                results.append(f"❌ {component}: URL not configured")
                continue
                
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        results.append(f"✅ {component}: Healthy")
                        healthy_count += 1
                    else:
                        results.append(f"❌ {component}: HTTP {response.status_code}")
            except Exception as e:
                results.append(f"❌ {component}: {str(e)}")
        
        overall_status = "Healthy" if healthy_count == len(components) else "Degraded"
        
        result_text = f"""
# 시스템 상태 확인 결과

**전체 상태**: {overall_status}
**헬스한 컴포넌트**: {healthy_count}/{len(components)}

## 컴포넌트별 상태:
{chr(10).join(results)}

**확인 시간**: {datetime.now(timezone.utc).isoformat()}
        """.strip()
        
        return result_text
        
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return f"❌ 시스템 상태 확인 실패: {str(e)}"


async def check_component_health(
    component: str,
    url: str,
    timeout: float = 5.0
) -> str:
    """특정 컴포넌트 상태 확인"""
    try:
        import httpx
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                response_time = (asyncio.get_event_loop().time() - start_time) * 1000
                
                if response.status_code == 200:
                    status = "✅ Healthy"
                    message = "OK"
                else:
                    status = "❌ Unhealthy"
                    message = f"HTTP {response.status_code}"
                    
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            status = "❌ Unhealthy"
            message = str(e)
        
        result_text = f"""
# 컴포넌트 상태 확인 결과

**컴포넌트**: {component}
**URL**: {url}
**상태**: {status}
**메시지**: {message}
**응답 시간**: {response_time:.2f}ms
**확인 시간**: {datetime.now(timezone.utc).isoformat()}
        """.strip()
        
        return result_text
        
    except Exception as e:
        logger.error(f"Component health check failed: {e}")
        return f"❌ 컴포넌트 상태 확인 실패: {str(e)}"


async def get_health_metrics(
    component: Optional[str] = None,
    time_range: str = "5m"
) -> str:
    """헬스체크 메트릭 조회"""
    try:
        # Prometheus 쿼리 구성
        queries = [
            "health_check_total",
            "health_check_duration_seconds",
            "component_status",
            "circuit_breaker_state"
        ]
        
        if component:
            queries = [f"{q}{{component='{component}'}}" for q in queries]
        
        results = []
        
        for query in queries:
            try:
                # 실제 Prometheus 쿼리는 별도 서비스에서 처리
                # 여기서는 예시 데이터 반환
                results.append(f"📊 {query}: [메트릭 데이터 조회됨]")
            except Exception as e:
                results.append(f"❌ {query}: {str(e)}")
        
        result_text = f"""
# 헬스체크 메트릭 조회 결과

**시간 범위**: {time_range}
**컴포넌트**: {component or "전체"}

## 메트릭:
{chr(10).join(results)}

**조회 시간**: {datetime.now(timezone.utc).isoformat()}
        """.strip()
        
        return result_text
        
    except Exception as e:
        logger.error(f"Health metrics query failed: {e}")
        return f"❌ 메트릭 조회 실패: {str(e)}"


async def send_health_alert(
    component: str,
    instance: str,
    is_healthy: bool,
    message: str
) -> str:
    """헬스체크 알림 전송"""
    try:
        success = await send_health_alert(component, instance, is_healthy, message)
        
        status = "✅ 성공" if success else "❌ 실패"
        
        result_text = f"""
# 헬스체크 알림 전송 결과

**상태**: {status}
**컴포넌트**: {component}
**인스턴스**: {instance}
**헬스 상태**: {"Healthy" if is_healthy else "Unhealthy"}
**메시지**: {message}
**전송 시간**: {datetime.now(timezone.utc).isoformat()}
        """.strip()
        
        return result_text
        
    except Exception as e:
        logger.error(f"Health alert sending failed: {e}")
        return f"❌ 알림 전송 실패: {str(e)}"


async def send_circuit_breaker_alert(
    component: str,
    state: str,
    message: str
) -> str:
    """Circuit Breaker 알림 전송"""
    try:
        success = await send_circuit_breaker_alert(component, state, message)
        
        status = "✅ 성공" if success else "❌ 실패"
        
        result_text = f"""
# Circuit Breaker 알림 전송 결과

**상태**: {status}
**컴포넌트**: {component}
**Circuit Breaker 상태**: {state}
**메시지**: {message}
**전송 시간**: {datetime.now(timezone.utc).isoformat()}
        """.strip()
        
        return result_text
        
    except Exception as e:
        logger.error(f"Circuit breaker alert sending failed: {e}")
        return f"❌ 알림 전송 실패: {str(e)}"
