#!/usr/bin/env python3
"""
고급 NLP 통합 테스트 스크립트
다중 모델, 컨텍스트 인식, 지능적 해석, 학습 기반 개선 기능을 통합 테스트
"""

import asyncio
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
from typing import Dict, Any

# 테스트 대상 모듈들
from app.llm.advanced_nlp_service import AdvancedNLPService
from app.llm.multi_model_processor import MultiModelProcessor, DEFAULT_CONFIG
from app.llm.context_manager import ContextManager
from app.llm.smart_command_interpreter import SmartCommandInterpreter
from app.llm.learning_processor import LearningProcessor, LearningFeedback
from app.mcp.tools.advanced_nlp import process_advanced_command, record_user_feedback, get_user_insights


class TestAdvancedNLPIntegration:
    """고급 NLP 통합 테스트 클래스"""
    
    @pytest.fixture
    async def mock_config(self):
        """모의 설정"""
        return {
            "gemini": {
                "enabled": True,
                "base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-api-key"
            },
            "claude": {
                "enabled": False,
                "base_url": "https://api.anthropic.com",
                "api_key": "test-claude-key"
            },
            "gpt4": {
                "enabled": False,
                "base_url": "https://api.openai.com",
                "api_key": "test-gpt4-key"
            }
        }
    
    @pytest.fixture
    async def mock_context(self):
        """모의 컨텍스트"""
        return {
            "project_name": "test-project",
            "current_deployments": [
                {"name": "web-app", "environment": "staging", "replicas": 2},
                {"name": "api-service", "environment": "production", "replicas": 3}
            ],
            "user_id": "test-user-123",
            "recent_conversations": [
                {
                    "user_input": "앱 상태 확인해줘",
                    "system_response": "현재 배포된 앱들의 상태를 확인했습니다",
                    "action_taken": "status_check",
                    "success": True
                }
            ]
        }
    
    @pytest.fixture
    async def advanced_nlp_service(self, mock_config):
        """고급 NLP 서비스 인스턴스"""
        service = AdvancedNLPService(mock_config)
        await service.initialize()
        return service
    
    @pytest.mark.asyncio
    async def test_advanced_command_processing(self, advanced_nlp_service, mock_context):
        """고급 명령 처리 테스트"""
        # 테스트 명령
        test_command = "web-app을 staging에 3개 복제본으로 배포해줘"
        
        # Gemini API 모의 응답
        mock_gemini_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "action": "deploy",
                            "target": "web-app",
                            "parameters": {
                                "replicas": 3,
                                "environment": "staging"
                            },
                            "confidence": 0.95,
                            "ambiguities": [],
                            "suggestions": [],
                            "alternatives": [],
                            "warnings": [],
                            "next_steps": ["배포 완료 후 상태 확인"],
                            "learning_notes": "복제본 수와 환경을 명확히 지정한 좋은 명령입니다"
                        })
                    }]
                }
            }],
            "usageMetadata": {
                "totalTokenCount": 150
            }
        }
        
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = mock_gemini_response
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            # 명령 처리 실행
            result = await advanced_nlp_service.process_command(
                user_id="test-user-123",
                project_name="test-project",
                command=test_command,
                context=mock_context
            )
            
            # 결과 검증
            assert result["original_command"] == test_command
            assert result["user_id"] == "test-user-123"
            assert result["project_name"] == "test-project"
            assert "interpreted_command" in result
            assert "model_responses" in result
            assert "ambiguities" in result
            assert "suggestions" in result
            assert "learned_suggestions" in result
            assert "processing_metadata" in result
            
            # 처리 메타데이터 검증
            metadata = result["processing_metadata"]
            assert metadata["models_used"] > 0
            assert metadata["total_processing_time"] > 0
    
    @pytest.mark.asyncio
    async def test_context_aware_processing(self, mock_config, mock_context):
        """컨텍스트 인식 처리 테스트"""
        # 컨텍스트 관리자 모의
        context_manager = ContextManager("redis://localhost:6379")
        context_manager.redis_client = None  # 메모리 모드
        context_manager._memory_store = {}
        
        # 다중 모델 프로세서 모의
        multi_processor = MultiModelProcessor(mock_config)
        
        # 컨텍스트 인식 프로세서 생성
        from app.llm.context_manager import ContextAwareProcessor
        processor = ContextAwareProcessor(context_manager, multi_processor)
        
        # Gemini API 모의
        mock_gemini_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "action": "deploy",
                            "target": "web-app",
                            "parameters": {"replicas": 3, "environment": "staging"},
                            "confidence": 0.9
                        })
                    }]
                }
            }],
            "usageMetadata": {"totalTokenCount": 100}
        }
        
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = mock_gemini_response
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            # 컨텍스트 인식 처리 실행
            result = await processor.process_with_context(
                user_id="test-user-123",
                project_name="test-project",
                command="web-app 배포해줘"
            )
            
            # 결과 검증
            assert "processed_command" in result
            assert "context" in result
            assert "conversation_turn" in result
            
            # 컨텍스트 검증
            context = result["context"]
            assert context["user_id"] == "test-user-123"
            assert context["project_name"] == "test-project"
            assert "recent_conversations" in context
    
    @pytest.mark.asyncio
    async def test_smart_command_interpretation(self):
        """지능적 명령 해석 테스트"""
        interpreter = SmartCommandInterpreter()
        
        # 테스트 케이스들
        test_cases = [
            {
                "command": "앱 배포해줘",
                "expected_ambiguities": ["MISSING_TARGET"],
                "expected_suggestions": True
            },
            {
                "command": "my-app을 staging에 3개로 배포해줘",
                "expected_ambiguities": [],
                "expected_suggestions": False
            },
            {
                "command": "스케일링",
                "expected_ambiguities": ["MISSING_TARGET", "MISSING_PARAMETERS"],
                "expected_suggestions": True
            }
        ]
        
        context = {
            "current_deployments": [
                {"name": "my-web-app", "environment": "staging"},
                {"name": "my-api", "environment": "production"}
            ]
        }
        
        for test_case in test_cases:
            result = await interpreter.interpret_command(
                test_case["command"], 
                context
            )
            
            # 기본 검증
            assert result.original_command == test_case["command"]
            assert result.confidence >= 0.0
            assert result.confidence <= 1.0
            
            # 모호함 검증
            if test_case["expected_ambiguities"]:
                assert len(result.ambiguities) > 0
                ambiguity_types = [amb.ambiguity_type.value for amb in result.ambiguities]
                for expected_type in test_case["expected_ambiguities"]:
                    assert expected_type in ambiguity_types
            
            # 제안 검증
            if test_case["expected_suggestions"]:
                assert len(result.suggestions) > 0
            else:
                assert len(result.suggestions) == 0
    
    @pytest.mark.asyncio
    async def test_learning_processor(self):
        """학습 프로세서 테스트"""
        learning_processor = LearningProcessor("redis://localhost:6379")
        learning_processor.redis_client = None  # 메모리 모드
        learning_processor._memory_store = {}
        
        # 피드백 생성
        feedback = LearningFeedback(
            user_id="test-user-123",
            command="앱 배포해줘",
            original_interpretation={
                "action": "deploy",
                "target": "unknown",
                "confidence": 0.6,
                "model_used": "gemini"
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
        
        # 피드백 기록
        await learning_processor.record_feedback(feedback)
        
        # 학습된 제안 조회
        suggestions = await learning_processor.get_learned_suggestions(
            "앱 배포해줘",
            "test-user-123",
            {"project_name": "test-project"}
        )
        
        # 결과 검증
        assert isinstance(suggestions, list)
        # 메모리 모드에서는 패턴이 저장되지 않을 수 있음
        # assert len(suggestions) >= 0
    
    @pytest.mark.asyncio
    async def test_mcp_tools_integration(self, mock_config):
        """MCP 도구 통합 테스트"""
        # Gemini API 모의
        mock_gemini_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "action": "deploy",
                            "target": "test-app",
                            "parameters": {"replicas": 2, "environment": "staging"},
                            "confidence": 0.9
                        })
                    }]
                }
            }],
            "usageMetadata": {"totalTokenCount": 120}
        }
        
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = mock_gemini_response
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            # MCP 도구 테스트
            result = await process_advanced_command(
                user_id="test-user-123",
                project_name="test-project",
                command="test-app 배포해줘"
            )
            
            # 결과 검증
            assert result["original_command"] == "test-app 배포해줘"
            assert result["user_id"] == "test-user-123"
            assert result["project_name"] == "test-project"
            assert "model_response" in result
            assert "advanced_features" in result
    
    @pytest.mark.asyncio
    async def test_error_handling(self, advanced_nlp_service, mock_context):
        """에러 처리 테스트"""
        # API 에러 시뮬레이션
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.side_effect = Exception("API Error")
            
            # 에러가 발생해도 서비스가 중단되지 않는지 확인
            try:
                result = await advanced_nlp_service.process_command(
                    user_id="test-user-123",
                    project_name="test-project",
                    command="test command",
                    context=mock_context
                )
                # 에러가 발생하면 빈 결과가 반환되어야 함
                assert result is not None
            except Exception as e:
                # 예상된 에러인지 확인
                assert "API Error" in str(e)
    
    @pytest.mark.asyncio
    async def test_performance_metrics(self, advanced_nlp_service, mock_context):
        """성능 메트릭 테스트"""
        # Gemini API 모의
        mock_gemini_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "action": "deploy",
                            "target": "test-app",
                            "confidence": 0.9
                        })
                    }]
                }
            }],
            "usageMetadata": {"totalTokenCount": 100}
        }
        
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = mock_gemini_response
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            # 성능 측정
            start_time = asyncio.get_event_loop().time()
            
            result = await advanced_nlp_service.process_command(
                user_id="test-user-123",
                project_name="test-project",
                command="test-app 배포해줘",
                context=mock_context
            )
            
            end_time = asyncio.get_event_loop().time()
            total_time = end_time - start_time
            
            # 성능 검증
            assert total_time < 5.0  # 5초 이내 완료
            assert result["processing_metadata"]["total_processing_time"] > 0
            assert result["processing_metadata"]["models_used"] > 0


# 통합 테스트 실행 함수
async def run_integration_tests():
    """통합 테스트 실행"""
    print("=== 고급 NLP 통합 테스트 시작 ===")
    
    # 테스트 실행
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--asyncio-mode=auto"
    ])
    
    print("=== 고급 NLP 통합 테스트 완료 ===")


if __name__ == "__main__":
    asyncio.run(run_integration_tests())






