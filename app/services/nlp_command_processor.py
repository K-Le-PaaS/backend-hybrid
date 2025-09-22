"""
자연어 명령 처리 시스템
실시간 피드백과 명령 히스토리를 포함한 통합 자연어 명령 처리
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from enum import Enum

from ..llm.gemini import GeminiClient
from ..websocket.deployment_monitor import get_deployment_monitor_manager
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class CommandStatus(str, Enum):
    """명령 상태"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommandType(str, Enum):
    """명령 타입"""
    DEPLOY = "deploy"
    ROLLBACK = "rollback"
    SCALE = "scale"
    DELETE = "delete"
    STATUS = "status"
    MONITOR = "monitor"
    UNKNOWN = "unknown"


class NaturalLanguageCommandProcessor:
    """자연어 명령 처리기"""
    
    def __init__(self):
        self.gemini_client = GeminiClient()
        self.command_history: Dict[str, Dict[str, Any]] = {}
        self.active_commands: Dict[str, Dict[str, Any]] = {}
    
    async def process_command(
        self,
        user_id: str,
        command: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """자연어 명령을 처리합니다."""
        command_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        
        try:
            # 명령 기록 시작
            await self._record_command_start(command_id, user_id, command, context)
            
            # 실시간 피드백: 명령 수신
            await self._send_realtime_feedback(
                command_id, 
                "명령을 수신했습니다. 해석 중...",
                CommandStatus.PROCESSING
            )
            
            # 자연어 해석
            interpretation = await self.gemini_client.interpret(command)
            
            # 실시간 피드백: 해석 완료
            await self._send_realtime_feedback(
                command_id,
                f"명령을 해석했습니다: {interpretation.get('intent', 'unknown')}",
                CommandStatus.PROCESSING
            )
            
            # 명령 실행
            result = await self._execute_command(command_id, interpretation, context)
            
            # 명령 완료 기록
            await self._record_command_completion(command_id, result, True)
            
            # 실시간 피드백: 완료
            await self._send_realtime_feedback(
                command_id,
                "명령이 성공적으로 완료되었습니다.",
                CommandStatus.COMPLETED
            )
            
            return {
                "command_id": command_id,
                "status": CommandStatus.COMPLETED,
                "result": result,
                "processing_time": (datetime.now(timezone.utc) - start_time).total_seconds(),
                "interpretation": interpretation
            }
            
        except Exception as e:
            logger.error(f"Command processing failed: {e}", command_id=command_id)
            
            # 실시간 피드백: 실패
            await self._send_realtime_feedback(
                command_id,
                f"명령 처리 중 오류가 발생했습니다: {str(e)}",
                CommandStatus.FAILED
            )
            
            # 명령 실패 기록
            await self._record_command_completion(command_id, {"error": str(e)}, False)
            
            return {
                "command_id": command_id,
                "status": CommandStatus.FAILED,
                "error": str(e),
                "processing_time": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
    
    async def _record_command_start(
        self, 
        command_id: str, 
        user_id: str, 
        command: str, 
        context: Dict[str, Any]
    ):
        """명령 시작을 기록합니다."""
        self.active_commands[command_id] = {
            "command_id": command_id,
            "user_id": user_id,
            "command": command,
            "context": context or {},
            "status": CommandStatus.PENDING,
            "started_at": datetime.now(timezone.utc),
            "steps": []
        }
    
    async def _record_command_completion(
        self, 
        command_id: str, 
        result: Dict[str, Any], 
        success: bool
    ):
        """명령 완료를 기록합니다."""
        if command_id in self.active_commands:
            command_record = self.active_commands[command_id]
            command_record["status"] = CommandStatus.COMPLETED if success else CommandStatus.FAILED
            command_record["completed_at"] = datetime.now(timezone.utc)
            command_record["result"] = result
            command_record["success"] = success
            
            # 히스토리에 이동
            self.command_history[command_id] = command_record
            del self.active_commands[command_id]
    
    async def _send_realtime_feedback(
        self, 
        command_id: str, 
        message: str, 
        status: CommandStatus
    ):
        """실시간 피드백을 전송합니다."""
        try:
            # WebSocket을 통해 실시간 피드백 전송
            manager = get_deployment_monitor_manager()
            if manager and manager.is_initialized:
                feedback_data = {
                    "command_id": command_id,
                    "message": message,
                    "status": status.value,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # 모든 활성 연결에게 브로드캐스트
                await manager.broadcast_deployment_update("command_feedback", feedback_data)
            
            # 명령 기록에 단계 추가
            if command_id in self.active_commands:
                self.active_commands[command_id]["steps"].append({
                    "message": message,
                    "status": status.value,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
        except Exception as e:
            logger.error(f"Failed to send realtime feedback: {e}")
    
    async def _execute_command(
        self, 
        command_id: str, 
        interpretation: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """해석된 명령을 실행합니다."""
        intent = interpretation.get("intent", "unknown")
        entities = interpretation.get("entities", {})
        
        # 실시간 피드백: 실행 시작
        await self._send_realtime_feedback(
            command_id,
            f"{intent} 명령을 실행합니다...",
            CommandStatus.PROCESSING
        )
        
        if intent == "deploy":
            return await self._execute_deploy_command(command_id, entities, context)
        elif intent == "rollback":
            return await self._execute_rollback_command(command_id, entities, context)
        elif intent == "monitor":
            return await self._execute_monitor_command(command_id, entities, context)
        else:
            return {
                "message": f"지원하지 않는 명령입니다: {intent}",
                "supported_commands": ["deploy", "rollback", "monitor"]
            }
    
    async def _execute_deploy_command(
        self, 
        command_id: str, 
        entities: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """배포 명령을 실행합니다."""
        try:
            # 실시간 피드백: 배포 시작
            await self._send_realtime_feedback(
                command_id,
                f"애플리케이션 {entities.get('app_name', '알 수 없음')} 배포를 시작합니다...",
                CommandStatus.PROCESSING
            )
            
            # MCP 도구 호출 (실제 구현에서는 mcp_registry 사용)
            # result = await mcp_registry.call_tool("k-le-paas", "deploy_application", entities)
            
            # 시뮬레이션 (실제 구현에서는 실제 MCP 도구 호출)
            await asyncio.sleep(2)  # 배포 시뮬레이션
            
            result = {
                "action": "deploy",
                "app_name": entities.get("app_name", "myapp"),
                "environment": entities.get("environment", "staging"),
                "image": entities.get("image", "myapp:latest"),
                "replicas": entities.get("replicas", 2),
                "status": "deployed",
                "deployment_id": f"deploy-{command_id[:8]}"
            }
            
            # 실시간 피드백: 배포 완료
            await self._send_realtime_feedback(
                command_id,
                f"배포가 완료되었습니다. {result['replicas']}개 복제본이 {result['environment']} 환경에서 실행 중입니다.",
                CommandStatus.PROCESSING
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Deploy command execution failed: {e}")
            raise
    
    async def _execute_rollback_command(
        self, 
        command_id: str, 
        entities: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """롤백 명령을 실행합니다."""
        try:
            # 실시간 피드백: 롤백 시작
            await self._send_realtime_feedback(
                command_id,
                f"애플리케이션 {entities.get('app_name', '알 수 없음')} 롤백을 시작합니다...",
                CommandStatus.PROCESSING
            )
            
            # MCP 도구 호출 시뮬레이션
            await asyncio.sleep(1)  # 롤백 시뮬레이션
            
            result = {
                "action": "rollback",
                "app_name": entities.get("app_name", "myapp"),
                "environment": entities.get("environment", "staging"),
                "previous_version": "v1.0.0",
                "current_version": "v0.9.0",
                "status": "rolled_back"
            }
            
            # 실시간 피드백: 롤백 완료
            await self._send_realtime_feedback(
                command_id,
                f"롤백이 완료되었습니다. {result['app_name']}이 이전 버전으로 복원되었습니다.",
                CommandStatus.PROCESSING
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Rollback command execution failed: {e}")
            raise
    
    async def _execute_monitor_command(
        self, 
        command_id: str, 
        entities: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """모니터링 명령을 실행합니다."""
        try:
            # 실시간 피드백: 모니터링 시작
            await self._send_realtime_feedback(
                command_id,
                f"애플리케이션 {entities.get('app_name', '알 수 없음')} 상태를 확인합니다...",
                CommandStatus.PROCESSING
            )
            
            # MCP 도구 호출 시뮬레이션
            await asyncio.sleep(0.5)  # 모니터링 시뮬레이션
            
            result = {
                "action": "monitor",
                "app_name": entities.get("app_name", "myapp"),
                "status": "running",
                "replicas": 3,
                "ready_replicas": 3,
                "cpu_usage": "45%",
                "memory_usage": "67%",
                "uptime": "2d 14h 32m"
            }
            
            # 실시간 피드백: 모니터링 완료
            await self._send_realtime_feedback(
                command_id,
                f"모니터링 완료: {result['app_name']}이 정상적으로 실행 중입니다.",
                CommandStatus.PROCESSING
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Monitor command execution failed: {e}")
            raise
    
    async def get_command_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """사용자의 명령 히스토리를 조회합니다."""
        user_commands = [
            cmd for cmd in self.command_history.values()
            if cmd.get("user_id") == user_id
        ]
        
        # 최신 순으로 정렬
        user_commands.sort(key=lambda x: x.get("started_at", datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        
        return user_commands[:limit]
    
    async def get_active_commands(self, user_id: str) -> List[Dict[str, Any]]:
        """사용자의 활성 명령을 조회합니다."""
        return [
            cmd for cmd in self.active_commands.values()
            if cmd.get("user_id") == user_id
        ]
    
    async def cancel_command(self, command_id: str, user_id: str) -> bool:
        """명령을 취소합니다."""
        if command_id in self.active_commands:
            command = self.active_commands[command_id]
            if command.get("user_id") == user_id:
                command["status"] = CommandStatus.CANCELLED
                command["cancelled_at"] = datetime.now(timezone.utc)
                
                # 실시간 피드백: 취소
                await self._send_realtime_feedback(
                    command_id,
                    "명령이 취소되었습니다.",
                    CommandStatus.CANCELLED
                )
                
                # 히스토리로 이동
                self.command_history[command_id] = command
                del self.active_commands[command_id]
                
                return True
        
        return False


# 전역 인스턴스
_nlp_processor: Optional[NaturalLanguageCommandProcessor] = None


def get_nlp_processor() -> NaturalLanguageCommandProcessor:
    """자연어 명령 처리기 인스턴스를 반환합니다."""
    global _nlp_processor
    if _nlp_processor is None:
        _nlp_processor = NaturalLanguageCommandProcessor()
    return _nlp_processor


