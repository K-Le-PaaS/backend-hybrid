"""
Deployment Monitor WebSocket Manager

실시간 배포 진행률 모니터링을 위한 WebSocket 연결 관리자입니다.
특정 배포나 사용자별로 WebSocket 연결을 관리하고 실시간 업데이트를 전송합니다.
"""

import json
import asyncio
from typing import Dict, List, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class DeploymentMonitorManager:
    """배포 모니터링 WebSocket 연결 관리자"""
    
    def __init__(self):
        # 배포별 연결 관리: {deployment_id: [websocket1, websocket2, ...]}
        self.deployment_connections: Dict[str, List[WebSocket]] = {}
        
        # 사용자별 연결 관리: {user_id: [websocket1, websocket2, ...]}
        self.user_connections: Dict[str, List[WebSocket]] = {}
        
        # WebSocket별 메타데이터: {websocket: {deployment_id, user_id, connected_at}}
        self.connection_metadata: Dict[WebSocket, Dict] = {}
        
        # 연결 ID별 WebSocket 관리: {connection_id: websocket}
        self.connections: Dict[str, WebSocket] = {}
        
        # 초기화 상태
        self.is_initialized = False
    
    async def initialize(self):
        """매니저 초기화"""
        self.is_initialized = True
        logger.info("DeploymentMonitorManager initialized")
    
    async def connect(self, websocket: WebSocket, connection_id: str, deployment_id: str = None, user_id: str = None):
        """기존 API와 호환성을 위한 연결 메서드"""
        await websocket.accept()
        self.connections[connection_id] = websocket
        
        # 메타데이터 저장
        self.connection_metadata[websocket] = {
            "connection_id": connection_id,
            "deployment_id": deployment_id,
            "user_id": user_id,
            "connected_at": datetime.utcnow()
        }
        
        # 배포별 연결 등록
        if deployment_id:
            if deployment_id not in self.deployment_connections:
                self.deployment_connections[deployment_id] = []
            self.deployment_connections[deployment_id].append(websocket)
        
        # 사용자별 연결 등록
        if user_id:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = []
            self.user_connections[user_id].append(websocket)
        
        logger.info(f"WebSocket connected: {connection_id}, deployment_id: {deployment_id}, user_id: {user_id}")
    
    async def disconnect(self, connection_id: str):
        """기존 API와 호환성을 위한 연결 해제 메서드"""
        if connection_id in self.connections:
            websocket = self.connections[connection_id]
            
            # 메타데이터에서 연결 정보 가져오기
            if websocket in self.connection_metadata:
                metadata = self.connection_metadata[websocket]
                deployment_id = metadata.get("deployment_id")
                user_id = metadata.get("user_id")
                
                # 배포별 연결에서 제거
                if deployment_id and deployment_id in self.deployment_connections:
                    if websocket in self.deployment_connections[deployment_id]:
                        self.deployment_connections[deployment_id].remove(websocket)
                    if not self.deployment_connections[deployment_id]:
                        del self.deployment_connections[deployment_id]
                
                # 사용자별 연결에서 제거
                if user_id and user_id in self.user_connections:
                    if websocket in self.user_connections[user_id]:
                        self.user_connections[user_id].remove(websocket)
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]
                
                # 메타데이터에서 제거
                del self.connection_metadata[websocket]
            
            del self.connections[connection_id]
        logger.info(f"WebSocket disconnected: {connection_id}")
    
    async def handle_message(self, connection_id: str, data: dict):
        """기존 API와 호환성을 위한 메시지 처리 메서드"""
        message_type = data.get("type")
        logger.info(f"Handling message type '{message_type}' for connection {connection_id}")
        
        if message_type == "ping":
            # ping/pong 처리 - pong 응답 전송
            try:
                logger.info(f"Processing ping from {connection_id}")
                # 해당 연결 ID의 웹소켓 찾기
                if connection_id in self.connections:
                    ws = self.connections[connection_id]
                    logger.info(f"Sending pong to {connection_id}")
                    await ws.send_json({"type": "pong", "data": {"message": "pong"}})
                    logger.info(f"Pong sent successfully to {connection_id}")
                else:
                    logger.warning(f"Connection {connection_id} not found in connections")
            except Exception as e:
                logger.error(f"Failed to send pong to {connection_id}: {e}")
        elif message_type == "subscribe":
            # 구독 처리
            subscriber_id = data.get("subscriber_id")
            deployment_id = data.get("deployment_id")
            user_id = data.get("user_id")
            
            if subscriber_id and connection_id in self.connections:
                websocket = self.connections[connection_id]
                
                # 메타데이터 업데이트
                if websocket in self.connection_metadata:
                    self.connection_metadata[websocket].update({
                        "deployment_id": deployment_id,
                        "user_id": user_id
                    })
                
                # 배포별 연결 등록
                if deployment_id:
                    if deployment_id not in self.deployment_connections:
                        self.deployment_connections[deployment_id] = []
                    if websocket not in self.deployment_connections[deployment_id]:
                        self.deployment_connections[deployment_id].append(websocket)
                
                # 사용자별 연결 등록
                if user_id:
                    if user_id not in self.user_connections:
                        self.user_connections[user_id] = []
                    if websocket not in self.user_connections[user_id]:
                        self.user_connections[user_id].append(websocket)
                
                logger.info(f"Subscriber {subscriber_id} registered for deployment {deployment_id}, user {user_id}")
                
        elif message_type == "unsubscribe":
            # 구독 해제 처리
            pass
    
    async def connect_deployment(self, websocket: WebSocket, deployment_id: str, user_id: str):
        """특정 배포의 WebSocket 연결"""
        await websocket.accept()
        
        # 연결 등록
        if deployment_id not in self.deployment_connections:
            self.deployment_connections[deployment_id] = []
        self.deployment_connections[deployment_id].append(websocket)
        
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)
        
        # 메타데이터 저장
        self.connection_metadata[websocket] = {
            "deployment_id": deployment_id,
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
            "connection_type": "deployment"
        }
        
        logger.info(f"WebSocket connected for deployment {deployment_id}, user {user_id}")
        
        # 연결 확인 메시지 전송
        await self.send_to_websocket(websocket, {
            "type": "connection_established",
            "deployment_id": deployment_id,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def connect_user(self, websocket: WebSocket, user_id: str):
        """사용자별 WebSocket 연결"""
        await websocket.accept()
        
        # 연결 등록
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)
        
        # 메타데이터 저장
        self.connection_metadata[websocket] = {
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
            "connection_type": "user"
        }
        
        logger.info(f"WebSocket connected for user {user_id}")
        
        # 연결 확인 메시지 전송
        await self.send_to_websocket(websocket, {
            "type": "connection_established",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def disconnect(self, websocket: WebSocket):
        """WebSocket 연결 해제"""
        if websocket not in self.connection_metadata:
            return
        
        metadata = self.connection_metadata[websocket]
        deployment_id = metadata.get("deployment_id")
        user_id = metadata.get("user_id")
        
        # 배포별 연결에서 제거
        if deployment_id and deployment_id in self.deployment_connections:
            if websocket in self.deployment_connections[deployment_id]:
                self.deployment_connections[deployment_id].remove(websocket)
            if not self.deployment_connections[deployment_id]:
                del self.deployment_connections[deployment_id]
        
        # 사용자별 연결에서 제거
        if user_id and user_id in self.user_connections:
            if websocket in self.user_connections[user_id]:
                self.user_connections[user_id].remove(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
        
        # 메타데이터 제거
        del self.connection_metadata[websocket]
        
        logger.info(f"WebSocket disconnected for deployment {deployment_id}, user {user_id}")
    
    async def send_to_websocket(self, websocket: WebSocket, message: dict):
        """특정 WebSocket에 메시지 전송"""
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to send message to WebSocket: {e}")
            await self.disconnect(websocket)
    
    async def broadcast_to_deployment(self, deployment_id: str, message: dict):
        """특정 배포의 모든 연결에 메시지 브로드캐스트"""
        if deployment_id not in self.deployment_connections:
                return
            
        connections = self.deployment_connections[deployment_id].copy()
        for websocket in connections:
            await self.send_to_websocket(websocket, message)
    
    async def broadcast_to_user(self, user_id: str, message: dict):
        """특정 사용자의 모든 연결에 메시지 브로드캐스트"""
        if user_id not in self.user_connections:
                return
            
        connections = self.user_connections[user_id].copy()
        for websocket in connections:
            await self.send_to_websocket(websocket, message)
    
    async def send_deployment_started(self, deployment_id: str, user_id: str, data: dict):
        """배포 시작 알림"""
        message = {
            "type": "deployment_started",
            "deployment_id": deployment_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_stage_started(self, deployment_id: str, user_id: str, stage: str, data: dict):
        """단계 시작 알림"""
        message = {
            "type": "stage_started",
            "deployment_id": deployment_id,
            "stage": stage,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_stage_completed(self, deployment_id: str, user_id: str, stage: str, status: str, data: dict):
        """단계 완료 알림"""
        message = {
            "type": "stage_completed",
            "deployment_id": deployment_id,
            "stage": stage,
            "status": status,  # success, failed
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_deployment_completed(self, deployment_id: str, user_id: str, status: str, data: dict):
        """배포 완료 알림"""
        message = {
            "type": "deployment_completed",
            "deployment_id": deployment_id,
            "status": status,  # success, failed
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    def get_connection_stats(self) -> dict:
        """연결 통계 반환"""
        return {
            "deployment_connections": len(self.deployment_connections),
            "user_connections": len(self.user_connections),
            "total_connections": len(self.connection_metadata),
            "deployment_connection_counts": {
                deployment_id: len(connections) 
                for deployment_id, connections in self.deployment_connections.items()
            },
            "user_connection_counts": {
                user_id: len(connections) 
                for user_id, connections in self.user_connections.items()
            }
        }


# 전역 인스턴스
deployment_monitor_manager = DeploymentMonitorManager()


def get_deployment_monitor_manager() -> DeploymentMonitorManager:
    """배포 모니터링 매니저 의존성 주입용 함수"""
    return deployment_monitor_manager


def init_deployment_monitor_manager():
    """배포 모니터링 매니저 초기화"""
    logger.info("Deployment monitor manager initialized")


# WebSocket 엔드포인트용 헬퍼 함수들
async def handle_deployment_websocket(websocket: WebSocket, deployment_id: str, user_id: str):
    """배포별 WebSocket 연결 처리"""
    await deployment_monitor_manager.connect_deployment(websocket, deployment_id, user_id)
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신 (ping/pong 등)
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # ping 메시지에 대한 pong 응답
            if message.get("type") == "ping":
                await deployment_monitor_manager.send_to_websocket(websocket, {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
    except WebSocketDisconnect:
        await deployment_monitor_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error for deployment {deployment_id}: {e}")
        await deployment_monitor_manager.disconnect(websocket)


async def handle_user_websocket(websocket: WebSocket, user_id: str):
    """사용자별 WebSocket 연결 처리"""
    await deployment_monitor_manager.connect_user(websocket, user_id)
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신 (ping/pong 등)
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # ping 메시지에 대한 pong 응답
            if message.get("type") == "ping":
                await deployment_monitor_manager.send_to_websocket(websocket, {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                })
                
    except WebSocketDisconnect:
        await deployment_monitor_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await deployment_monitor_manager.disconnect(websocket)