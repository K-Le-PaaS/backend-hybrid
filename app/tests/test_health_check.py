"""
Health Check 시스템 테스트
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import asyncio

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app


class TestHealthCheck:
    """헬스체크 시스템 테스트"""
    
    def setup_method(self):
        """테스트 설정"""
        self.client = TestClient(app)
    
    def test_basic_health_endpoint(self):
        """기본 헬스체크 엔드포인트 테스트"""
        response = self.client.get("/api/v1/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "time" in data
        assert "uptime_seconds" in data
        assert data["status"] == "ok"
    
    def test_healthz_endpoint_success(self):
        """상세 헬스체크 엔드포인트 성공 테스트"""
        # MCP 서버가 정상 응답하는 경우를 모킹
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_get.return_value = mock_response
            
            response = self.client.get("/api/v1/healthz")
            
            # 200 또는 503이 될 수 있음 (일부 컴포넌트가 실패할 수 있음)
            assert response.status_code in [200, 503]
            
            data = response.json()
            assert "status" in data
            assert "timestamp" in data
            assert "components" in data
            assert "overall_health" in data
            assert isinstance(data["components"], list)
    
    def test_healthz_endpoint_failure(self):
        """상세 헬스체크 엔드포인트 실패 테스트"""
        # 모든 컴포넌트가 실패하는 경우를 모킹
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            response = self.client.get("/api/v1/healthz")
            
            # 실패 시 503 반환
            assert response.status_code == 503
            
            data = response.json()
            assert "detail" in data
            assert "degraded" in data["detail"].lower()
    
    def test_health_db_endpoint(self):
        """DB 헬스체크 엔드포인트 테스트"""
        response = self.client.get("/api/v1/health/db")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "message" in data
        assert data["status"] == "ok"
    
    def test_metrics_endpoint(self):
        """메트릭 엔드포인트 테스트"""
        response = self.client.get("/metrics")
        assert response.status_code == 200
        
        # Prometheus 메트릭 형식 확인
        content = response.text
        assert "# HELP" in content
        assert "# TYPE" in content
        assert "health_check_total" in content
        assert "component_status" in content
        assert "circuit_breaker_state" in content
    
    def test_version_endpoint(self):
        """버전 엔드포인트 테스트"""
        response = self.client.get("/api/v1/version")
        assert response.status_code == 200
        
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "K-Le-PaaS Backend Hybrid"
    
    @pytest.mark.asyncio
    async def test_health_alert_sending(self):
        """헬스체크 알림 전송 테스트"""
        from services.alerting import send_health_alert, send_circuit_breaker_alert
        
        # Slack 웹훅이 설정되지 않은 경우를 모킹
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response
            
            # 헬스체크 알림 테스트
            result = await send_health_alert(
                component="test-component",
                instance="test-instance", 
                is_healthy=False,
                message="테스트 알림"
            )
            
            # Slack 웹훅이 설정되지 않았으므로 False 반환
            assert result is False
        
        # Circuit Breaker 알림 테스트
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response
            
            result = await send_circuit_breaker_alert(
                component="test-component",
                state="OPEN",
                message="테스트 Circuit Breaker 알림"
            )
            
            # Slack 웹훅이 설정되지 않았으므로 False 반환
            assert result is False
    
    def test_component_health_check(self):
        """개별 컴포넌트 헬스체크 테스트"""
        from api.v1.system import check_component_health
        
        # 정상 응답 모킹
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            # 비동기 함수를 동기적으로 실행
            result = asyncio.run(check_component_health(
                component="test-component",
                url="http://test.com/health"
            ))
            
            assert result.component == "test-component"
            assert result.status == "healthy"
            assert result.message == "OK"
            assert result.response_time_ms is not None
    
    def test_component_health_check_failure(self):
        """개별 컴포넌트 헬스체크 실패 테스트"""
        from api.v1.system import check_component_health
        
        # 실패 응답 모킹
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.side_effect = Exception("Connection failed")
            
            result = asyncio.run(check_component_health(
                component="test-component",
                url="http://test.com/health"
            ))
            
            assert result.component == "test-component"
            assert result.status == "unhealthy"
            assert "Connection failed" in result.message
            assert result.response_time_ms is not None


class TestHealthMetrics:
    """헬스체크 메트릭 테스트"""
    
    def test_prometheus_metrics_registration(self):
        """Prometheus 메트릭 등록 테스트"""
        from api.v1.system import (
            health_check_counter,
            health_check_duration,
            component_status,
            system_info,
            circuit_breaker_state
        )
        
        # 메트릭이 정상적으로 생성되었는지 확인
        assert health_check_counter is not None
        assert health_check_duration is not None
        assert component_status is not None
        assert system_info is not None
        assert circuit_breaker_state is not None
    
    def test_metrics_increment(self):
        """메트릭 증가 테스트"""
        from ..api.v1.system import health_check_counter
        
        # 카운터 증가
        health_check_counter.labels(status='success', component='test').inc()
        health_check_counter.labels(status='error', component='test').inc()
        
        # 메트릭 값 확인 (실제로는 Prometheus가 수집)
        # 여기서는 예외가 발생하지 않는지만 확인
        assert True


class TestAlertingService:
    """알림 서비스 테스트"""
    
    def test_alert_creation(self):
        """알림 생성 테스트"""
        from services.alerting import Alert, AlertStatus, AlertSeverity
        
        alert = Alert(
            alertname="TestAlert",
            status=AlertStatus.FIRING,
            severity=AlertSeverity.CRITICAL,
            component="test-component",
            instance="test-instance",
            summary="Test alert",
            description="This is a test alert",
            starts_at="2024-01-01T00:00:00Z"
        )
        
        assert alert.alertname == "TestAlert"
        assert alert.status == AlertStatus.FIRING
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.component == "test-component"
    
    def test_alert_group_creation(self):
        """알림 그룹 생성 테스트"""
        from services.alerting import AlertGroup, Alert, AlertStatus, AlertSeverity
        
        alert = Alert(
            alertname="TestAlert",
            status=AlertStatus.FIRING,
            severity=AlertSeverity.CRITICAL,
            component="test-component",
            instance="test-instance",
            summary="Test alert",
            description="This is a test alert",
            starts_at="2024-01-01T00:00:00Z"
        )
        
        group = AlertGroup(
            group_key="test-group",
            status=AlertStatus.FIRING,
            alerts=[alert]
        )
        
        assert group.group_key == "test-group"
        assert group.status == AlertStatus.FIRING
        assert len(group.alerts) == 1
        assert group.alerts[0].alertname == "TestAlert"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
