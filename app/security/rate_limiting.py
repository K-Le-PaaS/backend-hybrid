"""
Rate Limiting 모듈
"""
import time
from typing import Dict, Optional
from fastapi import HTTPException, Request, status
from app.core.config import settings

class RateLimiter:
    """Rate Limiting을 담당하는 클래스"""
    
    def __init__(self):
        self.requests = {}  # {key: [(timestamp, count), ...]}
        self.default_limits = {
            "login": {"requests": 5, "window": 300},  # 5분에 5회
            "api": {"requests": 100, "window": 60},   # 1분에 100회
            "deploy": {"requests": 10, "window": 300}, # 5분에 10회
            "upload": {"requests": 20, "window": 3600} # 1시간에 20회
        }
    
    def get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 주소 추출"""
        # X-Forwarded-For 헤더 확인 (프록시 환경)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # X-Real-IP 헤더 확인
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # 직접 연결
        return request.client.host if request.client else "unknown"
    
    def get_rate_limit_key(self, request: Request, limit_type: str = "api") -> str:
        """Rate limit 키 생성"""
        client_ip = self.get_client_ip(request)
        user_id = getattr(request.state, "user_id", None)
        
        if user_id:
            return f"{limit_type}:user:{user_id}"
        else:
            return f"{limit_type}:ip:{client_ip}"
    
    def is_rate_limited(self, key: str, limit_type: str = "api") -> bool:
        """Rate limit 확인"""
        limits = self.default_limits.get(limit_type, self.default_limits["api"])
        max_requests = limits["requests"]
        window_seconds = limits["window"]
        
        current_time = time.time()
        window_start = current_time - window_seconds
        
        # 해당 키의 요청 기록 가져오기
        if key not in self.requests:
            self.requests[key] = []
        
        # 윈도우 밖의 오래된 요청 제거
        self.requests[key] = [
            (timestamp, count) for timestamp, count in self.requests[key]
            if timestamp > window_start
        ]
        
        # 현재 윈도우 내 요청 수 계산
        current_requests = sum(count for _, count in self.requests[key])
        
        return current_requests >= max_requests
    
    def record_request(self, key: str, count: int = 1) -> None:
        """요청 기록"""
        current_time = time.time()
        
        if key not in self.requests:
            self.requests[key] = []
        
        self.requests[key].append((current_time, count))
    
    def get_remaining_requests(self, key: str, limit_type: str = "api") -> int:
        """남은 요청 수 반환"""
        limits = self.default_limits.get(limit_type, self.default_limits["api"])
        max_requests = limits["requests"]
        window_seconds = limits["window"]
        
        current_time = time.time()
        window_start = current_time - window_seconds
        
        if key not in self.requests:
            return max_requests
        
        # 윈도우 밖의 오래된 요청 제거
        self.requests[key] = [
            (timestamp, count) for timestamp, count in self.requests[key]
            if timestamp > window_start
        ]
        
        # 현재 윈도우 내 요청 수 계산
        current_requests = sum(count for _, count in self.requests[key])
        
        return max(0, max_requests - current_requests)
    
    def get_reset_time(self, key: str, limit_type: str = "api") -> float:
        """Rate limit 리셋 시간 반환"""
        limits = self.default_limits.get(limit_type, self.default_limits["api"])
        window_seconds = limits["window"]
        
        if key not in self.requests or not self.requests[key]:
            return time.time() + window_seconds
        
        # 가장 오래된 요청 시간 + 윈도우 시간
        oldest_request = min(timestamp for timestamp, _ in self.requests[key])
        return oldest_request + window_seconds
    
    def check_rate_limit(self, request: Request, limit_type: str = "api") -> None:
        """Rate limit 확인 및 예외 발생"""
        key = self.get_rate_limit_key(request, limit_type)
        
        if self.is_rate_limited(key, limit_type):
            remaining = self.get_remaining_requests(key, limit_type)
            reset_time = self.get_reset_time(key, limit_type)
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded",
                    "limit_type": limit_type,
                    "remaining_requests": remaining,
                    "reset_time": reset_time,
                    "retry_after": int(reset_time - time.time())
                },
                headers={
                    "X-RateLimit-Limit": str(self.default_limits[limit_type]["requests"]),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(int(reset_time)),
                    "Retry-After": str(int(reset_time - time.time()))
                }
            )
        
        # 요청 기록
        self.record_request(key)
    
    def get_rate_limit_info(self, request: Request, limit_type: str = "api") -> Dict:
        """Rate limit 정보 반환"""
        key = self.get_rate_limit_key(request, limit_type)
        limits = self.default_limits.get(limit_type, self.default_limits["api"])
        
        return {
            "limit_type": limit_type,
            "max_requests": limits["requests"],
            "window_seconds": limits["window"],
            "remaining_requests": self.get_remaining_requests(key, limit_type),
            "reset_time": self.get_reset_time(key, limit_type),
            "is_limited": self.is_rate_limited(key, limit_type)
        }
    
    def cleanup_old_requests(self, max_age_seconds: int = 3600) -> None:
        """오래된 요청 기록 정리"""
        current_time = time.time()
        cutoff_time = current_time - max_age_seconds
        
        for key in list(self.requests.keys()):
            # 오래된 요청 제거
            self.requests[key] = [
                (timestamp, count) for timestamp, count in self.requests[key]
                if timestamp > cutoff_time
            ]
            
            # 빈 리스트 제거
            if not self.requests[key]:
                del self.requests[key]
