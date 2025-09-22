"""
Prometheus 메트릭 수집을 위한 모듈
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response
import time
from typing import Callable

# HTTP 요청 메트릭
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# 애플리케이션 메트릭
active_connections = Gauge(
    'active_connections',
    'Number of active connections'
)

deployment_requests_total = Counter(
    'deployment_requests_total',
    'Total deployment requests',
    ['environment', 'status']
)

rollback_requests_total = Counter(
    'rollback_requests_total',
    'Total rollback requests',
    ['environment', 'status']
)

# 데이터베이스 메트릭
db_connections_active = Gauge(
    'db_connections_active',
    'Number of active database connections'
)

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['query_type']
)

# Redis 메트릭
redis_operations_total = Counter(
    'redis_operations_total',
    'Total Redis operations',
    ['operation', 'status']
)

redis_connection_pool_size = Gauge(
    'redis_connection_pool_size',
    'Redis connection pool size'
)

# MCP 메트릭
mcp_requests_total = Counter(
    'mcp_requests_total',
    'Total MCP requests',
    ['provider', 'tool', 'status']
)

mcp_request_duration_seconds = Histogram(
    'mcp_request_duration_seconds',
    'MCP request duration in seconds',
    ['provider', 'tool']
)

# LLM 메트릭
llm_requests_total = Counter(
    'llm_requests_total',
    'Total LLM requests',
    ['provider', 'model', 'status']
)

llm_tokens_total = Counter(
    'llm_tokens_total',
    'Total LLM tokens processed',
    ['provider', 'model', 'type']
)

llm_request_duration_seconds = Histogram(
    'llm_request_duration_seconds',
    'LLM request duration in seconds',
    ['provider', 'model']
)

def track_http_request(func: Callable) -> Callable:
    """HTTP 요청 메트릭을 추적하는 데코레이터"""
    async def wrapper(request: Request, *args, **kwargs):
        start_time = time.time()
        
        # 요청 정보 추출
        method = request.method
        endpoint = request.url.path
        
        try:
            response = await func(request, *args, **kwargs)
            status_code = response.status_code if hasattr(response, 'status_code') else 200
            
            # 메트릭 기록
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status_code=str(status_code)
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(time.time() - start_time)
            
            return response
            
        except Exception as e:
            # 에러 발생 시 메트릭 기록
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status_code='500'
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(time.time() - start_time)
            
            raise e
    
    return wrapper

def track_database_query(query_type: str):
    """데이터베이스 쿼리 메트릭을 추적하는 데코레이터"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                db_query_duration_seconds.labels(
                    query_type=query_type
                ).observe(time.time() - start_time)
                
                return result
                
            except Exception as e:
                db_query_duration_seconds.labels(
                    query_type=query_type
                ).observe(time.time() - start_time)
                raise e
        
        return wrapper
    return decorator

def track_redis_operation(operation: str):
    """Redis 작업 메트릭을 추적하는 데코레이터"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                
                redis_operations_total.labels(
                    operation=operation,
                    status='success'
                ).inc()
                
                return result
                
            except Exception as e:
                redis_operations_total.labels(
                    operation=operation,
                    status='error'
                ).inc()
                raise e
        
        return wrapper
    return decorator

def track_mcp_request(provider: str, tool: str):
    """MCP 요청 메트릭을 추적하는 데코레이터"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                mcp_requests_total.labels(
                    provider=provider,
                    tool=tool,
                    status='success'
                ).inc()
                
                mcp_request_duration_seconds.labels(
                    provider=provider,
                    tool=tool
                ).observe(time.time() - start_time)
                
                return result
                
            except Exception as e:
                mcp_requests_total.labels(
                    provider=provider,
                    tool=tool,
                    status='error'
                ).inc()
                
                mcp_request_duration_seconds.labels(
                    provider=provider,
                    tool=tool
                ).observe(time.time() - start_time)
                
                raise e
        
        return wrapper
    return decorator

def track_llm_request(provider: str, model: str):
    """LLM 요청 메트릭을 추적하는 데코레이터"""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                llm_requests_total.labels(
                    provider=provider,
                    model=model,
                    status='success'
                ).inc()
                
                llm_request_duration_seconds.labels(
                    provider=provider,
                    model=model
                ).observe(time.time() - start_time)
                
                # 토큰 수집 (결과에서 추출 가능한 경우)
                if isinstance(result, dict):
                    input_tokens = result.get('input_tokens', 0)
                    output_tokens = result.get('output_tokens', 0)
                    
                    if input_tokens:
                        llm_tokens_total.labels(
                            provider=provider,
                            model=model,
                            type='input'
                        ).inc(input_tokens)
                    
                    if output_tokens:
                        llm_tokens_total.labels(
                            provider=provider,
                            model=model,
                            type='output'
                        ).inc(output_tokens)
                
                return result
                
            except Exception as e:
                llm_requests_total.labels(
                    provider=provider,
                    model=model,
                    status='error'
                ).inc()
                
                llm_request_duration_seconds.labels(
                    provider=provider,
                    model=model
                ).observe(time.time() - start_time)
                
                raise e
        
        return wrapper
    return decorator

def get_metrics() -> str:
    """Prometheus 메트릭을 반환"""
    return generate_latest()

def get_metrics_content_type() -> str:
    """Prometheus 메트릭 컨텐츠 타입을 반환"""
    return CONTENT_TYPE_LATEST
