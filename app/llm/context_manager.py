#!/usr/bin/env python3
"""
컨텍스트 인식 대화 시스템
대화 히스토리, 프로젝트 상태, 사용자 패턴을 추적하여 지능적인 대화 제공
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import redis.asyncio as redis
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

@dataclass
class ConversationTurn:
    """대화 턴 데이터"""
    user_id: str
    timestamp: datetime
    user_input: str
    system_response: str
    context_snapshot: Dict[str, Any]
    model_used: str
    confidence: float
    action_taken: Optional[str] = None
    success: Optional[bool] = None

@dataclass
class ProjectContext:
    """프로젝트 컨텍스트 데이터"""
    project_name: str
    current_deployments: List[Dict[str, Any]]
    recent_actions: List[Dict[str, Any]]
    user_preferences: Dict[str, Any]
    last_updated: datetime

@dataclass
class UserPattern:
    """사용자 패턴 데이터"""
    user_id: str
    common_commands: List[str]
    preferred_actions: Dict[str, int]
    typical_parameters: Dict[str, Any]
    error_patterns: List[str]
    success_patterns: List[str]

class ContextManager:
    """컨텍스트 관리자"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.context_ttl = 3600  # 1시간
        self.conversation_ttl = 86400  # 24시간
        self.pattern_ttl = 604800  # 7일
    
    async def initialize(self):
        """Redis 클라이언트 초기화"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Context manager initialized with Redis")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            # Redis가 없는 경우 메모리 저장소 사용
            self.redis_client = None
            self._memory_store = {}
            logger.info("Using in-memory storage for context")
    
    async def save_conversation_turn(self, turn: ConversationTurn):
        """대화 턴 저장"""
        try:
            key = f"conversation:{turn.user_id}:{turn.timestamp.isoformat()}"
            data = {
                "user_id": turn.user_id,
                "timestamp": turn.timestamp.isoformat(),
                "user_input": turn.user_input,
                "system_response": turn.system_response,
                "context_snapshot": turn.context_snapshot,
                "model_used": turn.model_used,
                "confidence": turn.confidence,
                "action_taken": turn.action_taken,
                "success": turn.success
            }
            
            if self.redis_client:
                await self.redis_client.setex(
                    key, 
                    self.conversation_ttl, 
                    json.dumps(data)
                )
            else:
                self._memory_store[key] = data
            
            logger.debug(f"Saved conversation turn for user {turn.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to save conversation turn: {e}")
    
    async def get_recent_conversations(self, user_id: str, limit: int = 5) -> List[ConversationTurn]:
        """최근 대화 히스토리 조회"""
        try:
            pattern = f"conversation:{user_id}:*"
            
            if self.redis_client:
                keys = await self.redis_client.keys(pattern)
                keys.sort(reverse=True)  # 최신순 정렬
                keys = keys[:limit]
                
                conversations = []
                for key in keys:
                    data = await self.redis_client.get(key)
                    if data:
                        conv_data = json.loads(data)
                        conversations.append(ConversationTurn(
                            user_id=conv_data["user_id"],
                            timestamp=datetime.fromisoformat(conv_data["timestamp"]),
                            user_input=conv_data["user_input"],
                            system_response=conv_data["system_response"],
                            context_snapshot=conv_data["context_snapshot"],
                            model_used=conv_data["model_used"],
                            confidence=conv_data["confidence"],
                            action_taken=conv_data.get("action_taken"),
                            success=conv_data.get("success")
                        ))
                
                return conversations
            else:
                # 메모리 저장소에서 조회
                conversations = []
                for key, data in self._memory_store.items():
                    if key.startswith(f"conversation:{user_id}:"):
                        conversations.append(ConversationTurn(
                            user_id=data["user_id"],
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            user_input=data["user_input"],
                            system_response=data["system_response"],
                            context_snapshot=data["context_snapshot"],
                            model_used=data["model_used"],
                            confidence=data["confidence"],
                            action_taken=data.get("action_taken"),
                            success=data.get("success")
                        ))
                
                # 최신순 정렬 및 제한
                conversations.sort(key=lambda x: x.timestamp, reverse=True)
                return conversations[:limit]
                
        except Exception as e:
            logger.error(f"Failed to get recent conversations: {e}")
            return []
    
    async def save_project_context(self, context: ProjectContext):
        """프로젝트 컨텍스트 저장"""
        try:
            key = f"project_context:{context.project_name}"
            data = {
                "project_name": context.project_name,
                "current_deployments": context.current_deployments,
                "recent_actions": context.recent_actions,
                "user_preferences": context.user_preferences,
                "last_updated": context.last_updated.isoformat()
            }
            
            if self.redis_client:
                await self.redis_client.setex(
                    key,
                    self.context_ttl,
                    json.dumps(data)
                )
            else:
                self._memory_store[key] = data
            
            logger.debug(f"Saved project context for {context.project_name}")
            
        except Exception as e:
            logger.error(f"Failed to save project context: {e}")
    
    async def get_project_context(self, project_name: str) -> Optional[ProjectContext]:
        """프로젝트 컨텍스트 조회"""
        try:
            key = f"project_context:{project_name}"
            
            if self.redis_client:
                data = await self.redis_client.get(key)
                if data:
                    context_data = json.loads(data)
                    return ProjectContext(
                        project_name=context_data["project_name"],
                        current_deployments=context_data["current_deployments"],
                        recent_actions=context_data["recent_actions"],
                        user_preferences=context_data["user_preferences"],
                        last_updated=datetime.fromisoformat(context_data["last_updated"])
                    )
            else:
                data = self._memory_store.get(key)
                if data:
                    return ProjectContext(
                        project_name=data["project_name"],
                        current_deployments=data["current_deployments"],
                        recent_actions=data["recent_actions"],
                        user_preferences=data["user_preferences"],
                        last_updated=datetime.fromisoformat(data["last_updated"])
                    )
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get project context: {e}")
            return None
    
    async def update_user_pattern(self, user_id: str, command: str, success: bool, action: str = None):
        """사용자 패턴 업데이트"""
        try:
            pattern_key = f"user_pattern:{user_id}"
            
            # 기존 패턴 조회
            pattern_data = await self._get_user_pattern(user_id)
            if not pattern_data:
                pattern_data = {
                    "user_id": user_id,
                    "common_commands": [],
                    "preferred_actions": {},
                    "typical_parameters": {},
                    "error_patterns": [],
                    "success_patterns": []
                }
            
            # 명령어 추가
            if command not in pattern_data["common_commands"]:
                pattern_data["common_commands"].append(command)
                # 최대 20개 유지
                pattern_data["common_commands"] = pattern_data["common_commands"][-20:]
            
            # 액션 선호도 업데이트
            if action:
                pattern_data["preferred_actions"][action] = pattern_data["preferred_actions"].get(action, 0) + 1
            
            # 성공/실패 패턴 업데이트
            if success:
                if command not in pattern_data["success_patterns"]:
                    pattern_data["success_patterns"].append(command)
                    pattern_data["success_patterns"] = pattern_data["success_patterns"][-10:]
            else:
                if command not in pattern_data["error_patterns"]:
                    pattern_data["error_patterns"].append(command)
                    pattern_data["error_patterns"] = pattern_data["error_patterns"][-10:]
            
            # 저장
            if self.redis_client:
                await self.redis_client.setex(
                    pattern_key,
                    self.pattern_ttl,
                    json.dumps(pattern_data)
                )
            else:
                self._memory_store[pattern_key] = pattern_data
            
            logger.debug(f"Updated user pattern for {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to update user pattern: {e}")
    
    async def _get_user_pattern(self, user_id: str) -> Optional[Dict[str, Any]]:
        """사용자 패턴 조회"""
        try:
            pattern_key = f"user_pattern:{user_id}"
            
            if self.redis_client:
                data = await self.redis_client.get(pattern_key)
                return json.loads(data) if data else None
            else:
                return self._memory_store.get(pattern_key)
                
        except Exception as e:
            logger.error(f"Failed to get user pattern: {e}")
            return None
    
    async def get_user_pattern(self, user_id: str) -> Optional[UserPattern]:
        """사용자 패턴 조회 (구조화된 형태)"""
        try:
            pattern_data = await self._get_user_pattern(user_id)
            if not pattern_data:
                return None
            
            return UserPattern(
                user_id=pattern_data["user_id"],
                common_commands=pattern_data["common_commands"],
                preferred_actions=pattern_data["preferred_actions"],
                typical_parameters=pattern_data["typical_parameters"],
                error_patterns=pattern_data["error_patterns"],
                success_patterns=pattern_data["success_patterns"]
            )
            
        except Exception as e:
            logger.error(f"Failed to get user pattern: {e}")
            return None
    
    async def build_context_for_command(self, user_id: str, project_name: str) -> Dict[str, Any]:
        """명령 처리용 컨텍스트 구성"""
        try:
            context = {
                "user_id": user_id,
                "project_name": project_name,
                "timestamp": datetime.now().isoformat()
            }
            
            # 최근 대화 히스토리
            recent_conversations = await self.get_recent_conversations(user_id, 3)
            context["recent_conversations"] = [
                {
                    "user_input": conv.user_input,
                    "system_response": conv.system_response,
                    "action_taken": conv.action_taken,
                    "success": conv.success
                }
                for conv in recent_conversations
            ]
            
            # 프로젝트 컨텍스트
            project_context = await self.get_project_context(project_name)
            if project_context:
                context.update({
                    "current_deployments": project_context.current_deployments,
                    "recent_actions": project_context.recent_actions,
                    "user_preferences": project_context.user_preferences
                })
            
            # 사용자 패턴
            user_pattern = await self.get_user_pattern(user_id)
            if user_pattern:
                context.update({
                    "common_commands": user_pattern.common_commands,
                    "preferred_actions": user_pattern.preferred_actions,
                    "error_patterns": user_pattern.error_patterns,
                    "success_patterns": user_pattern.success_patterns
                })
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to build context: {e}")
            return {"user_id": user_id, "project_name": project_name}
    
    async def close(self):
        """리소스 정리"""
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Context manager closed")

class ContextAwareProcessor:
    """컨텍스트 인식 프로세서"""
    
    def __init__(self, context_manager: ContextManager, multi_model_processor):
        self.context_manager = context_manager
        self.multi_model_processor = multi_model_processor
    
    async def process_with_context(self, user_id: str, project_name: str, command: str) -> Dict[str, Any]:
        """컨텍스트를 고려한 명령 처리"""
        try:
            # 컨텍스트 구성
            context = await self.context_manager.build_context_for_command(user_id, project_name)
            
            # 명령 처리
            result = await self.multi_model_processor.process_command(command, context)
            
            # 대화 턴 저장
            conversation_turn = ConversationTurn(
                user_id=user_id,
                timestamp=datetime.now(),
                user_input=command,
                system_response=result.best_response.content,
                context_snapshot=context,
                model_used=result.best_response.model_type.value,
                confidence=result.confidence
            )
            await self.context_manager.save_conversation_turn(conversation_turn)
            
            # 사용자 패턴 업데이트 (성공 여부는 나중에 업데이트)
            await self.context_manager.update_user_pattern(user_id, command, True)
            
            return {
                "processed_command": result,
                "context": context,
                "conversation_turn": conversation_turn
            }
            
        except Exception as e:
            logger.error(f"Context-aware processing failed: {e}")
            raise
    
    async def update_action_result(self, user_id: str, command: str, action: str, success: bool):
        """액션 결과 업데이트"""
        try:
            await self.context_manager.update_user_pattern(user_id, command, success, action)
            logger.debug(f"Updated action result for user {user_id}: {action} - {success}")
        except Exception as e:
            logger.error(f"Failed to update action result: {e}")

# 사용 예시
async def main():
    context_manager = ContextManager()
    await context_manager.initialize()
    
    # 컨텍스트 인식 프로세서 생성
    from .multi_model_processor import MultiModelProcessor, DEFAULT_CONFIG
    multi_processor = MultiModelProcessor(DEFAULT_CONFIG)
    processor = ContextAwareProcessor(context_manager, multi_processor)
    
    try:
        # 명령 처리
        result = await processor.process_with_context(
            user_id="user123",
            project_name="my-project",
            command="앱을 배포해줘"
        )
        
        print(f"Processed: {result['processed_command'].interpreted_command}")
        print(f"Context: {result['context']}")
        
    finally:
        await context_manager.close()
        await multi_processor.close()

if __name__ == "__main__":
    asyncio.run(main())
