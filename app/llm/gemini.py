from typing import Any, Dict, List, Optional

from .interfaces import LLMClient
from .advanced_nlp_service import AdvancedNLPService
from ..core.config import get_settings
from ..mcp.external.registry import mcp_registry


class GeminiClient(LLMClient):
    def __init__(self) -> None:
        self.settings = get_settings()
        self.advanced_nlp_service = None

    async def interpret(self, prompt: str, user_id: str = "default", project_name: str = "default") -> Dict[str, Any]:
        """자연어 명령을 해석하고 적절한 MCP 도구를 호출합니다."""
        try:
            # 고급 자연어 처리 서비스 초기화
            if not self.advanced_nlp_service:
                self.advanced_nlp_service = AdvancedNLPService()
                await self.advanced_nlp_service.initialize()
            
            # 고급 자연어 처리로 명령 해석
            advanced_result = await self.advanced_nlp_service.process_command(
                user_id=user_id,
                project_name=project_name,
                command=prompt
            )
            
            # 기존 방식으로 폴백 (호환성 유지)
            if advanced_result["confidence"] < 0.5:
                return await self._legacy_interpret(prompt)
            
            # 고급 해석 결과를 기존 형식으로 변환
            interpreted = advanced_result["interpreted_command"]
            intent = interpreted.get("action", "unknown")
            
            if intent == "deploy":
                return await self._handle_deploy_intent_advanced(prompt, interpreted, advanced_result)
            elif intent == "rollback":
                return await self._handle_rollback_intent_advanced(prompt, interpreted, advanced_result)
            elif intent == "scale":
                return await self._handle_scale_intent_advanced(prompt, interpreted, advanced_result)
            elif intent == "status":
                return await self._handle_monitor_intent_advanced(prompt, interpreted, advanced_result)
            else:
                return {
                    "intent": intent,
                    "entities": interpreted,
                    "message": f"고급 해석 결과: {advanced_result['best_model']} 모델이 {advanced_result['confidence']:.2f} 신뢰도로 해석했습니다.",
                    "advanced_nlp": advanced_result,
                    "llm": {
                        "provider": "gemini_advanced",
                        "model": advanced_result["best_model"],
                        "confidence": advanced_result["confidence"],
                        "quality": advanced_result["quality"],
                        "mode": "advanced_nlp",
                    },
                }
        except Exception as e:
            # 고급 처리 실패 시 기존 방식으로 폴백
            return await self._legacy_interpret(prompt)
    
    async def _legacy_interpret(self, prompt: str) -> Dict[str, Any]:
        """기존 방식의 명령 해석 (폴백)"""
        try:
            # 간단한 키워드 기반 의도 분류
            intent = self._classify_intent(prompt)
            
            if intent == "deploy":
                return await self._handle_deploy_intent(prompt)
            elif intent == "rollback":
                return await self._handle_rollback_intent(prompt)
            elif intent == "monitor":
                return await self._handle_monitor_intent(prompt)
            else:
                return {
                    "intent": "unknown",
                    "entities": {"raw": prompt},
                    "message": "지원하지 않는 명령입니다. 배포, 롤백, 모니터링 명령을 사용해주세요.",
                    "llm": {
                        "provider": "gemini",
                        "model": self.settings.gemini_model,
                        "project": self.settings.gcp_project,
                        "location": self.settings.gcp_location,
                        "mode": "legacy",
                    },
                }
        except Exception as e:
            return {
                "intent": "error",
                "entities": {"raw": prompt},
                "error": str(e),
                "message": "명령 처리 중 오류가 발생했습니다.",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "error",
                },
            }

    def _classify_intent(self, prompt: str) -> str:
        """자연어 명령의 의도를 분류합니다."""
        prompt_lower = prompt.lower()
        
        if any(word in prompt_lower for word in ["배포", "deploy", "배포해", "배포해줘"]):
            return "deploy"
        elif any(word in prompt_lower for word in ["롤백", "rollback", "되돌리", "이전"]):
            return "rollback"
        elif any(word in prompt_lower for word in ["모니터", "monitor", "상태", "확인"]):
            return "monitor"
        else:
            return "unknown"

    async def _handle_deploy_intent(self, prompt: str) -> Dict[str, Any]:
        """배포 의도를 처리합니다."""
        # 간단한 파라미터 추출 (실제로는 Gemini API를 사용해야 함)
        entities = self._extract_deploy_entities(prompt)
        
        try:
            # MCP 도구 호출
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="deploy_application",
                arguments=entities
            )
            
            return {
                "intent": "deploy",
                "entities": entities,
                "result": result,
                "message": f"배포 명령이 성공적으로 처리되었습니다: {entities.get('app_name', '알 수 없음')}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }
        except Exception as e:
            return {
                "intent": "deploy",
                "entities": entities,
                "error": str(e),
                "message": f"배포 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }

    async def _handle_rollback_intent(self, prompt: str) -> Dict[str, Any]:
        """롤백 의도를 처리합니다."""
        entities = self._extract_rollback_entities(prompt)
        
        try:
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="rollback_deployment",
                arguments=entities
            )
            
            return {
                "intent": "rollback",
                "entities": entities,
                "result": result,
                "message": f"롤백 명령이 성공적으로 처리되었습니다: {entities.get('app_name', '알 수 없음')}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }
        except Exception as e:
            return {
                "intent": "rollback",
                "entities": entities,
                "error": str(e),
                "message": f"롤백 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }

    async def _handle_monitor_intent(self, prompt: str) -> Dict[str, Any]:
        """모니터링 의도를 처리합니다."""
        entities = self._extract_monitor_entities(prompt)
        
        try:
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="query_metrics",
                arguments=entities
            )
            
            return {
                "intent": "monitor",
                "entities": entities,
                "result": result,
                "message": f"모니터링 명령이 성공적으로 처리되었습니다",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }
        except Exception as e:
            return {
                "intent": "monitor",
                "entities": entities,
                "error": str(e),
                "message": f"모니터링 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "project": self.settings.gcp_project,
                    "location": self.settings.gcp_location,
                    "mode": "mcp_integration",
                },
            }

    def _extract_deploy_entities(self, prompt: str) -> Dict[str, Any]:
        """배포 명령에서 엔티티를 추출합니다."""
        # 간단한 키워드 기반 추출 (실제로는 Gemini API 사용)
        prompt_lower = prompt.lower()
        
        # 기본값 설정
        entities = {
            "app_name": "myapp",
            "environment": "staging",
            "image": "myapp:latest",
            "replicas": 2
        }
        
        # 앱명 추출 (더 유연한 패턴)
        import re
        app_match = re.search(r'([a-zA-Z0-9_-]+)\s*(?:을|를|을/를)', prompt)
        if app_match:
            entities["app_name"] = app_match.group(1)
        elif "myapp" in prompt_lower:
            entities["app_name"] = "myapp"
        elif "testapp" in prompt_lower:
            entities["app_name"] = "testapp"
        
        # 환경 추출
        if any(word in prompt_lower for word in ["production", "프로덕션", "운영"]):
            entities["environment"] = "production"
        elif any(word in prompt_lower for word in ["staging", "스테이징", "개발"]):
            entities["environment"] = "staging"
        
        # 이미지 추출 (간단한 패턴)
        image_match = re.search(r'([a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+)', prompt)
        if image_match:
            entities["image"] = image_match.group(1)
        
        # 레플리카 수 추출
        replicas_match = re.search(r'(\d+)\s*(?:개|replica)', prompt)
        if replicas_match:
            entities["replicas"] = int(replicas_match.group(1))
        
        return entities

    def _extract_rollback_entities(self, prompt: str) -> Dict[str, Any]:
        """롤백 명령에서 엔티티를 추출합니다."""
        entities = {
            "app_name": "myapp",
            "environment": "staging"
        }
        
        prompt_lower = prompt.lower()
        
        # 앱명 추출
        import re
        app_match = re.search(r'([a-zA-Z0-9_-]+)\s*(?:을|를|을/를)', prompt)
        if app_match:
            entities["app_name"] = app_match.group(1)
        elif "myapp" in prompt_lower:
            entities["app_name"] = "myapp"
        elif "testapp" in prompt_lower:
            entities["app_name"] = "testapp"
        
        if any(word in prompt_lower for word in ["production", "프로덕션", "운영"]):
            entities["environment"] = "production"
        elif any(word in prompt_lower for word in ["staging", "스테이징", "개발"]):
            entities["environment"] = "staging"
        
        return entities

    def _extract_monitor_entities(self, prompt: str) -> Dict[str, Any]:
        """모니터링 명령에서 엔티티를 추출합니다."""
        entities = {
            "query": "up",
            "app_name": "myapp"
        }
        
        prompt_lower = prompt.lower()
        
        # 앱명 추출
        import re
        app_match = re.search(r'([a-zA-Z0-9_-]+)\s*(?:상태|모니터|monitor)', prompt)
        if app_match:
            entities["app_name"] = app_match.group(1)
        elif "myapp" in prompt_lower:
            entities["app_name"] = "myapp"
        elif "testapp" in prompt_lower:
            entities["app_name"] = "testapp"
        
        return entities

    async def _handle_deploy_intent_advanced(self, prompt: str, interpreted: Dict[str, Any], advanced_result: Dict[str, Any]) -> Dict[str, Any]:
        """고급 배포 의도 처리"""
        try:
            # 고급 해석 결과에서 엔티티 추출
            entities = interpreted.get("entities", {})
            
            # 고급 NLP 결과의 제안사항이 있으면 적용
            suggestions = advanced_result.get("suggestions", [])
            for suggestion in suggestions:
                if suggestion["type"] == "parameter_correction" and suggestion["confidence"] > 0.8:
                    # 제안된 수정사항 적용
                    if "app_name" in suggestion["suggested_text"]:
                        entities["app_name"] = suggestion["suggested_text"]["app_name"]
                    if "environment" in suggestion["suggested_text"]:
                        entities["environment"] = suggestion["suggested_text"]["environment"]
            
            # MCP 도구 호출
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="deploy_application",
                arguments=entities
            )
            
            return {
                "intent": "deploy",
                "entities": entities,
                "result": result,
                "message": f"고급 배포 명령이 성공적으로 처리되었습니다: {entities.get('app_name', '알 수 없음')}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_deploy",
                },
            }
        except Exception as e:
            return {
                "intent": "deploy",
                "entities": interpreted.get("entities", {}),
                "error": str(e),
                "message": f"고급 배포 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_deploy_error",
                },
            }
    
    async def _handle_rollback_intent_advanced(self, prompt: str, interpreted: Dict[str, Any], advanced_result: Dict[str, Any]) -> Dict[str, Any]:
        """고급 롤백 의도 처리"""
        try:
            # 고급 해석 결과에서 엔티티 추출
            entities = interpreted.get("entities", {})
            
            # 고급 NLP 결과의 제안사항이 있으면 적용
            suggestions = advanced_result.get("suggestions", [])
            for suggestion in suggestions:
                if suggestion["type"] == "parameter_correction" and suggestion["confidence"] > 0.8:
                    if "app_name" in suggestion["suggested_text"]:
                        entities["app_name"] = suggestion["suggested_text"]["app_name"]
                    if "environment" in suggestion["suggested_text"]:
                        entities["environment"] = suggestion["suggested_text"]["environment"]
            
            # MCP 도구 호출
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="rollback_deployment",
                arguments=entities
            )
            
            return {
                "intent": "rollback",
                "entities": entities,
                "result": result,
                "message": f"고급 롤백 명령이 성공적으로 처리되었습니다: {entities.get('app_name', '알 수 없음')}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_rollback",
                },
            }
        except Exception as e:
            return {
                "intent": "rollback",
                "entities": interpreted.get("entities", {}),
                "error": str(e),
                "message": f"고급 롤백 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_rollback_error",
                },
            }
    
    async def _handle_scale_intent_advanced(self, prompt: str, interpreted: Dict[str, Any], advanced_result: Dict[str, Any]) -> Dict[str, Any]:
        """고급 스케일링 의도 처리"""
        try:
            # 고급 해석 결과에서 엔티티 추출
            entities = interpreted.get("entities", {})
            
            # 스케일링 관련 파라미터 설정
            if "replicas" not in entities:
                entities["replicas"] = 2  # 기본값
            
            # 고급 NLP 결과의 제안사항이 있으면 적용
            suggestions = advanced_result.get("suggestions", [])
            for suggestion in suggestions:
                if suggestion["type"] == "parameter_correction" and suggestion["confidence"] > 0.8:
                    if "app_name" in suggestion["suggested_text"]:
                        entities["app_name"] = suggestion["suggested_text"]["app_name"]
                    if "replicas" in suggestion["suggested_text"]:
                        entities["replicas"] = suggestion["suggested_text"]["replicas"]
            
            # MCP 도구 호출 (스케일링은 배포 도구를 재사용)
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="deploy_application",
                arguments=entities
            )
            
            return {
                "intent": "scale",
                "entities": entities,
                "result": result,
                "message": f"고급 스케일링 명령이 성공적으로 처리되었습니다: {entities.get('app_name', '알 수 없음')} -> {entities.get('replicas', 2)}개",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_scale",
                },
            }
        except Exception as e:
            return {
                "intent": "scale",
                "entities": interpreted.get("entities", {}),
                "error": str(e),
                "message": f"고급 스케일링 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_scale_error",
                },
            }
    
    async def _handle_monitor_intent_advanced(self, prompt: str, interpreted: Dict[str, Any], advanced_result: Dict[str, Any]) -> Dict[str, Any]:
        """고급 모니터링 의도 처리"""
        try:
            # 고급 해석 결과에서 엔티티 추출
            entities = interpreted.get("entities", {})
            
            # 고급 NLP 결과의 제안사항이 있으면 적용
            suggestions = advanced_result.get("suggestions", [])
            for suggestion in suggestions:
                if suggestion["type"] == "parameter_correction" and suggestion["confidence"] > 0.8:
                    if "app_name" in suggestion["suggested_text"]:
                        entities["app_name"] = suggestion["suggested_text"]["app_name"]
                    if "query" in suggestion["suggested_text"]:
                        entities["query"] = suggestion["suggested_text"]["query"]
            
            # MCP 도구 호출
            result = await mcp_registry.call_tool(
                provider="k-le-paas",
                tool="query_metrics",
                arguments=entities
            )
            
            return {
                "intent": "monitor",
                "entities": entities,
                "result": result,
                "message": f"고급 모니터링 명령이 성공적으로 처리되었습니다",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_monitor",
                },
            }
        except Exception as e:
            return {
                "intent": "monitor",
                "entities": interpreted.get("entities", {}),
                "error": str(e),
                "message": f"고급 모니터링 명령 처리 중 오류가 발생했습니다: {str(e)}",
                "advanced_nlp": advanced_result,
                "llm": {
                    "provider": "gemini_advanced",
                    "model": advanced_result["best_model"],
                    "confidence": advanced_result["confidence"],
                    "quality": advanced_result["quality"],
                    "mode": "advanced_monitor_error",
                },
            }


