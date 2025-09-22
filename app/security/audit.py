"""
감사 로깅 모듈
"""
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
from fastapi import Request
from app.core.config import settings

class AuditEventType(Enum):
    """감사 이벤트 타입"""
    # 인증 관련
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    MFA_ENABLE = "mfa_enable"
    MFA_DISABLE = "mfa_disable"
    
    # 권한 관련
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    ROLE_CHANGED = "role_changed"
    
    # 리소스 관련
    RESOURCE_CREATED = "resource_created"
    RESOURCE_UPDATED = "resource_updated"
    RESOURCE_DELETED = "resource_deleted"
    RESOURCE_ACCESSED = "resource_accessed"
    
    # 배포 관련
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_COMPLETED = "rollback_completed"
    
    # 시스템 관련
    CONFIGURATION_CHANGED = "configuration_changed"
    SECURITY_ALERT = "security_alert"
    SYSTEM_ERROR = "system_error"

class AuditLogger:
    """감사 로깅을 담당하는 클래스"""
    
    def __init__(self):
        self.log_file = "audit.log"
        self.max_log_size = 100 * 1024 * 1024  # 100MB
        self.retention_days = 365
    
    def _get_client_info(self, request: Request) -> Dict[str, Any]:
        """클라이언트 정보 추출"""
        return {
            "ip_address": self._get_client_ip(request),
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            "referer": request.headers.get("Referer"),
            "host": request.headers.get("Host"),
            "x_forwarded_for": request.headers.get("X-Forwarded-For"),
            "x_real_ip": request.headers.get("X-Real-IP")
        }
    
    def _get_client_ip(self, request: Request) -> str:
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
    
    def _format_log_entry(self, event_type: AuditEventType, user_id: Optional[str], 
                         details: Dict[str, Any], request: Optional[Request] = None) -> Dict[str, Any]:
        """로그 엔트리 포맷팅"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type.value,
            "user_id": user_id,
            "details": details
        }
        
        if request:
            log_entry["client_info"] = self._get_client_info(request)
            log_entry["request_info"] = {
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "query_params": dict(request.query_params)
            }
        
        return log_entry
    
    def log_event(self, event_type: AuditEventType, user_id: Optional[str] = None,
                  details: Optional[Dict[str, Any]] = None, request: Optional[Request] = None) -> None:
        """감사 이벤트 로깅"""
        if details is None:
            details = {}
        
        log_entry = self._format_log_entry(event_type, user_id, details, request)
        
        # 로그 파일에 기록
        self._write_to_log_file(log_entry)
        
        # 데이터베이스에 기록 (선택적)
        self._write_to_database(log_entry)
    
    def _write_to_log_file(self, log_entry: Dict[str, Any]) -> None:
        """로그 파일에 기록"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # 로그 파일 쓰기 실패 시 콘솔에 출력
            print(f"Failed to write to audit log file: {e}")
            print(f"Log entry: {json.dumps(log_entry, ensure_ascii=False)}")
    
    def _write_to_database(self, log_entry: Dict[str, Any]) -> None:
        """데이터베이스에 기록 (구현 필요)"""
        # TODO: 데이터베이스에 감사 로그 저장
        pass
    
    def log_authentication(self, user_id: str, success: bool, request: Request, 
                          details: Optional[Dict[str, Any]] = None) -> None:
        """인증 이벤트 로깅"""
        if details is None:
            details = {}
        
        event_type = AuditEventType.LOGIN_SUCCESS if success else AuditEventType.LOGIN_FAILURE
        details.update({
            "success": success,
            "timestamp": time.time()
        })
        
        self.log_event(event_type, user_id, details, request)
    
    def log_permission_check(self, user_id: str, resource: str, action: str, 
                           granted: bool, request: Request) -> None:
        """권한 확인 이벤트 로깅"""
        event_type = AuditEventType.PERMISSION_GRANTED if granted else AuditEventType.PERMISSION_DENIED
        details = {
            "resource": resource,
            "action": action,
            "granted": granted,
            "timestamp": time.time()
        }
        
        self.log_event(event_type, user_id, details, request)
    
    def log_resource_access(self, user_id: str, resource_type: str, resource_id: str,
                          action: str, request: Request, details: Optional[Dict[str, Any]] = None) -> None:
        """리소스 접근 이벤트 로깅"""
        if details is None:
            details = {}
        
        details.update({
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "timestamp": time.time()
        })
        
        self.log_event(AuditEventType.RESOURCE_ACCESSED, user_id, details, request)
    
    def log_deployment(self, user_id: str, deployment_id: str, action: str, 
                      success: bool, request: Request, details: Optional[Dict[str, Any]] = None) -> None:
        """배포 이벤트 로깅"""
        if details is None:
            details = {}
        
        event_type_map = {
            "start": AuditEventType.DEPLOYMENT_STARTED,
            "complete": AuditEventType.DEPLOYMENT_COMPLETED,
            "fail": AuditEventType.DEPLOYMENT_FAILED,
            "rollback_start": AuditEventType.ROLLBACK_STARTED,
            "rollback_complete": AuditEventType.ROLLBACK_COMPLETED
        }
        
        event_type = event_type_map.get(action, AuditEventType.DEPLOYMENT_STARTED)
        
        details.update({
            "deployment_id": deployment_id,
            "action": action,
            "success": success,
            "timestamp": time.time()
        })
        
        self.log_event(event_type, user_id, details, request)
    
    def log_security_alert(self, alert_type: str, severity: str, details: Dict[str, Any],
                          request: Optional[Request] = None) -> None:
        """보안 알림 이벤트 로깅"""
        details.update({
            "alert_type": alert_type,
            "severity": severity,
            "timestamp": time.time()
        })
        
        self.log_event(AuditEventType.SECURITY_ALERT, None, details, request)
    
    def get_audit_logs(self, user_id: Optional[str] = None, event_type: Optional[str] = None,
                      start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """감사 로그 조회"""
        # TODO: 데이터베이스에서 감사 로그 조회 구현
        return []
    
    def cleanup_old_logs(self) -> None:
        """오래된 로그 정리"""
        # TODO: 오래된 로그 파일 정리 구현
        pass
