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
        """자연어 명령을 해석하고 구조화된 데이터를 반환합니다."""
        try:
            # Gemini API를 직접 호출하여 명령 해석
            gemini_response = await self._call_gemini_api(prompt)
            
            # Gemini 응답에서 command와 parameters 추출
            command_data = self._parse_gemini_response(gemini_response)
            
            # 파라미터 파싱 및 명령어 결정
            parameters = command_data.get("parameters", {})
            command = command_data.get("command", "unknown")

            # 명령어에 따른 entities 구성 (해당 명령에 필요한 필드만 포함)
            entities: Dict[str, Any] = {}

            # app_name 포함이 필요한 명령어들
            if command in ("status", "endpoint", "restart", "scale", "rollback", "deploy", "logs"):
                if parameters.get("appName") is not None:
                    entities["app_name"] = parameters.get("appName")

            # namespace 기본값 포함이 필요한 명령어들
            if command in ("status", "endpoint", "restart", "overview", "list_pods", "list_apps", "logs"):
                entities["namespace"] = parameters.get("namespace", "default")

            # 스케일링 복제수
            if command == "scale":
                if parameters.get("replicas") is not None:
                    entities["replicas"] = parameters.get("replicas")

            # 롤백 버전
            if command == "rollback":
                if parameters.get("version") is not None:
                    entities["version"] = parameters.get("version")

            # 로그 관련 옵션: lines, previous
            if command == "logs":
                raw_lines = parameters.get("lines", 30)
                try:
                    coerced_lines = int(raw_lines)
                except (TypeError, ValueError):
                    coerced_lines = 30
                if coerced_lines < 1:
                    coerced_lines = 1
                if coerced_lines > 100:
                    coerced_lines = 100
                entities["lines"] = coerced_lines
                entities["previous"] = bool(parameters.get("previous", False))

            # list_deployments / list_services / list_ingresses / list_namespaces 는 파라미터 없음
            
            # 명령어에 따른 기본 메시지 생성
            messages = {
                "deploy": "배포 명령을 해석했습니다.",
                "rollback": "롤백 명령을 해석했습니다.",
                "scale": "스케일링 명령을 해석했습니다.",
                "status": "상태 확인 명령을 해석했습니다.",
                "logs": "로그 조회 명령을 해석했습니다.",
                "endpoint": "엔드포인트 조회 명령을 해석했습니다.",
                "restart": "재시작 명령을 해석했습니다.",
                "list_pods": "파드 목록 조회 명령을 해석했습니다.",
                "list_apps": "네임스페이스 앱 목록 조회 명령을 해석했습니다.",
                "list_deployments": "전체 Deployment 조회 명령을 해석했습니다.",
                "list_services": "전체 Service 조회 명령을 해석했습니다.",
                "list_ingresses": "전체 Ingress/도메인 조회 명령을 해석했습니다.",
                "list_namespaces": "네임스페이스 목록 조회 명령을 해석했습니다.",
                "overview": "통합 대시보드 조회 명령을 해석했습니다.",
                "unknown": "알 수 없는 명령입니다."
            }
            
            return {
                "intent": command,
                "entities": entities,
                "message": messages.get(command, "명령을 해석했습니다."),
                "llm": {
                    "provider": "gemini",
                    "model": self.settings.gemini_model,
                    "mode": "interpretation_only",
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
        # Settings에서 API 키 가져오기 (.env 파일 지원)
        api_key = self.settings.gemini_api_key or os.getenv("KLEPAAS_GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API 키가 설정되지 않았습니다. .env 파일 또는 환경변수에 KLEPAAS_GEMINI_API_KEY를 설정하세요.")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        
        # MVP 시스템 프롬프트
        system_prompt = """SYSTEM PROMPT:
당신은 쿠버네티스 전문가 AI 어시스턴트입니다. 당신의 역할은 사용자의 자연어 명령을 분석하여, 미리 정의된 구조화된 JSON 형식으로 변환하는 것입니다. 당신의 답변에는 어떠한 추가 설명이나 대화도 포함되어서는 안 되며, 오직 JSON 객체만을 반환해야 합니다.

명령어 및 반환 형식:

1. 상태 확인 (command: "status")
설명: 배포된 애플리케이션의 현재 상태를 확인하는 명령입니다.
사용자 입력 예시: "내 앱 상태 보여줘", "chat-app 상태 어때?", "서버 목록 확인"
필수 JSON 형식: { "command": "status", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

2. 로그 조회 (command: "logs")
설명: 배포된 애플리케이션의 로그를 조회하는 명령입니다.
사용자 입력 예시: "최신 로그 100줄 보여줘", "로그 확인", "에러 로그 찾아줘", "이전 로그 확인해줘", "test 네임스페이스 nginx 로그 보여줘"
제한사항: 로그 줄 수는 최대 100줄까지 조회 가능합니다.
네임스페이스 추출 규칙: "test 네임스페이스", "default 네임스페이스", "kube-system에서" 등의 표현에서 네임스페이스명을 정확히 추출하세요.
필수 JSON 형식: { "command": "logs", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "lines": <추출된_줄_수_없으면_30_최대_100>, "previous": <이전_파드_로그_요청시_true>, "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

3. 엔드포인트/URL 확인 (command: "endpoint")
설명: 배포된 서비스의 접속 주소를 확인하는 명령입니다.
기능: Service 확인 → LoadBalancer/NodePort/ClusterIP 엔드포인트 제공
사용자 입력 예시: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?", "내 앱 주소 알려줘", "앱 URL 확인", "접속 주소 보여줘", "서비스 주소 알려줘", "엔드포인트 확인", "외부 접속 주소", "로드밸런서 주소"
필수 JSON 형식: { "command": "endpoint", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

4. 재시작 (command: "restart")
설명: 애플리케이션을 재시작하는 명령입니다.
기능: kubectl rollout restart deployment로 Pod 재시작
사용자 입력 예시: "앱 재시작해줘", "chat-app 껐다 켜줘", "nginx-test 재시작", "서비스 재시작해줘"
필수 JSON 형식: { "command": "restart", "parameters": { "appName": "<추출된_앱이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

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

8. 통합 대시보드 조회 (command: "overview")
설명: 특정 네임스페이스의 모든 리소스를 한번에 조회하는 명령입니다 (Deployment, Pod, Service, Ingress).
사용자 입력 예시: "전체 상황 보여줘", "대시보드 확인", "모든 리소스 상태", "네임스페이스 전체 현황", "클러스터 상태 확인"
필수 JSON 형식: { "command": "overview", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

9. 파드 목록 조회 (command: "list_pods")
설명: 현재 실행 중인 모든 파드의 목록을 조회하는 명령입니다.
사용자 입력 예시: "모든 파드 조회해줘", "파드 목록 보여줘", "실행 중인 파드들 확인"
필수 JSON 형식: { "command": "list_pods", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

10. 전체 Deployment 조회 (command: "list_deployments")
설명: 모든 네임스페이스의 Deployment 목록을 조회하는 명령입니다.
사용자 입력 예시: "모든 Deployment 조회해줘", "전체 앱 목록 보여줘", "모든 배포 확인"
필수 JSON 형식: { "command": "list_deployments", "parameters": {} }

11. 전체 Service 조회 (command: "list_services")
설명: 모든 네임스페이스의 Service 목록을 조회하는 명령입니다.
사용자 입력 예시: "모든 Service 조회해줘", "전체 서비스 목록 보여줘", "모든 서비스 확인"
필수 JSON 형식: { "command": "list_services", "parameters": {} }

12. 전체 Ingress/도메인 조회 (command: "list_ingresses")
설명: 모든 네임스페이스의 Ingress와 도메인 목록을 조회하는 명령입니다.
사용자 입력 예시: "모든 도메인 조회해줘", "전체 Ingress 목록 보여줘", "모든 접속 주소 확인"
필수 JSON 형식: { "command": "list_ingresses", "parameters": {} }

13. 네임스페이스 목록 조회 (command: "list_namespaces")
설명: 클러스터의 모든 네임스페이스 목록을 조회하는 명령입니다.
사용자 입력 예시: "모든 네임스페이스 조회해줘", "네임스페이스 목록 보여줘", "전체 네임스페이스 확인"
필수 JSON 형식: { "command": "list_namespaces", "parameters": {} }

14. 네임스페이스 앱 목록 조회 (command: "list_apps")
설명: 특정 네임스페이스의 모든 애플리케이션(Deployment) 목록을 조회하는 명령입니다.
사용자 입력 예시: "test 네임스페이스 앱 목록 보여줘", "default 네임스페이스 모든 앱 확인", "특정 네임스페이스 앱 목록 조회"
필수 JSON 형식: { "command": "list_apps", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 14가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
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

    # 백엔드 호출 및 응답 가공 메서드 제거됨
    # 이제 gemini.py는 자연어 해석만 담당

    # 모든 백엔드 호출 메서드 제거됨
    # gemini.py는 이제 자연어 해석만 담당