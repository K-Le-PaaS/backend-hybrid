import os
import time
import json
import re
from typing import Any, Dict, List, Optional

import httpx

from .interfaces import LLMClient
from ..core.config import get_settings


class GeminiClient(LLMClient):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def interpret(self, prompt: str, user_id: str = "default", project_name: str = "default") -> Dict[str, Any]:
        """자연어 명령을 해석하고 적절한 액션을 반환합니다."""
        try:
            # Gemini API를 직접 호출하여 명령 해석
            gemini_response = await self._call_gemini_api(prompt)
            
            # Gemini 응답에서 command와 parameters 추출
            command_data = self._parse_gemini_response(gemini_response)
            
            # 명령어에 따른 처리
            if command_data["command"] == "deploy":
                return await self._handle_deploy_command(command_data, prompt)
            elif command_data["command"] == "rollback":
                return await self._handle_rollback_command(command_data, prompt)
            elif command_data["command"] == "scale":
                return await self._handle_scale_command(command_data, prompt)
            elif command_data["command"] == "status":
                return await self._handle_status_command(command_data, prompt)
            elif command_data["command"] == "logs":
                return await self._handle_logs_command(command_data, prompt)
            elif command_data["command"] == "endpoint":
                return await self._handle_endpoint_command(command_data, prompt)
            elif command_data["command"] == "restart":
                return await self._handle_restart_command(command_data, prompt)
            else:
                return {
                    "intent": "unknown",
                    "entities": command_data,
                    "message": f"지원하지 않는 명령입니다: {command_data.get('command', 'unknown')}",
                    "llm": {
                        "provider": "gemini",
                        "model": self.settings.gemini_model,
                        "mode": "direct_api",
                    },
                }
        except Exception as e:
            return {
                "intent": "error",
                "entities": {},
                "error": str(e),
                "message": f"명령 해석 중 오류가 발생했습니다: {str(e)}",
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "mode": "error",
                },
            }

    async def _call_gemini_api(self, prompt: str) -> str:
        """Gemini API를 직접 호출하여 응답을 받습니다."""
        import httpx
        
        # Gemini API 설정
        api_key = os.getenv("KLEPAAS_GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API 키가 설정되지 않았습니다")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        
        # MVP 시스템 프롬프트
        system_prompt = """SYSTEM PROMPT:
당신은 쿠버네티스 전문가 AI 어시스턴트입니다. 당신의 역할은 사용자의 자연어 명령을 분석하여, 미리 정의된 구조화된 JSON 형식으로 변환하는 것입니다. 당신의 답변에는 어떠한 추가 설명이나 대화도 포함되어서는 안 되며, 오직 JSON 객체만을 반환해야 합니다.

명령어 및 반환 형식:

1. 상태 확인 (command: "status")
설명: 배포된 애플리케이션의 현재 상태를 확인하는 명령입니다.
사용자 입력 예시: "내 앱 상태 보여줘", "chat-app 상태 어때?", "서버 목록 확인"
필수 JSON 형식: { "command": "status", "parameters": { "appName": "<추출된_앱이름_없으면_null>" } }

2. 로그 조회 (command: "logs")
설명: 배포된 애플리케이션의 로그를 조회하는 명령입니다.
사용자 입력 예시: "최신 로그 100줄 보여줘", "로그 확인", "에러 로그 찾아줘"
필수 JSON 형식: { "command": "logs", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "lines": <추출된_줄_수_없으면_30> } }

3. 엔드포인트/URL 확인 (command: "endpoint")
설명: 배포된 서비스의 접속 주소를 확인하는 명령입니다.
사용자 입력 예시: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?", "내 앱 주소 알려줘", "앱 URL 확인", "접속 주소 보여줘", "서비스 주소 알려줘", "엔드포인트 확인", "외부 접속 주소", "인그레스 URL", "로드밸런서 주소"
필수 JSON 형식: { "command": "endpoint", "parameters": { "appName": "<추출된_앱이름_없으면_null>" } }

4. 재시작 (command: "restart")
설명: 애플리케이션을 재시작하는 명령입니다.
사용자 입력 예시: "앱 재시작해줘", "chat-app 껐다 켜줘"
필수 JSON 형식: { "command": "restart", "parameters": { "appName": "<추출된_앱이름_없으면_null>" } }

5. 스케일링 (command: "scale")
설명: 애플리케이션의 서버(파드) 개수를 조절하는 명령입니다.
사용자 입력 예시: "서버 3대로 늘려줘", "chat-app 스케일 아웃", "서버 1개로 줄여"
필수 JSON 형식: { "command": "scale", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "replicas": <추출된_숫자> } }

6. 이미지 롤백 (command: "rollback")
설명: 애플리케이션을 이전 버전으로 되돌리는 명령입니다.
사용자 입력 예시: "v1.1 버전으로 롤백해줘", "이전 배포로 되돌려"
필수 JSON 형식: { "command": "rollback", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "version": "<추출된_버전_태그>" } }

7. 배포 (command: "deploy")
설명: 사용자의 최신 코드를 빌드하고 클러스터에 배포합니다.
사용자 입력 예시: "배포해줘", "최신 코드로 업데이트해줘"
필수 JSON 형식: { "command": "deploy", "parameters": { "appName": "<추출된_앱이름>" } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 7가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
- appName이 명시되지 않은 경우, 컨텍스트상 기본 앱이 있다면 그 이름을 사용하거나 null을 반환합니다.
- 오직 JSON 객체만 반환하며, 추가 설명이나 대화는 포함하지 않습니다."""
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{system_prompt}\n\n사용자 명령: {prompt}"
                }]
            }]
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            
            # Gemini 응답에서 텍스트 추출
            if "candidates" in result and len(result["candidates"]) > 0:
                content = result["candidates"][0]["content"]["parts"][0]["text"]
                return content
            else:
                raise ValueError("Gemini API에서 유효한 응답을 받지 못했습니다")

    def _parse_gemini_response(self, response: str) -> Dict[str, Any]:
        """Gemini 응답을 파싱하여 command와 parameters를 추출합니다."""
        import json
        import re
        
        # JSON 코드 블록에서 JSON 추출
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 코드 블록이 없으면 전체 텍스트에서 JSON 찾기
            json_match = re.search(r'(\{.*?\})', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                return {"command": "unknown", "parameters": {"query": response}}
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {"command": "unknown", "parameters": {"query": response}}

    async def _process_response_with_gemini(self, command: str, raw_response: Dict[str, Any], original_prompt: str) -> str:
        """Gemini를 사용하여 백엔드 응답을 사용자 친화적 메시지로 가공"""
        try:
            # Gemini에게 응답 가공 요청
            processing_prompt = f"""
백엔드 서버에서 받은 응답을 사용자 친화적인 JSON 메시지로 변환해주세요.

사용자 원본 질문: {original_prompt}
명령어 타입: {command}
백엔드 응답: {raw_response}

다음 JSON 형식으로 응답해주세요:
{{
  "user_message": "이모지 + 사용자 친화적 메시지",
  "status": "success/error/warning",
  "summary": "핵심 정보 요약",
  "details": "상세 정보 (선택사항)"
}}

규칙:
1. user_message는 한국어로 자연스럽게
2. 이모지 사용으로 가독성 향상
3. 기술적 세부사항은 간단히 설명
4. 오류가 있다면 친근하게 안내
"""
            
            content = await self._call_gemini_api(processing_prompt)
            
            # JSON 파싱
            try:
                # JSON 코드 블록에서 JSON 추출
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # 코드 블록이 없으면 전체 텍스트에서 JSON 찾기
                    json_match = re.search(r'(\{.*?\})', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        return f"✅ {command} 명령이 처리되었습니다."
                
                # JSON 파싱
                parsed_response = json.loads(json_str)
                return parsed_response.get("user_message", f"✅ {command} 명령이 처리되었습니다.")
                
            except json.JSONDecodeError:
                return f"✅ {command} 명령이 처리되었습니다."
            
        except Exception as e:
            # Gemini 가공 실패 시 기본 메시지
            return f"✅ {command} 명령이 처리되었습니다."

    # 명령어별 처리 메서드들
    async def _handle_deploy_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """배포 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/api/v1/commands/execute",
                json={
                    "command": "deploy",
                    "app_name": entities.get('appName', '')
                }
            )
            backend_result = response.json()
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="deploy",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "deploy",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_rollback_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """롤백 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "rollback",
                        "app_name": entities.get('appName', ''),
                        "version": entities.get('version', '')
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="rollback",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "rollback",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_scale_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """스케일링 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "scale",
                        "app_name": entities.get('appName', ''),
                        "replicas": entities.get('replicas', 1)
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="scale",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "scale",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_status_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """상태 확인 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "status",
                        "app_name": entities.get('appName', '')
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="status",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "status",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_logs_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """로그 조회 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "logs",
                        "app_name": entities.get('appName', ''),
                        "lines": entities.get('lines', 30)
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="logs",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "logs",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_endpoint_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """엔드포인트 조회 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "endpoint",
                        "app_name": entities.get('appName', '')
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="endpoint",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "endpoint",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }

    async def _handle_restart_command(self, command_data: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """재시작 명령 처리"""
        entities = command_data.get("parameters", {})
        
        # 우리 백엔드 다른 파트로 POST 호출
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/commands/execute",
                    json={
                        "command": "restart",
                        "app_name": entities.get('appName', '')
                    }
                )
                backend_result = response.json()
        except Exception as e:
            # 백엔드 호출 실패 시 에러 응답
            backend_result = {
                "error": "Backend service unavailable",
                "message": f"백엔드 서비스 호출 실패: {str(e)}"
            }
        
        # Gemini로 응답 가공
        processed_message = await self._process_response_with_gemini(
            command="restart",
            raw_response=backend_result,
            original_prompt=prompt
        )
        
        return {
            "intent": "restart",
            "entities": entities,
            "result": backend_result,
            "message": processed_message,
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "response_processing",
            },
        }