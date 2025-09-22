"""
배포 모니터링 WebSocket 서비스

실시간 배포 상태를 클라이언트에게 전송하는 WebSocket 서비스입니다.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Set, Optional
from enum import Enum

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from ..services.kubernetes_watcher import KubernetesWatcher, get_kubernetes_watcher
from ..services.deployment_history import DeploymentHistoryService, get_deployment_history_service

logger = structlog.get_logger(__name__)


class WebSocketMessageType(str, Enum):
    """WebSocket 메시지 타입"""
    DEPLOYMENT_STATUS = "deployment_status"
    DEPLOYMENT_PROGRESS = "deployment_progress"
    DEPLOYMENT_COMPLETE = "deployment_complete"
    DEPLOYMENT_FAILED = "deployment_failed"
    ROLLBACK_STATUS = "rollback_status"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


class WebSocketMessage:
    """WebSocket 메시지 클래스"""
    
    def __init__(
        self,
        message_type: WebSocketMessageType,
        data: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ):
        self.type = message_type
        self.data = data
        self.timestamp = timestamp or datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class DeploymentMonitorManager:
    """배포 모니터링 매니저"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_subscriptions: Dict[str, Set[str]] = {}  # connection_id -> set of app_names
        self.app_subscriptions: Dict[str, Set[str]] = {}  # app_name -> set of connection_ids
        self.kubernetes_watcher: Optional[KubernetesWatcher] = None
        self.deployment_history_service: Optional[DeploymentHistoryService] = None
        self.is_initialized = False

    async def initialize(self):
        """서비스를 초기화합니다."""
        try:
            self.kubernetes_watcher = get_kubernetes_watcher()
            self.deployment_history_service = get_deployment_history_service()
            
            # Kubernetes Watch 이벤트 핸들러 등록
            self.kubernetes_watcher.add_event_handler(
                'deployment',
                self._handle_deployment_event
            )
            
            self.is_initialized = True
            logger.info("deployment_monitor_manager_initialized")
            
        except Exception as e:
            logger.error("deployment_monitor_manager_initialization_failed", error=str(e))
            raise

    async def connect(self, websocket: WebSocket, connection_id: str):
        """WebSocket 연결을 수락합니다."""
        try:
            await websocket.accept()
            self.active_connections[connection_id] = websocket
            self.connection_subscriptions[connection_id] = set()
            
            # 연결 확인 메시지 전송
            welcome_message = WebSocketMessage(
                WebSocketMessageType.DEPLOYMENT_STATUS,
                {
                    "message": "Connected to deployment monitor",
                    "connection_id": connection_id,
                    "available_commands": ["subscribe", "unsubscribe", "ping"]
                }
            )
            await self._send_to_connection(connection_id, welcome_message)
            
            logger.info("websocket_connected", connection_id=connection_id)
            
        except Exception as e:
            logger.error("websocket_connection_failed", error=str(e), connection_id=connection_id)
            raise

    async def disconnect(self, connection_id: str):
        """WebSocket 연결을 종료합니다."""
        try:
            if connection_id in self.active_connections:
                # 구독 해제
                if connection_id in self.connection_subscriptions:
                    for app_name in self.connection_subscriptions[connection_id]:
                        await self._unsubscribe_from_app(connection_id, app_name)
                
                # 연결 제거
                del self.active_connections[connection_id]
                if connection_id in self.connection_subscriptions:
                    del self.connection_subscriptions[connection_id]
                
                logger.info("websocket_disconnected", connection_id=connection_id)
            
        except Exception as e:
            logger.error("websocket_disconnect_failed", error=str(e), connection_id=connection_id)

    async def handle_message(self, connection_id: str, message: Dict[str, Any]):
        """WebSocket 메시지를 처리합니다."""
        try:
            message_type = message.get("type")
            data = message.get("data", {})
            
            if message_type == "subscribe":
                app_name = data.get("app_name")
                environment = data.get("environment", "staging")
                if app_name:
                    await self._subscribe_to_app(connection_id, app_name, environment)
            
            elif message_type == "unsubscribe":
                app_name = data.get("app_name")
                if app_name:
                    await self._unsubscribe_from_app(connection_id, app_name)
            
            elif message_type == "ping":
                pong_message = WebSocketMessage(WebSocketMessageType.PONG, {"timestamp": datetime.now(timezone.utc).isoformat()})
                await self._send_to_connection(connection_id, pong_message)
            
            else:
                error_message = WebSocketMessage(
                    WebSocketMessageType.ERROR,
                    {"error": f"Unknown message type: {message_type}"}
                )
                await self._send_to_connection(connection_id, error_message)
                
        except Exception as e:
            logger.error("websocket_message_handling_failed", error=str(e), connection_id=connection_id)
            error_message = WebSocketMessage(
                WebSocketMessageType.ERROR,
                {"error": f"Message processing failed: {str(e)}"}
            )
            await self._send_to_connection(connection_id, error_message)

    async def _subscribe_to_app(self, connection_id: str, app_name: str, environment: str):
        """앱 배포 상태 구독을 시작합니다."""
        try:
            # 구독 정보 업데이트
            self.connection_subscriptions[connection_id].add(app_name)
            
            if app_name not in self.app_subscriptions:
                self.app_subscriptions[app_name] = set()
            self.app_subscriptions[app_name].add(connection_id)
            
            # 현재 배포 상태 전송
            await self._send_current_deployment_status(connection_id, app_name, environment)
            
            # 구독 확인 메시지
            subscribe_message = WebSocketMessage(
                WebSocketMessageType.DEPLOYMENT_STATUS,
                {
                    "message": f"Subscribed to {app_name} deployments",
                    "app_name": app_name,
                    "environment": environment
                }
            )
            await self._send_to_connection(connection_id, subscribe_message)
            
            logger.info(
                "app_subscription_created",
                connection_id=connection_id,
                app_name=app_name,
                environment=environment
            )
            
        except Exception as e:
            logger.error(
                "app_subscription_failed",
                error=str(e),
                connection_id=connection_id,
                app_name=app_name
            )

    async def _unsubscribe_from_app(self, connection_id: str, app_name: str):
        """앱 배포 상태 구독을 해제합니다."""
        try:
            # 구독 정보 업데이트
            if connection_id in self.connection_subscriptions:
                self.connection_subscriptions[connection_id].discard(app_name)
            
            if app_name in self.app_subscriptions:
                self.app_subscriptions[app_name].discard(connection_id)
                if not self.app_subscriptions[app_name]:
                    del self.app_subscriptions[app_name]
            
            # 구독 해제 확인 메시지
            unsubscribe_message = WebSocketMessage(
                WebSocketMessageType.DEPLOYMENT_STATUS,
                {
                    "message": f"Unsubscribed from {app_name} deployments",
                    "app_name": app_name
                }
            )
            await self._send_to_connection(connection_id, unsubscribe_message)
            
            logger.info(
                "app_subscription_removed",
                connection_id=connection_id,
                app_name=app_name
            )
            
        except Exception as e:
            logger.error(
                "app_unsubscription_failed",
                error=str(e),
                connection_id=connection_id,
                app_name=app_name
            )

    async def _send_current_deployment_status(self, connection_id: str, app_name: str, environment: str):
        """현재 배포 상태를 전송합니다."""
        try:
            if not self.deployment_history_service:
                return
            
            # 최근 배포 정보 조회
            recent_versions = await self.deployment_history_service.get_recent_versions(
                app_name=app_name,
                environment=environment,
                limit=1
            )
            
            if recent_versions:
                latest_deployment = recent_versions[0]
                
                status_message = WebSocketMessage(
                    WebSocketMessageType.DEPLOYMENT_STATUS,
                    {
                        "app_name": app_name,
                        "environment": environment,
                        "deployment_id": latest_deployment.id,
                        "image": latest_deployment.image,
                        "image_tag": latest_deployment.image_tag,
                        "status": latest_deployment.status,
                        "progress": latest_deployment.progress,
                        "replicas": latest_deployment.replicas,
                        "deployed_at": latest_deployment.deployed_at.isoformat() if latest_deployment.deployed_at else None,
                        "is_rollback": latest_deployment.is_rollback
                    }
                )
                await self._send_to_connection(connection_id, status_message)
            
        except Exception as e:
            logger.error(
                "current_deployment_status_send_failed",
                error=str(e),
                connection_id=connection_id,
                app_name=app_name
            )

    async def _handle_deployment_event(self, event_data: Dict[str, Any]):
        """Kubernetes 배포 이벤트를 처리합니다."""
        try:
            app_name = event_data.get('name')
            if not app_name or app_name not in self.app_subscriptions:
                return
            
            # 구독 중인 연결들에게 이벤트 전송
            for connection_id in self.app_subscriptions[app_name]:
                await self._send_deployment_event_to_connection(connection_id, event_data)
            
        except Exception as e:
            logger.error("deployment_event_handling_failed", error=str(e), event_data=event_data)

    async def _send_deployment_event_to_connection(self, connection_id: str, event_data: Dict[str, Any]):
        """특정 연결에게 배포 이벤트를 전송합니다."""
        try:
            app_name = event_data.get('name')
            event_type = event_data.get('event_type')
            progress = event_data.get('progress', 0)
            phase = event_data.get('phase', 'Unknown')
            
            # 이벤트 타입에 따른 메시지 생성
            if phase == 'Complete':
                message_type = WebSocketMessageType.DEPLOYMENT_COMPLETE
            elif phase == 'Failed':
                message_type = WebSocketMessageType.DEPLOYMENT_FAILED
            else:
                message_type = WebSocketMessageType.DEPLOYMENT_PROGRESS
            
            message = WebSocketMessage(
                message_type,
                {
                    "app_name": app_name,
                    "event_type": event_type,
                    "progress": progress,
                    "phase": phase,
                    "desired_replicas": event_data.get('desired_replicas', 0),
                    "ready_replicas": event_data.get('ready_replicas', 0),
                    "available_replicas": event_data.get('available_replicas', 0),
                    "pod_info": event_data.get('pod_info', {}),
                    "image": event_data.get('image'),
                    "timestamp": event_data.get('timestamp')
                }
            )
            
            await self._send_to_connection(connection_id, message)
            
        except Exception as e:
            logger.error(
                "deployment_event_send_failed",
                error=str(e),
                connection_id=connection_id,
                event_data=event_data
            )

    async def _send_to_connection(self, connection_id: str, message: WebSocketMessage):
        """특정 연결에게 메시지를 전송합니다."""
        try:
            if connection_id in self.active_connections:
                websocket = self.active_connections[connection_id]
                
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(message.to_json())
                else:
                    # 연결이 끊어진 경우 정리
                    await self.disconnect(connection_id)
            
        except WebSocketDisconnect:
            await self.disconnect(connection_id)
        except Exception as e:
            logger.error(
                "websocket_send_failed",
                error=str(e),
                connection_id=connection_id
            )

    async def broadcast_deployment_update(self, app_name: str, update_data: Dict[str, Any]):
        """특정 앱의 모든 구독자에게 업데이트를 브로드캐스트합니다."""
        try:
            if app_name not in self.app_subscriptions:
                return
            
            message = WebSocketMessage(
                WebSocketMessageType.DEPLOYMENT_STATUS,
                {
                    "app_name": app_name,
                    **update_data
                }
            )
            
            for connection_id in self.app_subscriptions[app_name]:
                await self._send_to_connection(connection_id, message)
            
        except Exception as e:
            logger.error(
                "deployment_broadcast_failed",
                error=str(e),
                app_name=app_name
            )

    def get_connection_stats(self) -> Dict[str, Any]:
        """연결 통계를 반환합니다."""
        return {
            "active_connections": len(self.active_connections),
            "total_subscriptions": sum(len(subs) for subs in self.connection_subscriptions.values()),
            "app_subscriptions": {
                app_name: len(connection_ids)
                for app_name, connection_ids in self.app_subscriptions.items()
            }
        }


# 전역 매니저 인스턴스
deployment_monitor_manager: Optional[DeploymentMonitorManager] = None


def get_deployment_monitor_manager() -> DeploymentMonitorManager:
    """배포 모니터링 매니저 인스턴스를 반환합니다."""
    if deployment_monitor_manager is None:
        raise RuntimeError("DeploymentMonitorManager not initialized")
    return deployment_monitor_manager


def init_deployment_monitor_manager() -> None:
    """배포 모니터링 매니저를 초기화합니다."""
    global deployment_monitor_manager
    deployment_monitor_manager = DeploymentMonitorManager()
