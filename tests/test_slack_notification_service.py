"""
Slack 알림 서비스 테스트

SlackNotificationService의 기능을 테스트합니다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.services.slack_notification_service import (
    SlackNotificationService,
    get_slack_notification_service,
    NotificationPriority
)
from app.models.slack_events import (
    SlackEventType,
    SlackChannelType,
    SlackNotificationRequest,
    SlackNotificationResponse
)


class TestSlackNotificationService:
    """SlackNotificationService 테스트 클래스"""
    
    @pytest.fixture
    def mock_slack_client(self):
        """Mock Slack 클라이언트"""
        client = AsyncMock()
        client.send_notification = AsyncMock()
        return client
    
    @pytest.fixture
    def notification_service(self, mock_slack_client):
        """테스트용 알림 서비스"""
        return SlackNotificationService(slack_client=mock_slack_client)
    
    @pytest.mark.asyncio
    async def test_send_deployment_notification_success(self, notification_service, mock_slack_client):
        """배포 성공 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#deployments",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_deployment_notification(
            event_type=SlackEventType.DEPLOYMENT_SUCCESS,
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0",
            status="success",
            deployment_id="deploy-123"
        )
        
        # Then
        assert response.success is True
        assert response.channel == "#deployments"
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.DEPLOYMENT_SUCCESS
        assert call_args.title == "✅ 배포 성공: test-app"
        assert "staging" in call_args.message
        assert "test-app:v1.0.0" in call_args.message
    
    @pytest.mark.asyncio
    async def test_send_deployment_notification_failure(self, notification_service, mock_slack_client):
        """배포 실패 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#deployments",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_deployment_notification(
            event_type=SlackEventType.DEPLOYMENT_FAILED,
            app_name="test-app",
            environment="production",
            image="test-app:v1.0.0",
            status="failed",
            error_message="Image pull failed",
            deployment_id="deploy-456"
        )
        
        # Then
        assert response.success is True
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.DEPLOYMENT_FAILED
        assert call_args.title == "❌ 배포 실패: test-app"
        assert "Image pull failed" in call_args.message
    
    @pytest.mark.asyncio
    async def test_send_build_notification(self, notification_service, mock_slack_client):
        """빌드 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#build",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_build_notification(
            event_type=SlackEventType.BUILD_SUCCESS,
            app_name="test-app",
            branch="main",
            commit_sha="abc123def456",
            status="success",
            build_url="https://github.com/test/repo/actions/runs/123"
        )
        
        # Then
        assert response.success is True
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.BUILD_SUCCESS
        assert call_args.title == "✅ 빌드 성공: test-app"
        assert "main" in call_args.message
        assert "abc123de" in call_args.message  # 커밋 SHA 일부
    
    @pytest.mark.asyncio
    async def test_send_error_notification(self, notification_service, mock_slack_client):
        """에러 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#errors",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_error_notification(
            event_type=SlackEventType.RATE_LIMITED,
            operation="deploy_application",
            error_code="429",
            error_message="Too many requests",
            context={"retry_after": 60}
        )
        
        # Then
        assert response.success is True
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.RATE_LIMITED
        assert call_args.title == "⏰ Rate Limited: deploy_application"
        assert "429" in call_args.message
        assert "Too many requests" in call_args.message
    
    @pytest.mark.asyncio
    async def test_send_health_notification(self, notification_service, mock_slack_client):
        """헬스 체크 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#health",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_health_notification(
            event_type=SlackEventType.HEALTH_DOWN,
            service_name="api-server",
            status="down",
            details="Connection timeout"
        )
        
        # Then
        assert response.success is True
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.HEALTH_DOWN
        assert call_args.title == "🔴 서비스 다운: api-server"
        assert "Connection timeout" in call_args.message
    
    @pytest.mark.asyncio
    async def test_send_custom_notification(self, notification_service, mock_slack_client):
        """사용자 정의 알림 테스트"""
        # Given
        mock_slack_client.send_notification.return_value = SlackNotificationResponse(
            success=True,
            channel="#custom",
            message_ts="1234567890.123456"
        )
        
        # When
        response = await notification_service.send_custom_notification(
            event_type=SlackEventType.SYSTEM_ERROR,
            title="Custom Alert",
            message="This is a custom notification",
            context={"custom_field": "custom_value"},
            channel="#custom",
            channel_type=SlackChannelType.ERRORS,
            priority="urgent"
        )
        
        # Then
        assert response.success is True
        mock_slack_client.send_notification.assert_called_once()
        
        # 요청 내용 검증
        call_args = mock_slack_client.send_notification.call_args[0][0]
        assert call_args.event_type == SlackEventType.SYSTEM_ERROR
        assert call_args.title == "Custom Alert"
        assert call_args.message == "This is a custom notification"
        assert call_args.channel == "#custom"
        assert call_args.priority == "urgent"
    
    @pytest.mark.asyncio
    async def test_priority_mapping(self, notification_service):
        """우선순위 매핑 테스트"""
        # 높은 우선순위 이벤트들
        high_priority_events = [
            SlackEventType.DEPLOYMENT_FAILED,
            SlackEventType.BUILD_FAILED,
            SlackEventType.UNAUTHORIZED,
            SlackEventType.SYSTEM_ERROR,
            SlackEventType.HEALTH_DOWN
        ]
        
        for event_type in high_priority_events:
            priority = notification_service._get_priority_for_event(event_type)
            if event_type in [SlackEventType.UNAUTHORIZED, SlackEventType.SYSTEM_ERROR]:
                assert priority == NotificationPriority.URGENT.value
            else:
                assert priority == NotificationPriority.HIGH.value
        
        # 일반 우선순위 이벤트들
        normal_priority_events = [
            SlackEventType.DEPLOYMENT_STARTED,
            SlackEventType.DEPLOYMENT_SUCCESS,
            SlackEventType.BUILD_STARTED,
            SlackEventType.BUILD_SUCCESS
        ]
        
        for event_type in normal_priority_events:
            priority = notification_service._get_priority_for_event(event_type)
            assert priority == NotificationPriority.NORMAL.value
    
    @pytest.mark.asyncio
    async def test_message_creation_deployment(self, notification_service):
        """배포 메시지 생성 테스트"""
        # 배포 시작
        title, message = notification_service._create_deployment_message(
            SlackEventType.DEPLOYMENT_STARTED,
            "test-app", "staging", "test-app:v1.0.0", "in_progress",
            progress=50, deployment_id="deploy-123"
        )
        assert title == "🚀 배포 시작: test-app"
        assert "staging" in message
        assert "test-app:v1.0.0" in message
        assert "50%" in message
        assert "deploy-123" in message
        
        # 배포 성공
        title, message = notification_service._create_deployment_message(
            SlackEventType.DEPLOYMENT_SUCCESS,
            "test-app", "production", "test-app:v1.0.0", "success",
            deployment_id="deploy-456"
        )
        assert title == "✅ 배포 성공: test-app"
        assert "production" in message
        assert "success" in message
        
        # 배포 실패
        title, message = notification_service._create_deployment_message(
            SlackEventType.DEPLOYMENT_FAILED,
            "test-app", "staging", "test-app:v1.0.0", "failed",
            error_message="Image not found", deployment_id="deploy-789"
        )
        assert title == "❌ 배포 실패: test-app"
        assert "Image not found" in message
    
    @pytest.mark.asyncio
    async def test_message_creation_build(self, notification_service):
        """빌드 메시지 생성 테스트"""
        # 빌드 시작
        title, message = notification_service._create_build_message(
            SlackEventType.BUILD_STARTED,
            "test-app", "main", "abc123def456", "in_progress",
            build_url="https://github.com/test/repo/actions/runs/123"
        )
        assert title == "🔨 빌드 시작: test-app"
        assert "main" in message
        assert "abc123de" in message
        assert "https://github.com/test/repo/actions/runs/123" in message
        
        # 빌드 실패
        title, message = notification_service._create_build_message(
            SlackEventType.BUILD_FAILED,
            "test-app", "feature-branch", "def456ghi789", "failed",
            error_message="Test failure"
        )
        assert title == "❌ 빌드 실패: test-app"
        assert "feature-branch" in message
        assert "Test failure" in message
    
    @pytest.mark.asyncio
    async def test_message_creation_error(self, notification_service):
        """에러 메시지 생성 테스트"""
        # Rate Limited
        title, message = notification_service._create_error_message(
            SlackEventType.RATE_LIMITED,
            "deploy_application", "429", "Too many requests"
        )
        assert title == "⏰ Rate Limited: deploy_application"
        assert "429" in message
        assert "Too many requests" in message
        
        # Unauthorized
        title, message = notification_service._create_error_message(
            SlackEventType.UNAUTHORIZED,
            "access_resource", "401", "Invalid token"
        )
        assert title == "🔒 인증 실패: access_resource"
        assert "401" in message
        assert "Invalid token" in message
    
    @pytest.mark.asyncio
    async def test_message_creation_health(self, notification_service):
        """헬스 체크 메시지 생성 테스트"""
        # 서비스 다운
        title, message = notification_service._create_health_message(
            SlackEventType.HEALTH_DOWN,
            "api-server", "down", "Connection timeout"
        )
        assert title == "🔴 서비스 다운: api-server"
        assert "down" in message
        assert "Connection timeout" in message
        
        # 서비스 복구
        title, message = notification_service._create_health_message(
            SlackEventType.HEALTH_RECOVERED,
            "api-server", "healthy", "All checks passed"
        )
        assert title == "🟢 서비스 복구: api-server"
        assert "healthy" in message
        assert "All checks passed" in message
    
    @pytest.mark.asyncio
    async def test_error_handling(self, notification_service, mock_slack_client):
        """에러 처리 테스트"""
        # Given - Slack 클라이언트에서 예외 발생
        mock_slack_client.send_notification.side_effect = Exception("Slack API error")
        
        # When
        response = await notification_service.send_deployment_notification(
            event_type=SlackEventType.DEPLOYMENT_SUCCESS,
            app_name="test-app",
            environment="staging",
            image="test-app:v1.0.0",
            status="success"
        )
        
        # Then
        assert response.success is False
        assert "Slack API error" in response.error
    
    @pytest.mark.asyncio
    async def test_get_slack_notification_service_singleton(self):
        """싱글톤 패턴 테스트"""
        service1 = get_slack_notification_service()
        service2 = get_slack_notification_service()
        
        assert service1 is service2
        assert isinstance(service1, SlackNotificationService)


