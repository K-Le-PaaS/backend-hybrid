#!/usr/bin/env python3
"""
고급 자연어 처리 통합 테스트 스크립트
T-047 고급 자연어 처리 및 AI 모델 통합 완료 테스트
"""

import asyncio
import logging
import sys
import os
from typing import Dict, Any
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.llm.gemini import GeminiClient
from app.llm.advanced_nlp_service import AdvancedNLPService
from app.core.config import get_settings

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AdvancedNLPIntegrationTester:
    """고급 NLP 통합 테스트 클래스"""
    
    def __init__(self):
        self.settings = get_settings()
        self.gemini_client = GeminiClient()
        self.advanced_nlp_service = None
        
    async def setup(self):
        """테스트 환경 설정"""
        try:
            logger.info("고급 NLP 통합 테스트 환경 설정 중...")
            
            # 고급 NLP 서비스 초기화
            self.advanced_nlp_service = AdvancedNLPService()
            await self.advanced_nlp_service.initialize()
            
            logger.info("테스트 환경 설정 완료")
            return True
            
        except Exception as e:
            logger.error(f"테스트 환경 설정 실패: {e}")
            return False
    
    async def test_basic_gemini_integration(self):
        """기본 Gemini 통합 테스트"""
        logger.info("=== 기본 Gemini 통합 테스트 ===")
        
        test_commands = [
            "myapp을 스테이징에 배포해줘",
            "testapp을 프로덕션에 롤백해줘",
            "myapp의 상태를 확인해줘",
            "testapp을 3개로 스케일링해줘"
        ]
        
        results = []
        for command in test_commands:
            try:
                logger.info(f"테스트 명령: {command}")
                result = await self.gemini_client.interpret(
                    prompt=command,
                    user_id="test_user",
                    project_name="test_project"
                )
                
                results.append({
                    "command": command,
                    "success": "error" not in result,
                    "intent": result.get("intent", "unknown"),
                    "message": result.get("message", ""),
                    "llm_mode": result.get("llm", {}).get("mode", "unknown")
                })
                
                logger.info(f"결과: {result.get('intent', 'unknown')} - {result.get('message', '')}")
                
            except Exception as e:
                logger.error(f"명령 처리 실패: {command} - {e}")
                results.append({
                    "command": command,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def test_advanced_nlp_processing(self):
        """고급 NLP 처리 테스트"""
        logger.info("=== 고급 NLP 처리 테스트 ===")
        
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return []
        
        test_commands = [
            "앱을 배포해줘",  # 모호한 명령
            "my-web-app을 staging 환경에 2개 인스턴스로 배포해줘",  # 명확한 명령
            "이전 버전으로 되돌려줘",  # 컨텍스트가 필요한 명령
            "서버 상태 확인",  # 간단한 명령
        ]
        
        results = []
        for command in test_commands:
            try:
                logger.info(f"고급 NLP 테스트 명령: {command}")
                result = await self.advanced_nlp_service.process_command(
                    user_id="test_user",
                    project_name="test_project",
                    command=command,
                    context={"current_deployments": [{"name": "my-web-app"}]}
                )
                
                results.append({
                    "command": command,
                    "success": True,
                    "confidence": result.get("confidence", 0.0),
                    "quality": result.get("quality", "unknown"),
                    "best_model": result.get("best_model", "unknown"),
                    "ambiguities_count": len(result.get("ambiguities", [])),
                    "suggestions_count": len(result.get("suggestions", [])),
                    "learned_suggestions_count": len(result.get("learned_suggestions", []))
                })
                
                logger.info(f"신뢰도: {result.get('confidence', 0.0):.2f}, "
                          f"품질: {result.get('quality', 'unknown')}, "
                          f"모델: {result.get('best_model', 'unknown')}")
                
            except Exception as e:
                logger.error(f"고급 NLP 처리 실패: {command} - {e}")
                results.append({
                    "command": command,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def test_feedback_learning(self):
        """피드백 학습 테스트"""
        logger.info("=== 피드백 학습 테스트 ===")
        
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return False
        
        try:
            # 테스트 명령 처리
            command = "앱을 배포해줘"
            result = await self.advanced_nlp_service.process_command(
                user_id="test_user",
                project_name="test_project",
                command=command
            )
            
            # 피드백 기록
            await self.advanced_nlp_service.record_feedback(
                user_id="test_user",
                command=command,
                original_interpretation=result["interpreted_command"],
                user_correction={
                    "action": "deploy",
                    "target": "my-web-app",
                    "environment": "staging"
                },
                feedback_type="correction",
                success=True
            )
            
            logger.info("피드백 학습 테스트 완료")
            return True
            
        except Exception as e:
            logger.error(f"피드백 학습 테스트 실패: {e}")
            return False
    
    async def test_user_insights(self):
        """사용자 인사이트 테스트"""
        logger.info("=== 사용자 인사이트 테스트 ===")
        
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return None
        
        try:
            insights = await self.advanced_nlp_service.get_user_insights("test_user")
            
            logger.info(f"사용자 인사이트 조회 완료:")
            logger.info(f"- 최근 대화: {insights.get('recent_conversations', 0)}개")
            logger.info(f"- 성공률: {insights.get('user_pattern', {}).get('success_rate', 0.0):.1%}")
            logger.info(f"- 학습된 제안: {len(insights.get('learned_suggestions', []))}개")
            
            return insights
            
        except Exception as e:
            logger.error(f"사용자 인사이트 테스트 실패: {e}")
            return None
    
    async def test_error_handling(self):
        """오류 처리 테스트"""
        logger.info("=== 오류 처리 테스트 ===")
        
        error_commands = [
            "",  # 빈 명령
            "invalid_command_xyz",  # 잘못된 명령
            None,  # None 값
        ]
        
        results = []
        for command in error_commands:
            try:
                if command is None:
                    # None 값 테스트
                    result = await self.gemini_client.interpret(
                        prompt=None,  # type: ignore
                        user_id="test_user",
                        project_name="test_project"
                    )
                else:
                    result = await self.gemini_client.interpret(
                        prompt=command,
                        user_id="test_user",
                        project_name="test_project"
                    )
                
                results.append({
                    "command": str(command),
                    "success": "error" in result,
                    "error_handled": True
                })
                
            except Exception as e:
                results.append({
                    "command": str(command),
                    "success": False,
                    "error_handled": True,
                    "exception": str(e)
                })
        
        return results
    
    async def run_all_tests(self):
        """모든 테스트 실행"""
        logger.info("고급 NLP 통합 테스트 시작")
        logger.info("=" * 50)
        
        # 환경 설정
        if not await self.setup():
            logger.error("테스트 환경 설정 실패")
            return False
        
        test_results = {
            "timestamp": datetime.now().isoformat(),
            "basic_gemini": [],
            "advanced_nlp": [],
            "feedback_learning": False,
            "user_insights": None,
            "error_handling": [],
            "overall_success": False
        }
        
        try:
            # 1. 기본 Gemini 통합 테스트
            test_results["basic_gemini"] = await self.test_basic_gemini_integration()
            
            # 2. 고급 NLP 처리 테스트
            test_results["advanced_nlp"] = await self.test_advanced_nlp_processing()
            
            # 3. 피드백 학습 테스트
            test_results["feedback_learning"] = await self.test_feedback_learning()
            
            # 4. 사용자 인사이트 테스트
            test_results["user_insights"] = await self.test_user_insights()
            
            # 5. 오류 처리 테스트
            test_results["error_handling"] = await self.test_error_handling()
            
            # 전체 성공 여부 계산
            basic_success = all(r.get("success", False) for r in test_results["basic_gemini"])
            advanced_success = all(r.get("success", False) for r in test_results["advanced_nlp"])
            feedback_success = test_results["feedback_learning"]
            error_success = all(r.get("error_handled", False) for r in test_results["error_handling"])
            
            test_results["overall_success"] = (
                basic_success and advanced_success and 
                feedback_success and error_success
            )
            
            # 결과 출력
            self.print_test_results(test_results)
            
            return test_results["overall_success"]
            
        except Exception as e:
            logger.error(f"테스트 실행 중 오류 발생: {e}")
            return False
        
        finally:
            # 정리
            if self.advanced_nlp_service:
                await self.advanced_nlp_service.close()
    
    def print_test_results(self, results: Dict[str, Any]):
        """테스트 결과 출력"""
        logger.info("=" * 50)
        logger.info("테스트 결과 요약")
        logger.info("=" * 50)
        
        # 기본 Gemini 테스트 결과
        basic_results = results["basic_gemini"]
        basic_success = sum(1 for r in basic_results if r.get("success", False))
        logger.info(f"기본 Gemini 통합: {basic_success}/{len(basic_results)} 성공")
        
        # 고급 NLP 테스트 결과
        advanced_results = results["advanced_nlp"]
        advanced_success = sum(1 for r in advanced_results if r.get("success", False))
        logger.info(f"고급 NLP 처리: {advanced_success}/{len(advanced_results)} 성공")
        
        # 피드백 학습 결과
        logger.info(f"피드백 학습: {'성공' if results['feedback_learning'] else '실패'}")
        
        # 사용자 인사이트 결과
        insights = results["user_insights"]
        if insights and "error" not in insights:
            logger.info(f"사용자 인사이트: 성공 (대화 {insights.get('recent_conversations', 0)}개)")
        else:
            logger.info("사용자 인사이트: 실패")
        
        # 오류 처리 결과
        error_results = results["error_handling"]
        error_success = sum(1 for r in error_results if r.get("error_handled", False))
        logger.info(f"오류 처리: {error_success}/{len(error_results)} 성공")
        
        # 전체 결과
        logger.info("=" * 50)
        logger.info(f"전체 테스트 결과: {'성공' if results['overall_success'] else '실패'}")
        logger.info("=" * 50)

async def main():
    """메인 함수"""
    tester = AdvancedNLPIntegrationTester()
    success = await tester.run_all_tests()
    
    if success:
        logger.info("모든 테스트가 성공적으로 완료되었습니다!")
        sys.exit(0)
    else:
        logger.error("일부 테스트가 실패했습니다.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())





















