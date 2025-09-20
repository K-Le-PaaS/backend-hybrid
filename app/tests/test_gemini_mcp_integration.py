"""
Gemini MCP 통합 테스트

자연어 명령이 Gemini를 통해 MCP 도구로 올바르게 전달되는지 테스트합니다.
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.llm.gemini import GeminiClient


class TestGeminiMCPIntegration:
    """Gemini MCP 통합 테스트 클래스"""
    
    def setup_method(self):
        """테스트 설정"""
        self.client = GeminiClient()

    @pytest.mark.asyncio
    async def test_deploy_intent_with_mcp(self):
        """배포 의도가 MCP 도구로 전달되는지 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "action": "deploy",
                "app_name": "myapp",
                "environment": "staging",
                "image": "myapp:latest",
                "replicas": 2,
                "status": "success"
            })
            
            result = await self.client.interpret("myapp을 staging에 배포해줘")
            
            assert result["intent"] == "deploy"
            assert result["entities"]["app_name"] == "myapp"
            assert result["entities"]["environment"] == "staging"
            assert "성공적으로 처리되었습니다" in result["message"]
            assert result["result"]["status"] == "success"
            
            # MCP 도구가 호출되었는지 확인
            mock_registry.call_tool.assert_called_once_with(
                provider="k-le-paas",
                tool="deploy_application",
                arguments={
                    "app_name": "myapp",
                    "environment": "staging",
                    "image": "myapp:latest",
                    "replicas": 2
                }
            )

    @pytest.mark.asyncio
    async def test_rollback_intent_with_mcp(self):
        """롤백 의도가 MCP 도구로 전달되는지 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "action": "rollback",
                "app_name": "myapp",
                "environment": "staging",
                "status": "success"
            })
            
            result = await self.client.interpret("myapp을 이전 버전으로 롤백해줘")
            
            assert result["intent"] == "rollback"
            assert result["entities"]["app_name"] == "myapp"
            assert "성공적으로 처리되었습니다" in result["message"]
            
            # MCP 도구가 호출되었는지 확인
            mock_registry.call_tool.assert_called_once_with(
                provider="k-le-paas",
                tool="rollback_deployment",
                arguments={
                    "app_name": "myapp",
                    "environment": "staging"
                }
            )

    @pytest.mark.asyncio
    async def test_monitor_intent_with_mcp(self):
        """모니터링 의도가 MCP 도구로 전달되는지 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "query": "up",
                "app_name": "myapp",
                "result": "healthy"
            })
            
            result = await self.client.interpret("myapp 상태를 확인해줘")
            
            assert result["intent"] == "monitor"
            assert result["entities"]["app_name"] == "myapp"
            assert "성공적으로 처리되었습니다" in result["message"]
            
            # MCP 도구가 호출되었는지 확인
            mock_registry.call_tool.assert_called_once_with(
                provider="k-le-paas",
                tool="query_metrics",
                arguments={
                    "query": "up",
                    "app_name": "myapp"
                }
            )

    @pytest.mark.asyncio
    async def test_unknown_intent(self):
        """알 수 없는 의도 처리 테스트"""
        result = await self.client.interpret("안녕하세요")
        
        assert result["intent"] == "unknown"
        assert "지원하지 않는 명령입니다" in result["message"]

    @pytest.mark.asyncio
    async def test_mcp_error_handling(self):
        """MCP 도구 호출 에러 처리 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(side_effect=Exception("MCP Error"))
            
            result = await self.client.interpret("myapp을 staging에 배포해줘")
            
            assert result["intent"] == "deploy"
            assert "오류가 발생했습니다" in result["message"]
            assert "MCP Error" in result["error"]

    def test_intent_classification(self):
        """의도 분류 테스트"""
        test_cases = [
            ("myapp을 배포해줘", "deploy"),
            ("deploy myapp", "deploy"),
            ("myapp을 롤백해줘", "rollback"),
            ("rollback myapp", "rollback"),
            ("myapp 상태 확인", "monitor"),
            ("monitor myapp", "monitor"),
            ("안녕하세요", "unknown"),
        ]
        
        for prompt, expected_intent in test_cases:
            intent = self.client._classify_intent(prompt)
            assert intent == expected_intent, f"Failed for prompt: {prompt}"

    def test_deploy_entity_extraction(self):
        """배포 엔티티 추출 테스트"""
        test_cases = [
            ("myapp을 staging에 배포", {
                "app_name": "myapp",
                "environment": "staging",
                "image": "myapp:latest",
                "replicas": 2
            }),
            ("testapp을 production에 myapp:v1.0으로 3개 배포", {
                "app_name": "testapp",
                "environment": "production",
                "image": "myapp:v1.0",
                "replicas": 3
            }),
        ]
        
        for prompt, expected_entities in test_cases:
            entities = self.client._extract_deploy_entities(prompt)
            for key, expected_value in expected_entities.items():
                assert entities[key] == expected_value, f"Failed for {key} in prompt: {prompt}"

    def test_rollback_entity_extraction(self):
        """롤백 엔티티 추출 테스트"""
        test_cases = [
            ("myapp을 롤백", {
                "app_name": "myapp",
                "environment": "staging"
            }),
            ("testapp을 production에서 롤백", {
                "app_name": "testapp",
                "environment": "production"
            }),
        ]
        
        for prompt, expected_entities in test_cases:
            entities = self.client._extract_rollback_entities(prompt)
            for key, expected_value in expected_entities.items():
                assert entities[key] == expected_value, f"Failed for {key} in prompt: {prompt}"

    def test_monitor_entity_extraction(self):
        """모니터링 엔티티 추출 테스트"""
        test_cases = [
            ("myapp 상태 확인", {
                "query": "up",
                "app_name": "myapp"
            }),
            ("testapp 모니터링", {
                "query": "up",
                "app_name": "testapp"
            }),
        ]
        
        for prompt, expected_entities in test_cases:
            entities = self.client._extract_monitor_entities(prompt)
            for key, expected_value in expected_entities.items():
                assert entities[key] == expected_value, f"Failed for {key} in prompt: {prompt}"

    @pytest.mark.asyncio
    async def test_production_deploy(self):
        """프로덕션 배포 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={
                "action": "deploy",
                "app_name": "myapp",
                "environment": "production",
                "status": "success"
            })
            
            result = await self.client.interpret("myapp을 production에 배포해줘")
            
            assert result["intent"] == "deploy"
            assert result["entities"]["environment"] == "production"
            
            # MCP 도구 호출 확인
            call_args = mock_registry.call_tool.call_args
            assert call_args[1]["arguments"]["environment"] == "production"

    @pytest.mark.asyncio
    async def test_image_and_replicas_extraction(self):
        """이미지와 레플리카 수 추출 테스트"""
        with patch('app.llm.gemini.mcp_registry') as mock_registry:
            mock_registry.call_tool = AsyncMock(return_value={"status": "success"})
            
            result = await self.client.interpret("myapp을 myapp:v2.0 이미지로 5개 배포해줘")
            
            assert result["intent"] == "deploy"
            assert result["entities"]["image"] == "myapp:v2.0"
            assert result["entities"]["replicas"] == 5
            
            # MCP 도구 호출 확인
            call_args = mock_registry.call_tool.call_args
            assert call_args[1]["arguments"]["image"] == "myapp:v2.0"
            assert call_args[1]["arguments"]["replicas"] == 5

