"""
Alertmanager 및 Slack 연동을 통한 알림 시스템
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

import httpx
from pydantic import BaseModel

from ..core.config import get_settings

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """알림 심각도"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertStatus(Enum):
    """알림 상태"""
    FIRING = "firing"
    RESOLVED = "resolved"


class Alert(BaseModel):
    """알림 모델"""
    alertname: str
    status: AlertStatus
    severity: AlertSeverity
    component: str
    instance: str
    summary: str
    description: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    labels: Dict[str, str] = {}
    annotations: Dict[str, str] = {}


class AlertGroup(BaseModel):
    """알림 그룹 모델"""
    group_key: str
    status: AlertStatus
    group_labels: Dict[str, str] = {}
    common_labels: Dict[str, str] = {}
    common_annotations: Dict[str, str] = {}
    alerts: List[Alert] = []
    receiver: str = "default"
    external_url: Optional[str] = None


class AlertManagerWebhook(BaseModel):
    """Alertmanager 웹훅 페이로드"""
    version: str = "4"
    group_key: str
    status: AlertStatus
    group_labels: Dict[str, str] = {}
    common_labels: Dict[str, str] = {}
    common_annotations: Dict[str, str] = {}
    external_url: Optional[str] = None
    alerts: List[Alert] = []
    receiver: str = "default"
    repeat_interval: Optional[str] = None
    group_interval: Optional[str] = None


class SlackMessage(BaseModel):
    """Slack 메시지 모델"""
    text: str
    channel: Optional[str] = None
    username: Optional[str] = None
    icon_emoji: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None


class AlertingService:
    """알림 서비스 클래스"""
    
    def __init__(self):
        self.settings = get_settings()
        self.slack_webhook_url = self.settings.slack_webhook_url
        self.alertmanager_url = self.settings.alertmanager_url
        self.alertmanager_webhook_url = self.settings.alertmanager_webhook_url
        
    async def send_slack_alert(self, alert: Alert, channel: Optional[str] = None) -> bool:
        """Slack으로 알림 전송"""
        if not self.slack_webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False
            
        try:
            # 알림 템플릿 선택
            template = self._get_alert_template(alert.severity)
            
            # 메시지 생성
            message = self._format_slack_message(alert, template, channel)
            
            # Slack으로 전송
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.slack_webhook_url,
                    json=message.dict(exclude_none=True)
                )
                response.raise_for_status()
                
            logger.info(f"Slack alert sent successfully: {alert.alertname}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False
    
    async def send_alertmanager_webhook(self, webhook_data: AlertManagerWebhook) -> bool:
        """Alertmanager로 웹훅 전송"""
        if not self.alertmanager_webhook_url:
            logger.warning("Alertmanager webhook URL not configured")
            return False
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.alertmanager_webhook_url,
                    json=webhook_data.dict(exclude_none=True)
                )
                response.raise_for_status()
                
            logger.info(f"Alertmanager webhook sent successfully: {webhook_data.group_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Alertmanager webhook: {e}")
            return False
    
    def _get_alert_template(self, severity: AlertSeverity) -> str:
        """심각도에 따른 템플릿 선택"""
        templates = {
            AlertSeverity.INFO: self.settings.slack_alert_template_error or 
                "[MCP][INFO] {{component}}: {{summary}}",
            AlertSeverity.WARNING: self.settings.slack_alert_template_error or 
                "[MCP][WARNING] {{component}}: {{summary}}",
            AlertSeverity.CRITICAL: self.settings.slack_alert_template_health_down or 
                "[MCP][CRITICAL] {{component}}: {{summary}}",
            AlertSeverity.EMERGENCY: self.settings.slack_alert_template_health_down or 
                "[MCP][EMERGENCY] {{component}}: {{summary}}"
        }
        return templates.get(severity, templates[AlertSeverity.INFO])
    
    def _format_slack_message(self, alert: Alert, template: str, channel: Optional[str]) -> SlackMessage:
        """Slack 메시지 포맷팅"""
        # 템플릿 변수 치환
        text = template.format(
            component=alert.component,
            summary=alert.summary,
            description=alert.description,
            instance=alert.instance,
            status=alert.status.value,
            severity=alert.severity.value
        )
        
        # 색상 결정
        color_map = {
            AlertSeverity.INFO: "good",
            AlertSeverity.WARNING: "warning", 
            AlertSeverity.CRITICAL: "danger",
            AlertSeverity.EMERGENCY: "danger"
        }
        color = color_map.get(alert.severity, "good")
        
        # 첨부파일 생성
        attachments = [{
            "color": color,
            "title": f"{alert.alertname} - {alert.component}",
            "text": alert.description,
            "fields": [
                {
                    "title": "Status",
                    "value": alert.status.value.upper(),
                    "short": True
                },
                {
                    "title": "Severity", 
                    "value": alert.severity.value.upper(),
                    "short": True
                },
                {
                    "title": "Instance",
                    "value": alert.instance,
                    "short": True
                },
                {
                    "title": "Started At",
                    "value": alert.starts_at.isoformat(),
                    "short": True
                }
            ],
            "footer": "K-Le-PaaS Monitoring",
            "ts": int(alert.starts_at.timestamp())
        }]
        
        # 라벨이 있으면 추가
        if alert.labels:
            labels_text = "\n".join([f"• {k}: {v}" for k, v in alert.labels.items()])
            attachments[0]["fields"].append({
                "title": "Labels",
                "value": labels_text,
                "short": False
            })
        
        return SlackMessage(
            text=text,
            channel=channel or self.settings.slack_alert_channel_default,
            username="K-Le-PaaS Monitor",
            icon_emoji=":warning:",
            attachments=attachments
        )
    
    async def create_health_alert(
        self, 
        component: str, 
        instance: str, 
        status: AlertStatus,
        message: str
    ) -> Alert:
        """헬스체크 알림 생성"""
        severity = AlertSeverity.CRITICAL if status == AlertStatus.FIRING else AlertSeverity.INFO
        
        return Alert(
            alertname="ComponentHealthCheck",
            status=status,
            severity=severity,
            component=component,
            instance=instance,
            summary=f"Component {component} is {status.value}",
            description=message,
            starts_at=datetime.now(timezone.utc),
            labels={
                "component": component,
                "instance": instance,
                "service": "k-le-paas"
            },
            annotations={
                "summary": f"Component {component} health check",
                "description": message
            }
        )
    
    async def create_circuit_breaker_alert(
        self,
        component: str,
        state: str,
        message: str
    ) -> Alert:
        """Circuit Breaker 알림 생성"""
        status = AlertStatus.FIRING if state == "OPEN" else AlertStatus.RESOLVED
        severity = AlertSeverity.CRITICAL if state == "OPEN" else AlertSeverity.INFO
        
        return Alert(
            alertname="CircuitBreakerStateChange",
            status=status,
            severity=severity,
            component=component,
            instance="circuit-breaker",
            summary=f"Circuit breaker for {component} is {state}",
            description=message,
            starts_at=datetime.now(timezone.utc),
            labels={
                "component": component,
                "state": state,
                "service": "k-le-paas"
            },
            annotations={
                "summary": f"Circuit breaker state change for {component}",
                "description": message
            }
        )