class TestSlackClientWrapper:
    """SlackClientWrapper 테스트 클래스"""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock 설정"""
        settings = MagicMock()
        settings.slack_webhook_url = "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
        settings.slack_alert_channel_default = "#general"
        settings.slack_alert_channel_rate_limited = "#errors"
        settings.slack_alert_channel_unauthorized = "#security"
        settings.slack_alert_template_error = "[ERROR] {{operation}} failed: {{code}} - {{message}}"
        settings.slack_alert_template_health_down = "[HEALTH] Service down: {{code}} - {{message}}"
        return settings
    
    @pytest.mark.asyncio
    async def test_webhook_message_sending(self, mock_settings):
        """웹훅 메시지 전송 테스트"""
        with patch('app.services.slack_client.get_settings', return_value=mock_settings):
            from app.services.slack_client import SlackClientWrapper
            
            client = SlackClientWrapper()
            
            # httpx를 mock하여 실제 HTTP 요청 방지
            with patch('httpx.AsyncClient') as mock_client:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = "ok"
                
                mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
                
                # When
                response = await client._send_webhook_message(
                    channel="#test",
                    text="Test message"
                )
                
                # Then
                assert response["ok"] is True
                assert response["status"] == "success"
                assert response["channel"] == "#test"
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, mock_settings):
        """Rate limiting 테스트"""
        with patch('app.services.slack_client.get_settings', return_value=mock_settings):
            from app.services.slack_client import SlackClientWrapper
            
            client = SlackClientWrapper()
            
            # Rate limit 상태 설정
            client._retry_after["#test"] = 60.0
            
            # When
            is_rate_limited = await client._is_rate_limited("#test")
            
            # Then
            assert is_rate_limited is True
            
            # Rate limit 해제
            client._retry_after["#test"] = 0.0
            is_rate_limited = await client._is_rate_limited("#test")
            assert is_rate_limited is False
    
    @pytest.mark.asyncio
    async def test_channel_determination(self, mock_settings):
        """채널 결정 테스트"""
        with patch('app.services.slack_client.get_settings', return_value=mock_settings):
            from app.services.slack_client import SlackClientWrapper
            from app.models.slack_events import SlackNotificationRequest, SlackEventType, SlackChannelType
            
            client = SlackClientWrapper()
            await client._load_routing_config()
            
            # 명시적 채널 지정
            request = SlackNotificationRequest(
                event_type=SlackEventType.DEPLOYMENT_SUCCESS,
                title="Test",
                message="Test message",
                channel="#explicit"
            )
            channel = await client._determine_channel(request)
            assert channel == "#explicit"
            
            # 이벤트 타입별 매핑
            request = SlackNotificationRequest(
                event_type=SlackEventType.RATE_LIMITED,
                title="Test",
                message="Test message"
            )
            channel = await client._determine_channel(request)
            assert channel == "#errors"
            
            # 기본 채널
            request = SlackNotificationRequest(
                event_type=SlackEventType.DEPLOYMENT_STARTED,
                title="Test",
                message="Test message"
            )
            channel = await client._determine_channel(request)
            assert channel == "#general"


if __name__ == "__main__":
    pytest.main([__file__])
