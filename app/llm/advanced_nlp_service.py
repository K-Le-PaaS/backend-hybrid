#!/usr/bin/env python3
"""
고급 자연어 처리 서비스
다중 AI 모델, 컨텍스트 인식, 지능적 해석, 학습 기반 개선을 통합한 서비스
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from .multi_model_processor import MultiModelProcessor, DEFAULT_CONFIG
from .context_manager import ContextManager, ContextAwareProcessor
from .smart_command_interpreter import SmartCommandInterpreter
from .learning_processor import LearningProcessor, LearningFeedback

logger = logging.getLogger(__name__)

class AdvancedNLPService:
    """고급 자연어 처리 서비스"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or DEFAULT_CONFIG
        
        # 컴포넌트 초기화
        self.multi_model_processor = MultiModelProcessor(self.config)
        self.context_manager = ContextManager()
        self.smart_interpreter = SmartCommandInterpreter()
        self.learning_processor = LearningProcessor()
        
        # 통합 프로세서
        self.context_aware_processor = ContextAwareProcessor(
            self.context_manager, 
            self.multi_model_processor
        )
        
        self.initialized = False
    
    async def initialize(self):
        """서비스 초기화"""
        try:
            await self.context_manager.initialize()
            await self.learning_processor.initialize()
            self.initialized = True
            logger.info("Advanced NLP Service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Advanced NLP Service: {e}")
            raise
    
    async def process_command(
        self, 
        user_id: str, 
        project_name: str, 
        command: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """고급 명령 처리"""
        if not self.initialized:
            await self.initialize()
        
        try:
            logger.info(f"Processing advanced command: {command} for user {user_id}")
            
            # 1. 컨텍스트 인식 처리
            context_result = await self.context_aware_processor.process_with_context(
                user_id, project_name, command
            )
            
            # 2. 지능적 해석
            interpretation_result = await self.smart_interpreter.interpret_command(
                command, context_result["context"]
            )
            
            # 3. 학습된 제안 조회
            learned_suggestions = await self.learning_processor.get_learned_suggestions(
                command, user_id, context_result["context"]
            )
            
            # 4. 결과 통합
            result = {
                "original_command": command,
                "user_id": user_id,
                "project_name": project_name,
                "timestamp": datetime.now().isoformat(),
                
                # 기본 해석 결과
                "interpreted_command": interpretation_result.interpreted_command,
                "confidence": interpretation_result.confidence,
                "quality": interpretation_result.quality.value,
                
                # 다중 모델 결과
                "model_responses": [
                    {
                        "model": resp.model_type.value,
                        "content": resp.content,
                        "confidence": resp.confidence,
                        "processing_time": resp.processing_time
                    }
                    for resp in context_result["processed_command"].model_responses
                ],
                "best_model": context_result["processed_command"].best_response.model_type.value,
                
                # 모호함 및 제안
                "ambiguities": [
                    {
                        "type": amb.ambiguity_type.value,
                        "confidence": amb.confidence,
                        "description": amb.description,
                        "affected_parts": amb.affected_parts
                    }
                    for amb in interpretation_result.ambiguities
                ],
                "suggestions": [
                    {
                        "type": sug.suggestion_type.value,
                        "original_text": sug.original_text,
                        "suggested_text": sug.suggested_text,
                        "confidence": sug.confidence,
                        "reasoning": sug.reasoning,
                        "priority": sug.priority
                    }
                    for sug in interpretation_result.suggestions
                ],
                
                # 학습된 제안
                "learned_suggestions": learned_suggestions,
                
                # 대안
                "alternatives": interpretation_result.alternatives,
                
                # 컨텍스트
                "context": context_result["context"],
                
                # 메타데이터
                "processing_metadata": {
                    "total_processing_time": sum(
                        resp.processing_time for resp in context_result["processed_command"].model_responses
                    ),
                    "models_used": len(context_result["processed_command"].model_responses),
                    "ambiguities_detected": len(interpretation_result.ambiguities),
                    "suggestions_generated": len(interpretation_result.suggestions),
                    "learned_suggestions_count": len(learned_suggestions)
                }
            }
            
            logger.info(f"Advanced command processing completed for user {user_id}")
            return result
            
        except Exception as e:
            logger.error(f"Advanced command processing failed: {e}")
            raise
    
    async def record_feedback(
        self,
        user_id: str,
        command: str,
        original_interpretation: Dict[str, Any],
        user_correction: Dict[str, Any] = None,
        feedback_type: str = "confirmation",
        success: bool = True,
        context: Dict[str, Any] = None
    ):
        """사용자 피드백 기록"""
        try:
            feedback = LearningFeedback(
                user_id=user_id,
                command=command,
                original_interpretation=original_interpretation,
                user_correction=user_correction or original_interpretation,
                feedback_type=feedback_type,
                timestamp=datetime.now(),
                success=success,
                context=context or {}
            )
            
            await self.learning_processor.record_feedback(feedback)
            
            # 컨텍스트 인식 프로세서에도 결과 업데이트
            if "action" in original_interpretation:
                await self.context_aware_processor.update_action_result(
                    user_id, command, original_interpretation["action"], success
                )
            
            logger.info(f"Feedback recorded for user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
    
    async def get_user_insights(self, user_id: str) -> Dict[str, Any]:
        """사용자 인사이트 조회"""
        try:
            # 최근 대화 히스토리
            recent_conversations = await self.context_manager.get_recent_conversations(user_id, 10)
            
            # 사용자 패턴
            user_pattern = await self.context_manager.get_user_pattern(user_id)
            
            # 학습된 제안 (최근 명령 기반)
            recent_commands = [conv.user_input for conv in recent_conversations[:5]]
            learned_suggestions = []
            for cmd in recent_commands:
                suggestions = await self.learning_processor.get_learned_suggestions(
                    cmd, user_id, {}
                )
                learned_suggestions.extend(suggestions)
            
            return {
                "user_id": user_id,
                "recent_conversations": len(recent_conversations),
                "user_pattern": {
                    "common_commands": user_pattern.common_commands if user_pattern else [],
                    "preferred_actions": user_pattern.preferred_actions if user_pattern else {},
                    "success_rate": self._calculate_success_rate(user_pattern) if user_pattern else 0.0
                },
                "learned_suggestions": learned_suggestions[:5],
                "insights": {
                    "most_used_commands": self._get_most_used_commands(recent_conversations),
                    "success_patterns": self._get_success_patterns(recent_conversations),
                    "improvement_areas": self._get_improvement_areas(recent_conversations)
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get user insights: {e}")
            return {"error": str(e)}
    
    def _calculate_success_rate(self, user_pattern) -> float:
        """사용자 성공률 계산"""
        if not user_pattern or not user_pattern.preferred_actions:
            return 0.0
        
        total_actions = sum(user_pattern.preferred_actions.values())
        if total_actions == 0:
            return 0.0
        
        # 간단한 휴리스틱: 성공 패턴이 더 많으면 성공률이 높다고 가정
        success_patterns = len(user_pattern.success_patterns) if user_pattern.success_patterns else 0
        error_patterns = len(user_pattern.error_patterns) if user_pattern.error_patterns else 0
        
        if success_patterns + error_patterns == 0:
            return 0.5  # 중간값
        
        return success_patterns / (success_patterns + error_patterns)
    
    def _get_most_used_commands(self, conversations) -> List[str]:
        """가장 많이 사용된 명령 조회"""
        command_counts = {}
        for conv in conversations:
            cmd = conv.user_input
            command_counts[cmd] = command_counts.get(cmd, 0) + 1
        
        return sorted(command_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    def _get_success_patterns(self, conversations) -> List[str]:
        """성공 패턴 조회"""
        success_patterns = []
        for conv in conversations:
            if conv.success and conv.action_taken:
                success_patterns.append(f"{conv.user_input} -> {conv.action_taken}")
        
        return list(set(success_patterns))[:5]
    
    def _get_improvement_areas(self, conversations) -> List[str]:
        """개선 영역 조회"""
        improvement_areas = []
        
        # 실패한 명령들
        failed_commands = [conv.user_input for conv in conversations if conv.success is False]
        if failed_commands:
            improvement_areas.append(f"실패한 명령들: {', '.join(set(failed_commands))}")
        
        # 모호한 명령들 (신뢰도가 낮은 경우)
        low_confidence_commands = [
            conv.user_input for conv in conversations 
            if hasattr(conv, 'confidence') and conv.confidence < 0.7
        ]
        if low_confidence_commands:
            improvement_areas.append(f"모호한 명령들: {', '.join(set(low_confidence_commands))}")
        
        return improvement_areas
    
    async def close(self):
        """서비스 종료"""
        try:
            await self.context_manager.close()
            await self.learning_processor.close()
            await self.multi_model_processor.close()
            logger.info("Advanced NLP Service closed")
        except Exception as e:
            logger.error(f"Error closing Advanced NLP Service: {e}")

# MCP 도구로 노출할 함수들
async def process_advanced_command(
    user_id: str,
    project_name: str,
    command: str,
    context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """고급 명령 처리 (MCP 도구용)"""
    service = AdvancedNLPService()
    await service.initialize()
    
    try:
        return await service.process_command(user_id, project_name, command, context)
    finally:
        await service.close()

async def record_user_feedback(
    user_id: str,
    command: str,
    original_interpretation: Dict[str, Any],
    user_correction: Dict[str, Any] = None,
    feedback_type: str = "confirmation",
    success: bool = True
):
    """사용자 피드백 기록 (MCP 도구용)"""
    service = AdvancedNLPService()
    await service.initialize()
    
    try:
        await service.record_feedback(
            user_id, command, original_interpretation, 
            user_correction, feedback_type, success
        )
    finally:
        await service.close()

async def get_user_insights(user_id: str) -> Dict[str, Any]:
    """사용자 인사이트 조회 (MCP 도구용)"""
    service = AdvancedNLPService()
    await service.initialize()
    
    try:
        return await service.get_user_insights(user_id)
    finally:
        await service.close()

# 사용 예시
async def main():
    service = AdvancedNLPService()
    await service.initialize()
    
    try:
        # 고급 명령 처리 테스트
        result = await service.process_command(
            user_id="user123",
            project_name="my-project",
            command="앱을 배포해줘",
            context={"current_deployments": [{"name": "my-web-app"}]}
        )
        
        print("=== 고급 명령 처리 결과 ===")
        print(f"원본 명령: {result['original_command']}")
        print(f"해석된 명령: {result['interpreted_command']}")
        print(f"신뢰도: {result['confidence']:.2f}")
        print(f"품질: {result['quality']}")
        print(f"사용된 모델: {result['best_model']}")
        print(f"모호함: {len(result['ambiguities'])}개")
        print(f"제안: {len(result['suggestions'])}개")
        print(f"학습된 제안: {len(result['learned_suggestions'])}개")
        
        # 피드백 기록 테스트
        await service.record_feedback(
            user_id="user123",
            command="앱을 배포해줘",
            original_interpretation=result['interpreted_command'],
            user_correction={
                "action": "deploy",
                "target": "my-web-app",
                "environment": "staging"
            },
            feedback_type="correction",
            success=True
        )
        
        # 사용자 인사이트 조회
        insights = await service.get_user_insights("user123")
        print("\n=== 사용자 인사이트 ===")
        print(f"최근 대화: {insights['recent_conversations']}개")
        print(f"성공률: {insights['user_pattern']['success_rate']:.1%}")
        print(f"개선 영역: {insights['insights']['improvement_areas']}")
        
    finally:
        await service.close()

if __name__ == "__main__":
    asyncio.run(main())