# 전역 알림 서비스 인스턴스
alerting_service = AlertingService()


async def send_health_alert(component: str, instance: str, is_healthy: bool, message: str) -> bool:
    """헬스체크 알림 전송 헬퍼 함수"""
    status = AlertStatus.RESOLVED if is_healthy else AlertStatus.FIRING
    alert = await alerting_service.create_health_alert(component, instance, status, message)
    
    # Slack 알림 전송
    slack_success = await alerting_service.send_slack_alert(alert)
    
    # Alertmanager 웹훅 전송 (선택적)
    if alerting_service.alertmanager_webhook_url:
        webhook_data = AlertManagerWebhook(
            group_key=f"health_{component}",
            status=status,
            group_labels={"component": component},
            common_labels={"service": "k-le-paas"},
            common_annotations={"summary": f"Health check for {component}"},
            alerts=[alert]
        )
        await alerting_service.send_alertmanager_webhook(webhook_data)
    
    return slack_success


async def send_circuit_breaker_alert(component: str, state: str, message: str) -> bool:
    """Circuit Breaker 알림 전송 헬퍼 함수"""
    alert = await alerting_service.create_circuit_breaker_alert(component, state, message)
    
    # Slack 알림 전송
    slack_success = await alerting_service.send_slack_alert(alert)
    
    # Alertmanager 웹훅 전송 (선택적)
    if alerting_service.alertmanager_webhook_url:
        webhook_data = AlertManagerWebhook(
            group_key=f"circuit_breaker_{component}",
            status=alert.status,
            group_labels={"component": component, "state": state},
            common_labels={"service": "k-le-paas"},
            common_annotations={"summary": f"Circuit breaker state change for {component}"},
            alerts=[alert]
        )
        await alerting_service.send_alertmanager_webhook(webhook_data)
    
    return slack_success
