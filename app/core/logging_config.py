"""
로깅 설정
"""

import logging
import sys
from typing import Dict, Any
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """컬러 로그 포매터"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset_color = self.COLORS['RESET']
        
        # 원본 포맷터 사용
        formatted = super().format(record)
        
        # 컬러 추가
        return f"{log_color}{formatted}{reset_color}"


def setup_logging(level: str = "INFO", enable_colors: bool = True) -> None:
    """로깅 설정"""
    
    # 로그 레벨 설정
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # 기존 핸들러 제거
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 콘솔 핸들러 생성
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # 포매터 설정
    if enable_colors:
        formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 파일 핸들러 생성 (선택적)
    try:
        file_handler = logging.FileHandler('app.log')
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # 파일 로깅 실패 시 무시
        pass
    
    # 특정 로거 레벨 설정
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("mcp").setLevel(logging.INFO)
    
    # 로깅 시작 메시지
    logger = logging.getLogger(__name__)
    logger.info("로깅 시스템이 초기화되었습니다")


def get_logger(name: str) -> logging.Logger:
    """로거 가져오기"""
    return logging.getLogger(name)


def log_request(request, response_time: float, status_code: int):
    """요청 로깅"""
    logger = get_logger("request")
    logger.info(
        f"{request.method} {request.url.path} - {status_code} - {response_time:.3f}s",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "response_time": response_time,
            "client_ip": request.client.host if request.client else "unknown"
        }
    )


def log_mcp_operation(operation: str, provider: str = None, tool_name: str = None, success: bool = True, error: str = None):
    """MCP 작업 로깅"""
    logger = get_logger("mcp")
    
    if success:
        logger.info(f"MCP {operation} 성공", extra={
            "operation": operation,
            "provider": provider,
            "tool_name": tool_name,
            "success": success
        })
    else:
        logger.error(f"MCP {operation} 실패: {error}", extra={
            "operation": operation,
            "provider": provider,
            "tool_name": tool_name,
            "success": success,
            "error": error
        })


