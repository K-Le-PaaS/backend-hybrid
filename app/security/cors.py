"""
CORS 설정 모듈
"""
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

class CORSManager:
    """CORS 관리를 담당하는 클래스"""
    
    def __init__(self):
        self.allowed_origins = self._get_allowed_origins()
        self.allowed_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
        self.allowed_headers = [
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-CSRF-Token",
            "X-API-Key"
        ]
        self.exposed_headers = [
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset"
        ]
        self.allow_credentials = True
        self.max_age = 3600  # 1시간
    
    def _get_allowed_origins(self) -> List[str]:
        """허용된 오리진 목록 반환"""
        origins = [
            "http://localhost:3000",  # 개발 환경
            "http://localhost:5173",  # Vite 개발 서버
            "https://k-le-paas.com",  # 프로덕션 도메인
            "https://www.k-le-paas.com",
            "https://staging.k-le-paas.com"  # 스테이징 도메인
        ]
        
        # 환경변수에서 추가 오리진 가져오기
        if hasattr(settings, 'cors_origins') and settings.cors_origins:
            origins.extend(settings.cors_origins.split(','))
        
        return origins
    
    def get_cors_middleware(self) -> CORSMiddleware:
        """CORS 미들웨어 반환"""
        return CORSMiddleware(
            allow_origins=self.allowed_origins,
            allow_credentials=self.allow_credentials,
            allow_methods=self.allowed_methods,
            allow_headers=self.allowed_headers,
            expose_headers=self.exposed_headers,
            max_age=self.max_age
        )
    
    def is_origin_allowed(self, origin: str) -> bool:
        """오리진이 허용되는지 확인"""
        return origin in self.allowed_origins
    
    def add_origin(self, origin: str) -> None:
        """새로운 오리진 추가"""
        if origin not in self.allowed_origins:
            self.allowed_origins.append(origin)
    
    def remove_origin(self, origin: str) -> None:
        """오리진 제거"""
        if origin in self.allowed_origins:
            self.allowed_origins.remove(origin)
    
    def get_cors_headers(self, origin: Optional[str] = None) -> dict:
        """CORS 헤더 반환"""
        headers = {
            "Access-Control-Allow-Methods": ", ".join(self.allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self.allowed_headers),
            "Access-Control-Expose-Headers": ", ".join(self.exposed_headers),
            "Access-Control-Max-Age": str(self.max_age)
        }
        
        if origin and self.is_origin_allowed(origin):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        
        return headers
    
    def validate_cors_request(self, origin: str, method: str, headers: List[str]) -> bool:
        """CORS 요청 유효성 검사"""
        # 오리진 검사
        if not self.is_origin_allowed(origin):
            return False
        
        # 메서드 검사
        if method not in self.allowed_methods:
            return False
        
        # 헤더 검사 (간단한 검사)
        for header in headers:
            if header.lower() not in [h.lower() for h in self.allowed_headers]:
                return False
        
        return True
