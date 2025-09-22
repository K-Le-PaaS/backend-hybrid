"""
통합 에러 처리 시스템
"""

import logging
import traceback
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..mcp.external.errors import MCPExternalError

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """통합 에러 처리 미들웨어"""
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except MCPExternalError as e:
            logger.error(f"MCP External Error: {e.message}", extra={
                "error_code": e.code,
                "error_message": e.message,
                "path": request.url.path,
                "method": request.method
            })
            return JSONResponse(
                status_code=400,
                content={
                    "error": "MCP External Error",
                    "code": e.code,
                    "message": e.message,
                    "path": request.url.path
                }
            )
        except HTTPException as e:
            logger.warning(f"HTTP Exception: {e.detail}", extra={
                "status_code": e.status_code,
                "path": request.url.path,
                "method": request.method
            })
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": "HTTP Exception",
                    "message": e.detail,
                    "path": request.url.path
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", extra={
                "path": request.url.path,
                "method": request.method,
                "traceback": traceback.format_exc()
            })
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                    "path": request.url.path
                }
            )


def setup_error_handlers(app):
    """에러 핸들러 설정"""
    # 미들웨어 추가
    app.add_middleware(ErrorHandlerMiddleware)
    
    # 글로벌 예외 핸들러
    @app.exception_handler(MCPExternalError)
    async def mcp_external_error_handler(request: Request, exc: MCPExternalError):
        logger.error(f"MCP External Error: {exc.message}", extra={
            "error_code": exc.code,
            "error_message": exc.message,
            "path": request.url.path,
            "method": request.method
        })
        return JSONResponse(
            status_code=400,
            content={
                "error": "MCP External Error",
                "code": exc.code,
                "message": exc.message,
                "path": request.url.path
            }
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(f"HTTP Exception: {exc.detail}", extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        })
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTP Exception",
                "message": exc.detail,
                "path": request.url.path
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unexpected error: {str(exc)}", extra={
            "path": request.url.path,
            "method": request.method,
            "traceback": traceback.format_exc()
        })
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "path": request.url.path
            }
        )


def log_mcp_tool_call(tool_name: str, arguments: Dict[str, Any], success: bool, error: Optional[str] = None):
    """MCP 도구 호출 로깅"""
    logger.info(f"MCP Tool Call: {tool_name}", extra={
        "tool_name": tool_name,
        "arguments": arguments,
        "success": success,
        "error": error
    })


def log_external_mcp_call(provider: str, tool_name: str, success: bool, error: Optional[str] = None):
    """외부 MCP 서버 호출 로깅"""
    logger.info(f"External MCP Call: {provider}.{tool_name}", extra={
        "provider": provider,
        "tool_name": tool_name,
        "success": success,
        "error": error
    })


