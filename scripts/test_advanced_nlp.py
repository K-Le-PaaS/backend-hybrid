#!/usr/bin/env python3
"""
고급 NLP 기능 간단 테스트 스크립트
개발 중 빠른 검증을 위한 스크립트
"""

import asyncio
import sys
import os
import json
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.llm.advanced_nlp_service import AdvancedNLPService
from app.llm.multi_model_processor import MultiModelProcessor, DEFAULT_CONFIG
from app.llm.context_manager import ContextManager
from app.llm.smart_command_interpreter import SmartCommandInterpreter
from app.llm.learning_processor import LearningProcessor, LearningFeedback
from datetime import datetime


async def test_basic_functionality():
    """기본 기능 테스트"""
    print("=== 기본 기능 테스트 ===")
    
    # 설정
    config = {
        "gemini": {
            "enabled": True,
            "base_url": "https://generativelanguage.googleapis.com",
            "api_key": "test-key"  # 실제 키가 필요함
        },
        "claude": {"enabled": False},
        "gpt4": {"enabled": False}
    }
    
    # 컨텍스트
    context = {
        "project_name": "test-project",
        "current_deployments": [
            {"name": "web-app", "environment": "staging", "replicas": 2},
            {"name": "api-service", "environment": "production", "replicas": 3}
        ]
    }
    
    try:
        # 1. 지능적 명령 해석 테스트
        print("\n1. 지능적 명령 해석 테스트")
        interpreter = SmartCommandInterpreter()
        
        test_commands = [
            "앱 배포해줘",
            "web-app을 staging에 3개로 배포해줘",
            "스케일링",
            "상태 확인"
        ]
        
        for command in test_commands:
            print(f"\n명령: {command}")
            result = await interpreter.interpret_command(command, context)
            print(f"  해석: {result.interpreted_command}")
            print(f"  신뢰도: {result.confidence:.2f}")
            print(f"  모호함: {len(result.ambiguities)}개")
            print(f"  제안: {len(result.suggestions)}개")
        
        # 2. 컨텍스트 관리자 테스트
        print("\n2. 컨텍스트 관리자 테스트")
        context_manager = ContextManager("redis://localhost:6379")
        context_manager.redis_client = None  # 메모리 모드
        context_manager._memory_store = {}
        
        # 컨텍스트 구성
        built_context = await context_manager.build_context_for_command(
            "test-user-123", "test-project"
        )
        print(f"  구성된 컨텍스트: {built_context}")
        
        # 3. 학습 프로세서 테스트
        print("\n3. 학습 프로세서 테스트")
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
                "confidence": 0.6
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
        print("  피드백 기록 완료")
        
        # 학습된 제안 조회
        suggestions = await learning_processor.get_learned_suggestions(
            "앱 배포해줘",
            "test-user-123",
            {"project_name": "test-project"}
        )
        print(f"  학습된 제안: {len(suggestions)}개")
        
        print("\n✅ 기본 기능 테스트 완료")
        
    except Exception as e:
        print(f"\n❌ 기본 기능 테스트 실패: {e}")
        import traceback
        traceback.print_exc()


async def test_gemini_integration():
    """Gemini 통합 테스트 (실제 API 키 필요)"""
    print("\n=== Gemini 통합 테스트 ===")
    
    # 실제 API 키가 있는지 확인
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  GEMINI_API_KEY 환경변수가 설정되지 않았습니다. 스킵합니다.")
        return
    
    try:
        # Gemini 클라이언트 테스트
        from app.llm.multi_model_processor import GeminiClient, ModelType
        
        client = GeminiClient(
            ModelType.GEMINI,
            "https://generativelanguage.googleapis.com",
            api_key
        )
        
        # 간단한 명령 테스트
        context = {
            "project_name": "test-project",
            "current_deployments": []
        }
        
        print("Gemini API 호출 중...")
        response = await client.process_command("안녕하세요", context)
        
        print(f"  응답: {response.content[:100]}...")
        print(f"  신뢰도: {response.confidence:.2f}")
        print(f"  처리 시간: {response.processing_time:.2f}초")
        
        await client.close()
        print("✅ Gemini 통합 테스트 완료")
        
    except Exception as e:
        print(f"❌ Gemini 통합 테스트 실패: {e}")


async def test_advanced_nlp_service():
    """고급 NLP 서비스 통합 테스트"""
    print("\n=== 고급 NLP 서비스 통합 테스트 ===")
    
    try:
        # 서비스 초기화
        service = AdvancedNLPService()
        await service.initialize()
        
        # 테스트 명령
        test_command = "web-app을 staging에 배포해줘"
        context = {
            "project_name": "test-project",
            "current_deployments": [
                {"name": "web-app", "environment": "staging"}
            ]
        }
        
        print(f"명령 처리 중: {test_command}")
        
        # 명령 처리 (실제 API 호출 없이)
        result = await service.process_command(
            user_id="test-user-123",
            project_name="test-project",
            command=test_command,
            context=context
        )
        
        print(f"  원본 명령: {result['original_command']}")
        print(f"  해석된 명령: {result['interpreted_command']}")
        print(f"  신뢰도: {result['confidence']:.2f}")
        print(f"  품질: {result['quality']}")
        print(f"  사용된 모델: {result['best_model']}")
        print(f"  모호함: {len(result['ambiguities'])}개")
        print(f"  제안: {len(result['suggestions'])}개")
        print(f"  학습된 제안: {len(result['learned_suggestions'])}개")
        
        await service.close()
        print("✅ 고급 NLP 서비스 통합 테스트 완료")
        
    except Exception as e:
        print(f"❌ 고급 NLP 서비스 통합 테스트 실패: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """메인 테스트 실행"""
    print("🚀 고급 NLP 기능 테스트 시작")
    print("=" * 50)
    
    # 기본 기능 테스트
    await test_basic_functionality()
    
    # Gemini 통합 테스트 (선택적)
    await test_gemini_integration()
    
    # 고급 NLP 서비스 테스트
    await test_advanced_nlp_service()
    
    print("\n" + "=" * 50)
    print("🎉 모든 테스트 완료!")


if __name__ == "__main__":
    asyncio.run(main())





