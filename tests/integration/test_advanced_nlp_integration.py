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

# 프로젝트 루트를 Python 경로에 추가 (pytest.ini에서 pythonpath=app 설정으로 대체되지만,
# 개별 실행 호환성을 위해 보조 경로 추가를 유지)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../app'))

from app.llm.gemini import GeminiClient
from app.llm.advanced_nlp_service import AdvancedNLPService
from app.core.config import get_settings


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
            self.advanced_nlp_service = AdvancedNLPService()
            await self.advanced_nlp_service.initialize()
            logger.info("테스트 환경 설정 완료")
            return True
        except Exception as e:
            logger.error(f"테스트 환경 설정 실패: {e}")
            return False

    async def test_basic_gemini_integration(self):
        logger.info("=== 기본 Gemini 통합 테스트 ===")
        test_commands = [
            "myapp을 스테이징에 배포해줘",
            "testapp을 프로덕션에 롤백해줘",
            "myapp의 상태를 확인해줘",
            "testapp을 3개로 스케일링해줘",
        ]
        results = []
        for command in test_commands:
            try:
                logger.info(f"테스트 명령: {command}")
                result = await self.gemini_client.interpret(
                    prompt=command,
                    user_id="test_user",
                    project_name="test_project",
                )
                results.append({
                    "command": command,
                    "success": "error" not in result,
                    "intent": result.get("intent", "unknown"),
                    "message": result.get("message", ""),
                    "llm_mode": result.get("llm", {}).get("mode", "unknown"),
                })
                logger.info(f"결과: {result.get('intent', 'unknown')} - {result.get('message', '')}")
            except Exception as e:
                logger.error(f"명령 처리 실패: {command} - {e}")
                results.append({"command": command, "success": False, "error": str(e)})
        return results

    async def test_advanced_nlp_processing(self):
        logger.info("=== 고급 NLP 처리 테스트 ===")
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return []
        test_commands = [
            "앱을 배포해줘",
            "my-web-app을 staging 환경에 2개 인스턴스로 배포해줘",
            "이전 버전으로 되돌려줘",
            "서버 상태 확인",
        ]
        results = []
        for command in test_commands:
            try:
                logger.info(f"고급 NLP 테스트 명령: {command}")
                result = await self.advanced_nlp_service.process_command(
                    user_id="test_user",
                    project_name="test_project",
                    command=command,
                    context={"current_deployments": [{"name": "my-web-app"}]},
                )
                results.append({
                    "command": command,
                    "success": True,
                    "confidence": result.get("confidence", 0.0),
                    "quality": result.get("quality", "unknown"),
                    "best_model": result.get("best_model", "unknown"),
                    "ambiguities_count": len(result.get("ambiguities", [])),
                    "suggestions_count": len(result.get("suggestions", [])),
                    "learned_suggestions_count": len(result.get("learned_suggestions", [])),
                })
                logger.info(
                    f"신뢰도: {result.get('confidence', 0.0):.2f}, "
                    f"품질: {result.get('quality', 'unknown')}, "
                    f"모델: {result.get('best_model', 'unknown')}"
                )
            except Exception as e:
                logger.error(f"고급 NLP 처리 실패: {command} - {e}")
                results.append({"command": command, "success": False, "error": str(e)})
        return results

    async def test_feedback_learning(self):
        logger.info("=== 피드백 학습 테스트 ===")
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return False
        try:
            command = "앱을 배포해줘"
            result = await self.advanced_nlp_service.process_command(
                user_id="test_user",
                project_name="test_project",
                command=command,
            )
            await self.advanced_nlp_service.record_feedback(
                user_id="test_user",
                command=command,
                original_interpretation=result["interpreted_command"],
                user_correction={"action": "deploy", "target": "my-web-app", "environment": "staging"},
                feedback_type="correction",
                success=True,
            )
            logger.info("피드백 학습 테스트 완료")
            return True
        except Exception as e:
            logger.error(f"피드백 학습 테스트 실패: {e}")
            return False

    async def test_user_insights(self):
        logger.info("=== 사용자 인사이트 테스트 ===")
        if not self.advanced_nlp_service:
            logger.error("고급 NLP 서비스가 초기화되지 않았습니다.")
            return None
        try:
            insights = await self.advanced_nlp_service.get_user_insights("test_user")
            logger.info(
                f"사용자 인사이트 조회 완료:\n- 최근 대화: {insights.get('recent_conversations', 0)}개\n"
                f"- 성공률: {insights.get('user_pattern', {}).get('success_rate', 0.0):.1%}\n"
                f"- 학습된 제안: {len(insights.get('learned_suggestions', []))}개"
            )
            return insights
        except Exception as e:
            logger.error(f"사용자 인사이트 테스트 실패: {e}")
            return None

    async def test_error_handling(self):
        logger.info("=== 오류 처리 테스트 ===")
        error_commands = ["", "invalid_command_xyz", None]
        results = []
        for command in error_commands:
            try:
                if command is None:
                    result = await self.gemini_client.interpret(
                        prompt=None,  # type: ignore
                        user_id="test_user",
                        project_name="test_project",
                    )
                else:
                    result = await self.gemini_client.interpret(
                        prompt=command,
                        user_id="test_user",
                        project_name="test_project",
                    )
                results.append({"command": str(command), "success": "error" in result, "error_handled": True})
            except Exception as e:
                results.append({
                    "command": str(command),
                    "success": False,
                    "error_handled": True,
                    "exception": str(e),
                })
        return results

    async def run_all_tests(self):
        logger.info("고급 NLP 통합 테스트 시작")
        logger.info("=" * 50)
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
            "overall_success": False,
        }
        try:
            test_results["basic_gemini"] = await self.test_basic_gemini_integration()
            test_results["advanced_nlp"] = await self.test_advanced_nlp_processing()
            test_results["feedback_learning"] = await self.test_feedback_learning()
            test_results["user_insights"] = await self.test_user_insights()
            test_results["error_handling"] = await self.test_error_handling()
            basic_success = all(r.get("success", False) for r in test_results["basic_gemini"])
            advanced_success = all(r.get("success", False) for r in test_results["advanced_nlp"])
            feedback_success = test_results["feedback_learning"]
            error_success = all(r.get("error_handled", False) for r in test_results["error_handling"])
            test_results["overall_success"] = basic_success and advanced_success and feedback_success and error_success
            self.print_test_results(test_results)
            return test_results["overall_success"]
        except Exception as e:
            logger.error(f"테스트 실행 중 오류 발생: {e}")
            return False
        finally:
            if self.advanced_nlp_service:
                await self.advanced_nlp_service.close()

    def print_test_results(self, results: Dict[str, Any]):
        logger.info("=" * 50)
        logger.info("테스트 결과 요약")
        logger.info("=" * 50)
        basic_results = results["basic_gemini"]
        basic_success = sum(1 for r in basic_results if r.get("success", False))
        logger.info(f"기본 Gemini 통합: {basic_success}/{len(basic_results)} 성공")
        advanced_results = results["advanced_nlp"]
        advanced_success = sum(1 for r in advanced_results if r.get("success", False))
        logger.info(f"고급 NLP 처리: {advanced_success}/{len(advanced_results)} 성공")
        logger.info(f"피드백 학습: {'성공' if results['feedback_learning'] else '실패'}")
        insights = results["user_insights"]
        if insights and "error" not in insights:
            logger.info(f"사용자 인사이트: 성공 (대화 {insights.get('recent_conversations', 0)}개)")
        else:
            logger.info("사용자 인사이트: 실패")
        error_results = results["error_handling"]
        error_success = sum(1 for r in error_results if r.get("error_handled", False))
        logger.info(f"오류 처리: {error_success}/{len(error_results)} 성공")
        logger.info("=" * 50)
        logger.info(f"전체 테스트 결과: {'성공' if results['overall_success'] else '실패'}")
        logger.info("=" * 50)


async def main():
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


