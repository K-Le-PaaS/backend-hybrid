#!/usr/bin/env python3
"""
학습 기반 개선 시스템
사용자 피드백과 패턴을 학습하여 더 정확한 명령 해석 제공
"""

import asyncio
import json
import logging
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import redis.asyncio as redis
from collections import defaultdict, Counter
import pickle
import hashlib

logger = logging.getLogger(__name__)

@dataclass
class LearningFeedback:
    """학습 피드백 데이터"""
    user_id: str
    command: str
    original_interpretation: Dict[str, Any]
    user_correction: Dict[str, Any]
    feedback_type: str  # "correction", "confirmation", "rejection"
    timestamp: datetime
    success: bool
    context: Dict[str, Any]

@dataclass
class CommandPattern:
    """명령 패턴 데이터"""
    pattern_hash: str
    command_template: str
    success_count: int
    failure_count: int
    common_interpretations: List[Dict[str, Any]]
    user_preferences: Dict[str, Any]
    last_used: datetime

@dataclass
class ModelPerformance:
    """모델 성능 데이터"""
    model_name: str
    total_requests: int
    successful_requests: int
    average_confidence: float
    average_processing_time: float
    user_satisfaction: float
    last_updated: datetime

class LearningProcessor:
    """학습 기반 프로세서"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.learning_ttl = 2592000  # 30일
        self.pattern_ttl = 7776000  # 90일
        
        # 메모리 기반 학습 데이터
        self.command_patterns: Dict[str, CommandPattern] = {}
        self.model_performance: Dict[str, ModelPerformance] = {}
        self.user_feedback: List[LearningFeedback] = []
        
        # 학습 가중치
        self.learning_weights = {
            "user_feedback": 0.4,
            "success_patterns": 0.3,
            "model_performance": 0.2,
            "context_similarity": 0.1
        }
    
    async def initialize(self):
        """초기화"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis_client.ping()
            logger.info("Learning processor initialized with Redis")
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            self.redis_client = None
            logger.info("Using in-memory storage for learning")
    
    async def record_feedback(self, feedback: LearningFeedback):
        """피드백 기록"""
        try:
            # 피드백 저장
            feedback_key = f"feedback:{feedback.user_id}:{feedback.timestamp.isoformat()}"
            feedback_data = asdict(feedback)
            feedback_data["timestamp"] = feedback.timestamp.isoformat()
            
            if self.redis_client:
                await self.redis_client.setex(
                    feedback_key,
                    self.learning_ttl,
                    json.dumps(feedback_data)
                )
            else:
                self.user_feedback.append(feedback)
            
            # 패턴 업데이트
            await self._update_command_patterns(feedback)
            
            # 모델 성능 업데이트
            await self._update_model_performance(feedback)
            
            logger.debug(f"Recorded feedback for user {feedback.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
    
    async def _update_command_patterns(self, feedback: LearningFeedback):
        """명령 패턴 업데이트"""
        try:
            # 명령 패턴 해시 생성
            pattern_hash = self._generate_pattern_hash(feedback.command)
            
            # 기존 패턴 조회
            pattern = await self._get_command_pattern(pattern_hash)
            if not pattern:
                pattern = CommandPattern(
                    pattern_hash=pattern_hash,
                    command_template=self._extract_template(feedback.command),
                    success_count=0,
                    failure_count=0,
                    common_interpretations=[],
                    user_preferences={},
                    last_used=feedback.timestamp
                )
            
            # 성공/실패 카운트 업데이트
            if feedback.success:
                pattern.success_count += 1
            else:
                pattern.failure_count += 1
            
            # 해석 패턴 업데이트
            if feedback.feedback_type == "correction":
                # 사용자 수정사항을 패턴에 반영
                pattern.common_interpretations.append(feedback.user_correction)
                # 최대 10개 유지
                pattern.common_interpretations = pattern.common_interpretations[-10:]
            
            # 사용자 선호도 업데이트
            user_prefs = pattern.user_preferences.get(feedback.user_id, {})
            if feedback.success:
                user_prefs["success_count"] = user_prefs.get("success_count", 0) + 1
            else:
                user_prefs["failure_count"] = user_prefs.get("failure_count", 0) + 1
            pattern.user_preferences[feedback.user_id] = user_prefs
            
            pattern.last_used = feedback.timestamp
            
            # 패턴 저장
            await self._save_command_pattern(pattern)
            
        except Exception as e:
            logger.error(f"Failed to update command patterns: {e}")
    
    async def _update_model_performance(self, feedback: LearningFeedback):
        """모델 성능 업데이트"""
        try:
            model_name = feedback.original_interpretation.get("model_used", "unknown")
            
            # 기존 성능 데이터 조회
            performance = await self._get_model_performance(model_name)
            if not performance:
                performance = ModelPerformance(
                    model_name=model_name,
                    total_requests=0,
                    successful_requests=0,
                    average_confidence=0.0,
                    average_processing_time=0.0,
                    user_satisfaction=0.0,
                    last_updated=feedback.timestamp
                )
            
            # 성능 지표 업데이트
            performance.total_requests += 1
            if feedback.success:
                performance.successful_requests += 1
            
            # 평균 신뢰도 업데이트
            confidence = feedback.original_interpretation.get("confidence", 0.0)
            performance.average_confidence = (
                (performance.average_confidence * (performance.total_requests - 1) + confidence) 
                / performance.total_requests
            )
            
            # 사용자 만족도 업데이트
            satisfaction_score = 1.0 if feedback.success else 0.0
            performance.user_satisfaction = (
                (performance.user_satisfaction * (performance.total_requests - 1) + satisfaction_score)
                / performance.total_requests
            )
            
            performance.last_updated = feedback.timestamp
            
            # 성능 데이터 저장
            await self._save_model_performance(performance)
            
        except Exception as e:
            logger.error(f"Failed to update model performance: {e}")
    
    async def get_learned_suggestions(self, command: str, user_id: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """학습된 제안 조회"""
        try:
            suggestions = []
            
            # 1. 명령 패턴 기반 제안
            pattern_suggestions = await self._get_pattern_based_suggestions(command, user_id)
            suggestions.extend(pattern_suggestions)
            
            # 2. 사용자 선호도 기반 제안
            preference_suggestions = await self._get_preference_based_suggestions(user_id, context)
            suggestions.extend(preference_suggestions)
            
            # 3. 모델 성능 기반 제안
            model_suggestions = await self._get_model_based_suggestions(command, context)
            suggestions.extend(model_suggestions)
            
            # 4. 유사 명령 기반 제안
            similar_suggestions = await self._get_similar_command_suggestions(command, user_id)
            suggestions.extend(similar_suggestions)
            
            # 중복 제거 및 우선순위 정렬
            unique_suggestions = self._deduplicate_suggestions(suggestions)
            return sorted(unique_suggestions, key=lambda x: x.get("priority", 0), reverse=True)[:5]
            
        except Exception as e:
            logger.error(f"Failed to get learned suggestions: {e}")
            return []
    
    async def _get_pattern_based_suggestions(self, command: str, user_id: str) -> List[Dict[str, Any]]:
        """패턴 기반 제안"""
        suggestions = []
        
        try:
            pattern_hash = self._generate_pattern_hash(command)
            pattern = await self._get_command_pattern(pattern_hash)
            
            if pattern and pattern.success_count > 0:
                # 성공한 해석 패턴 제안
                success_rate = pattern.success_count / (pattern.success_count + pattern.failure_count)
                
                for interpretation in pattern.common_interpretations[-3:]:  # 최근 3개
                    suggestions.append({
                        "type": "pattern_based",
                        "suggestion": interpretation,
                        "confidence": success_rate,
                        "priority": int(success_rate * 5),
                        "reasoning": f"이 명령은 {success_rate:.1%} 확률로 성공했습니다"
                    })
            
        except Exception as e:
            logger.error(f"Failed to get pattern-based suggestions: {e}")
        
        return suggestions
    
    async def _get_preference_based_suggestions(self, user_id: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """사용자 선호도 기반 제안"""
        suggestions = []
        
        try:
            # 사용자의 성공 패턴 조회
            user_patterns = await self._get_user_success_patterns(user_id)
            
            for pattern in user_patterns:
                if pattern.success_count > pattern.failure_count:
                    suggestions.append({
                        "type": "preference_based",
                        "suggestion": pattern.common_interpretations[-1] if pattern.common_interpretations else {},
                        "confidence": pattern.success_count / (pattern.success_count + pattern.failure_count),
                        "priority": 4,
                        "reasoning": f"사용자가 자주 사용하는 성공 패턴입니다"
                    })
            
        except Exception as e:
            logger.error(f"Failed to get preference-based suggestions: {e}")
        
        return suggestions
    
    async def _get_model_based_suggestions(self, command: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """모델 성능 기반 제안"""
        suggestions = []
        
        try:
            # 모든 모델의 성능 조회
            all_performance = await self._get_all_model_performance()
            
            # 가장 성능이 좋은 모델 추천
            best_model = max(all_performance.values(), key=lambda p: p.user_satisfaction)
            
            if best_model.user_satisfaction > 0.7:
                suggestions.append({
                    "type": "model_based",
                    "suggestion": {"recommended_model": best_model.model_name},
                    "confidence": best_model.user_satisfaction,
                    "priority": 3,
                    "reasoning": f"{best_model.model_name} 모델이 {best_model.user_satisfaction:.1%} 만족도를 보입니다"
                })
            
        except Exception as e:
            logger.error(f"Failed to get model-based suggestions: {e}")
        
        return suggestions
    
    async def _get_similar_command_suggestions(self, command: str, user_id: str) -> List[Dict[str, Any]]:
        """유사 명령 기반 제안"""
        suggestions = []
        
        try:
            # 유사한 명령 패턴 찾기
            similar_patterns = await self._find_similar_patterns(command)
            
            for pattern in similar_patterns:
                if pattern.success_count > pattern.failure_count:
                    suggestions.append({
                        "type": "similar_command",
                        "suggestion": pattern.common_interpretations[-1] if pattern.common_interpretations else {},
                        "confidence": pattern.success_count / (pattern.success_count + pattern.failure_count),
                        "priority": 2,
                        "reasoning": f"유사한 명령 '{pattern.command_template}'의 성공 패턴입니다"
                    })
            
        except Exception as e:
            logger.error(f"Failed to get similar command suggestions: {e}")
        
        return suggestions
    
    def _generate_pattern_hash(self, command: str) -> str:
        """명령 패턴 해시 생성"""
        # 명령을 정규화하여 패턴 해시 생성
        normalized = command.lower().strip()
        # 일반적인 단어들을 제거하여 패턴 추출
        stop_words = ["해줘", "해주세요", "please", "해", "해봐"]
        for word in stop_words:
            normalized = normalized.replace(word, "")
        normalized = " ".join(normalized.split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
    
    def _extract_template(self, command: str) -> str:
        """명령 템플릿 추출"""
        # 구체적인 값들을 변수로 치환
        template = command.lower()
        # 숫자 치환
        template = re.sub(r'\d+', '{NUMBER}', template)
        # 앱 이름 치환 (간단한 휴리스틱)
        words = template.split()
        for i, word in enumerate(words):
            if len(word) > 2 and not word in ["앱", "app", "서비스", "service"]:
                words[i] = '{APP_NAME}'
        return " ".join(words)
    
    async def _get_command_pattern(self, pattern_hash: str) -> Optional[CommandPattern]:
        """명령 패턴 조회"""
        try:
            if self.redis_client:
                data = await self.redis_client.get(f"pattern:{pattern_hash}")
                if data:
                    pattern_data = json.loads(data)
                    return CommandPattern(
                        pattern_hash=pattern_data["pattern_hash"],
                        command_template=pattern_data["command_template"],
                        success_count=pattern_data["success_count"],
                        failure_count=pattern_data["failure_count"],
                        common_interpretations=pattern_data["common_interpretations"],
                        user_preferences=pattern_data["user_preferences"],
                        last_used=datetime.fromisoformat(pattern_data["last_used"])
                    )
            else:
                return self.command_patterns.get(pattern_hash)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get command pattern: {e}")
            return None
    
    async def _save_command_pattern(self, pattern: CommandPattern):
        """명령 패턴 저장"""
        try:
            pattern_data = {
                "pattern_hash": pattern.pattern_hash,
                "command_template": pattern.command_template,
                "success_count": pattern.success_count,
                "failure_count": pattern.failure_count,
                "common_interpretations": pattern.common_interpretations,
                "user_preferences": pattern.user_preferences,
                "last_used": pattern.last_used.isoformat()
            }
            
            if self.redis_client:
                await self.redis_client.setex(
                    f"pattern:{pattern.pattern_hash}",
                    self.pattern_ttl,
                    json.dumps(pattern_data)
                )
            else:
                self.command_patterns[pattern.pattern_hash] = pattern
            
        except Exception as e:
            logger.error(f"Failed to save command pattern: {e}")
    
    async def _get_model_performance(self, model_name: str) -> Optional[ModelPerformance]:
        """모델 성능 조회"""
        try:
            if self.redis_client:
                data = await self.redis_client.get(f"model_perf:{model_name}")
                if data:
                    perf_data = json.loads(data)
                    return ModelPerformance(
                        model_name=perf_data["model_name"],
                        total_requests=perf_data["total_requests"],
                        successful_requests=perf_data["successful_requests"],
                        average_confidence=perf_data["average_confidence"],
                        average_processing_time=perf_data["average_processing_time"],
                        user_satisfaction=perf_data["user_satisfaction"],
                        last_updated=datetime.fromisoformat(perf_data["last_updated"])
                    )
            else:
                return self.model_performance.get(model_name)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get model performance: {e}")
            return None
    
    async def _save_model_performance(self, performance: ModelPerformance):
        """모델 성능 저장"""
        try:
            perf_data = {
                "model_name": performance.model_name,
                "total_requests": performance.total_requests,
                "successful_requests": performance.successful_requests,
                "average_confidence": performance.average_confidence,
                "average_processing_time": performance.average_processing_time,
                "user_satisfaction": performance.user_satisfaction,
                "last_updated": performance.last_updated.isoformat()
            }
            
            if self.redis_client:
                await self.redis_client.setex(
                    f"model_perf:{performance.model_name}",
                    self.learning_ttl,
                    json.dumps(perf_data)
                )
            else:
                self.model_performance[performance.model_name] = performance
            
        except Exception as e:
            logger.error(f"Failed to save model performance: {e}")
    
    async def _get_user_success_patterns(self, user_id: str) -> List[CommandPattern]:
        """사용자 성공 패턴 조회"""
        # 구현 생략 - 사용자별 성공 패턴 조회 로직
        return []
    
    async def _get_all_model_performance(self) -> Dict[str, ModelPerformance]:
        """모든 모델 성능 조회"""
        # 구현 생략 - 모든 모델 성능 조회 로직
        return {}
    
    async def _find_similar_patterns(self, command: str) -> List[CommandPattern]:
        """유사 패턴 찾기"""
        # 구현 생략 - 유사 패턴 찾기 로직
        return []
    
    def _deduplicate_suggestions(self, suggestions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """중복 제안 제거"""
        seen = set()
        unique_suggestions = []
        
        for suggestion in suggestions:
            suggestion_key = json.dumps(suggestion["suggestion"], sort_keys=True)
            if suggestion_key not in seen:
                seen.add(suggestion_key)
                unique_suggestions.append(suggestion)
        
        return unique_suggestions
    
    async def close(self):
        """리소스 정리"""
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Learning processor closed")

# 사용 예시
async def main():
    learning_processor = LearningProcessor()
    await learning_processor.initialize()
    
    try:
        # 피드백 기록 예시
        feedback = LearningFeedback(
            user_id="user123",
            command="앱 배포해줘",
            original_interpretation={
                "action": "deploy",
                "target": "unknown",
                "confidence": 0.6,
                "model_used": "claude"
            },
            user_correction={
                "action": "deploy",
                "target": "my-web-app",
                "environment": "staging"
            },
            feedback_type="correction",
            timestamp=datetime.now(),
            success=True,
            context={"project_name": "test-project"}
        )
        
        await learning_processor.record_feedback(feedback)
        
        # 학습된 제안 조회
        suggestions = await learning_processor.get_learned_suggestions(
            "앱 배포해줘",
            "user123",
            {"project_name": "test-project"}
        )
        
        print(f"학습된 제안: {len(suggestions)}개")
        for suggestion in suggestions:
            print(f"  - {suggestion['reasoning']}: {suggestion['suggestion']}")
        
    finally:
        await learning_processor.close()

if __name__ == "__main__":
    import re
    asyncio.run(main())
