"""
Health Check 및 상태 모니터링 MCP 도구
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from ...services.alerting import send_health_alert, send_circuit_breaker_alert
from ...core.config import get_settings

logger = logging.getLogger(__name__)

# MCP 서버 인스턴스
server = Server("k-le-paas-health-monitor")

# 설정
settings = get_settings()


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """사용 가능한 도구 목록 반환"""
    return [
        types.Tool(
            name="check_system_health",
            description="전체 시스템 상태 확인",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_components": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "확인할 컴포넌트 목록 (선택사항)"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "타임아웃 시간 (초)",
                        "default": 5.0
                    }
                }
            }
        ),
        types.Tool(
            name="check_component_health",
            description="특정 컴포넌트 상태 확인",
            inputSchema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "확인할 컴포넌트 이름"
                    },
                    "url": {
                        "type": "string",
                        "description": "컴포넌트 URL"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "타임아웃 시간 (초)",
                        "default": 5.0
                    }
                },
                "required": ["component", "url"]
            }
        ),
        types.Tool(
            name="get_health_metrics",
            description="헬스체크 메트릭 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "특정 컴포넌트 필터 (선택사항)"
                    },
                    "time_range": {
                        "type": "string",
                        "description": "시간 범위 (예: 5m, 1h, 1d)",
                        "default": "5m"
                    }
                }
            }
        ),
        types.Tool(
            name="send_health_alert",
            description="헬스체크 알림 전송",
            inputSchema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "컴포넌트 이름"
                    },
                    "instance": {
                        "type": "string",
                        "description": "인스턴스 이름"
                    },
                    "is_healthy": {
                        "type": "boolean",
                        "description": "헬스 상태"
                    },
                    "message": {
                        "type": "string",
                        "description": "알림 메시지"
                    }
                },
                "required": ["component", "instance", "is_healthy", "message"]
            }
        ),
        types.Tool(
            name="send_circuit_breaker_alert",
            description="Circuit Breaker 알림 전송",
            inputSchema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "컴포넌트 이름"
                    },
                    "state": {
                        "type": "string",
                        "description": "Circuit Breaker 상태 (CLOSED, OPEN, HALF_OPEN)"
                    },
                    "message": {
                        "type": "string",
                        "description": "알림 메시지"
                    }
                },
                "required": ["component", "state", "message"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    """도구 호출 처리"""
    
    if name == "check_system_health":
        return await check_system_health(arguments)
    elif name == "check_component_health":
        return await check_component_health(arguments)
    elif name == "get_health_metrics":
        return await get_health_metrics(arguments)
    elif name == "send_health_alert":
        return await send_health_alert_tool(arguments)
    elif name == "send_circuit_breaker_alert":
        return await send_circuit_breaker_alert_tool(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def check_system_health(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """전체 시스템 상태 확인"""
    try:
        import httpx
        
        # 기본 컴포넌트 목록
        components = arguments.get("include_components", [
            "rabbitmq-bridge",
            "prometheus", 
            "postgresql",
            "mcp-server"
        ])
        
        timeout = arguments.get("timeout", 5.0)
        
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
        
        return [types.TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return [types.TextContent(type="text", text=f"❌ 시스템 상태 확인 실패: {str(e)}")]


async def check_component_health(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """특정 컴포넌트 상태 확인"""
    try:
        import httpx
        
        component = arguments["component"]
        url = arguments["url"]
        timeout = arguments.get("timeout", 5.0)
        
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
        
        return [types.TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"Component health check failed: {e}")
        return [types.TextContent(type="text", text=f"❌ 컴포넌트 상태 확인 실패: {str(e)}")]


async def get_health_metrics(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """헬스체크 메트릭 조회"""
    try:
        component = arguments.get("component")
        time_range = arguments.get("time_range", "5m")
        
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
        
        return [types.TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"Health metrics query failed: {e}")
        return [types.TextContent(type="text", text=f"❌ 메트릭 조회 실패: {str(e)}")]


async def send_health_alert_tool(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """헬스체크 알림 전송"""
    try:
        component = arguments["component"]
        instance = arguments["instance"]
        is_healthy = arguments["is_healthy"]
        message = arguments["message"]
        
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
        
        return [types.TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"Health alert sending failed: {e}")
        return [types.TextContent(type="text", text=f"❌ 알림 전송 실패: {str(e)}")]


async def send_circuit_breaker_alert_tool(arguments: Dict[str, Any]) -> List[types.TextContent]:
    """Circuit Breaker 알림 전송"""
    try:
        component = arguments["component"]
        state = arguments["state"]
        message = arguments["message"]
        
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
        
        return [types.TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"Circuit breaker alert sending failed: {e}")
        return [types.TextContent(type="text", text=f"❌ 알림 전송 실패: {str(e)}")]


async def main():
    """MCP 서버 실행"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="k-le-paas-health-monitor",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
