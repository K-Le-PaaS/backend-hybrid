"""
Deployment Monitor WebSocket Manager

실시간 배포 진행률 모니터링을 위한 WebSocket 연결 관리자입니다.
특정 배포나 사용자별로 WebSocket 연결을 관리하고 실시간 업데이트를 전송합니다.
"""

import json
import asyncio
from typing import Dict, List, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from datetime import datetime, timezone
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

        # 배포별 최근 이벤트 저장: {deployment_id: [message, ...]}
        # 새로고침/재연결 시 스냅샷 재전송에 사용 (간단한 순차 복원)
        self.deployment_last_events: Dict[str, List[dict]] = {}
        # 이벤트 저장 상한 (메모리 보호)
        self.max_events_per_deployment: int = 200

        # 스테이지 시작 시각 저장: {deployment_id: {stage: datetime}}
        self.stage_started_at: Dict[str, Dict[str, datetime]] = {}
    
    async def initialize(self):
        """매니저 초기화"""
        self.is_initialized = True
        logger.info("DeploymentMonitorManager initialized")

    def _utcnow_iso(self) -> str:
        """UTC now in ISO8601 with timezone (e.g., +00:00) to avoid client TZ drift."""
        return datetime.now(timezone.utc).isoformat()
    
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
        
        # WebSocket connected (logging removed for verbosity)
    
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
        # WebSocket disconnected (logging removed for verbosity)
    
    async def handle_message(self, connection_id: str, data: dict):
        """기존 API와 호환성을 위한 메시지 처리 메서드"""
        message_type = data.get("type")
        # logger.info(f"Handling message type '{message_type}' for connection {connection_id}")
        
        if message_type == "ping":
            # ping/pong 처리 - pong 응답 전송
            try:
                # 해당 연결 ID의 웹소켓 찾기
                if connection_id in self.connections:
                    ws = self.connections[connection_id]
                    await ws.send_json({"type": "pong", "data": {"message": "pong"}})
                    # logger.info(f"Pong sent successfully to {connection_id}")
                else:
                    logger.warning(f"Connection {connection_id} not found in connections")
            except Exception as e:
                logger.error(f"Failed to send pong to {connection_id}: {e}")
        elif message_type == "subscribe":
            # 구독 처리
            subscriber_id = data.get("subscriber_id")
            deployment_id = data.get("deployment_id")
            user_id = data.get("user_id")
            
            # Subscribe message received (logging removed for verbosity)
            
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

                # 구독 직후 스냅샷 재전송 (해당 배포의 최근 이벤트들을 순서대로 전달)
                try:
                    if deployment_id and deployment_id in self.deployment_last_events:
                        snapshot_events = self.deployment_last_events[deployment_id]
                        logger.info(
                            f"Replaying {len(snapshot_events)} cached events to connection {connection_id} for deployment {deployment_id}"
                        )
                        for evt in snapshot_events:
                            try:
                                await websocket.send_json(evt)
                            except Exception as replay_err:
                                logger.warning(f"Failed to replay cached event: {replay_err}")
                                break
                except Exception as e:
                    logger.warning(f"Snapshot replay failed: {e}")
                
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
        
        # WebSocket connected for deployment (logging removed for verbosity)
        
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
        
        # WebSocket connected for user (logging removed for verbosity)
        
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
        
        # WebSocket disconnected for deployment (logging removed for verbosity)
    
    async def send_to_websocket(self, websocket: WebSocket, message: dict):
        """특정 WebSocket에 메시지 전송"""
        try:
            # WebSocket 연결 상태 확인
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"WebSocket not connected, skipping message: {message.get('type', 'unknown')}")
                return False
                
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
            # logger.info(f"Message sent to WebSocket: {message.get('type', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to WebSocket: {e}")
            await self.disconnect(websocket)
            return False
    
    async def broadcast_to_deployment(self, deployment_id: str, message: dict):
        """특정 배포의 모든 연결에 메시지 브로드캐스트"""
        if deployment_id not in self.deployment_connections:
            return
            
        connections = self.deployment_connections[deployment_id].copy()
        for websocket in connections:
            success = await self.send_to_websocket(websocket, message)
            if not success:
                # 연결이 끊어진 경우 연결 목록에서 제거
                if websocket in self.deployment_connections[deployment_id]:
                    self.deployment_connections[deployment_id].remove(websocket)
    
    async def broadcast_to_user(self, user_id: str, message: dict):
        """특정 사용자의 모든 연결에 메시지 브로드캐스트"""
        # logger.info(f"Broadcasting to user {user_id}")
        # logger.info(f"Available user connections: {list(self.user_connections.keys())}")
        
        if user_id not in self.user_connections:
            logger.warning(f"User {user_id} not found in user_connections")
            return
            
        connections = self.user_connections[user_id].copy()
        # logger.info(f"Found {len(connections)} connections for user {user_id}")
        
        for websocket in connections:
            success = await self.send_to_websocket(websocket, message)
            if not success:
                # 연결이 끊어진 경우 연결 목록에서 제거
                if websocket in self.user_connections[user_id]:
                    self.user_connections[user_id].remove(websocket)
    
    async def send_deployment_started(self, deployment_id: str, user_id: str, data: dict):
        """배포 시작 알림"""
        message = {
            "type": "deployment_started",
            "deployment_id": deployment_id,
            "timestamp": self._utcnow_iso(),
            "started_at": self._utcnow_iso(),
            "data": data
        }
        
        # Broadcasting deployment_started (logging removed for verbosity)

        self._record_deployment_event(deployment_id, message)
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_stage_started(self, deployment_id: str, user_id: str, stage: str, data: dict):
        """단계 시작 알림"""
        # 시작 시간 기록
        try:
            if deployment_id not in self.stage_started_at:
                self.stage_started_at[deployment_id] = {}
            self.stage_started_at[deployment_id][stage] = datetime.now(timezone.utc)
        except Exception:
            pass
        message = {
            "type": "stage_started",
            "deployment_id": deployment_id,
            "stage": stage,
            "timestamp": self._utcnow_iso(),
            "started_at": (self.stage_started_at.get(deployment_id, {}).get(stage) or datetime.now(timezone.utc)).isoformat(),
            "data": data
        }
        self._record_deployment_event(deployment_id, message)
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_stage_completed(self, deployment_id: str, user_id: str, stage: str, status: str, data: dict):
        """단계 완료 알림"""
        # duration이 없으면 서버에서 계산(UTC 기준)
        duration_val = None
        try:
            if isinstance(data, dict):
                duration_val = data.get("duration")
        except Exception:
            duration_val = None
        if duration_val in (None, 0):
            try:
                started_dt = self.stage_started_at.get(deployment_id, {}).get(stage)
                if started_dt:
                    duration_val = max(0, int((datetime.now(timezone.utc) - started_dt).total_seconds()))
            except Exception:
                duration_val = None
        message = {
            "type": "stage_completed",
            "deployment_id": deployment_id,
            "stage": stage,
            "status": status,  # success, failed
            "timestamp": self._utcnow_iso(),
            "completed_at": datetime.utcnow().isoformat(),
            "duration": duration_val,
            "data": data
        }
        self._record_deployment_event(deployment_id, message)
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_deployment_completed(self, deployment_id: str, user_id: str, status: str, data: dict):
        """배포 완료 알림"""
        message = {
            "type": "deployment_completed",
            "deployment_id": deployment_id,
            "status": status,  # success, failed
            "timestamp": self._utcnow_iso(),
            "completed_at": datetime.utcnow().isoformat(),
            "total_duration": data.get("total_duration") if isinstance(data, dict) else None,
            "data": data
        }
        self._record_deployment_event(deployment_id, message)
        await self.broadcast_to_deployment(deployment_id, message)
        await self.broadcast_to_user(user_id, message)
    
    async def send_stage_progress(self, deployment_id: str, user_id: str, stage: str, progress: int, elapsed_time: int, message: str = None):
        """단계별 실시간 진행률 전송"""
        # elapsed_time이 0/없으면 started_at 기준으로 계산해 채움
        started_dt = None
        try:
            started_dt = self.stage_started_at.get(deployment_id, {}).get(stage)
        except Exception:
            started_dt = None
        # 처음 progress가 들어오는 경우에도 시작시각이 없을 수 있으므로 여기서 초기화
        if started_dt is None:
            try:
                if deployment_id not in self.stage_started_at:
                    self.stage_started_at[deployment_id] = {}
                self.stage_started_at[deployment_id][stage] = datetime.now(timezone.utc)
                started_dt = self.stage_started_at[deployment_id][stage]
            except Exception:
                started_dt = None
        computed_elapsed = None
        if started_dt is not None:
            try:
                computed_elapsed = max(0, int((datetime.now(timezone.utc) - started_dt).total_seconds()))
            except Exception:
                computed_elapsed = None
        use_elapsed = elapsed_time if (isinstance(elapsed_time, int) and elapsed_time > 0) else (computed_elapsed or 0)
        websocket_message = {
            "type": "stage_progress",
            "deployment_id": deployment_id,
            "user_id": user_id,
            "stage": stage,
            "progress": progress,  # 0-100
            "elapsed_time": use_elapsed,  # 초 단위
            "message": message,
            "started_at": started_dt.isoformat() if started_dt else None,
            "timestamp": self._utcnow_iso()
        }
        
        # logger.info(f"Sending stage_progress: {stage} - {progress}% for deployment {deployment_id}")
        # logger.info(f"Stage progress message: {websocket_message}")
        self._record_deployment_event(deployment_id, websocket_message)
        await self.broadcast_to_deployment(deployment_id, websocket_message)
        await self.broadcast_to_user(user_id, websocket_message)

    def _record_deployment_event(self, deployment_id: str, message: dict) -> None:
        """배포별 최근 이벤트를 저장한다. 구독 시 스냅샷 재전송에 사용."""
        try:
            if not deployment_id:
                return
            if deployment_id not in self.deployment_last_events:
                self.deployment_last_events[deployment_id] = []
            events = self.deployment_last_events[deployment_id]

            # 같은 타입/스테이지의 진행 이벤트는 최신으로 교체하여 중복 축소 (특히 stage_progress)
            replaced = False
            if message.get("type") == "stage_progress":
                stage = message.get("stage")
                for i in range(len(events) - 1, -1, -1):
                    evt = events[i]
                    if evt.get("type") == "stage_progress" and evt.get("stage") == stage:
                        events[i] = message
                        replaced = True
                        break
            if not replaced:
                events.append(message)
            # 상한 관리
            if len(events) > self.max_events_per_deployment:
                self.deployment_last_events[deployment_id] = events[-self.max_events_per_deployment:]
        except Exception as e:
            logger.warning(f"Failed to record deployment event: {e}")
    
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