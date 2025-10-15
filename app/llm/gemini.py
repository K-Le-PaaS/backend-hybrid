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

            # 리소스 타입별 파라미터 처리
            if command in ("status", "logs", "restart"):
                # Pod 관련 명령어
                if parameters.get("podName") is not None:
                    entities["pod_name"] = parameters.get("podName")
            elif command in ("scale", "rollback", "deploy", "get_deployment"):
                # Deployment 관련 명령어
                if parameters.get("deploymentName") is not None:
                    entities["deployment_name"] = parameters.get("deploymentName")
            elif command in ("endpoint", "get_service"):
                # Service 관련 명령어
                if parameters.get("serviceName") is not None:
                    entities["service_name"] = parameters.get("serviceName")

            # namespace 기본값 포함이 필요한 명령어들
            if command in ("status", "endpoint", "restart", "overview", "list_pods", "list_apps", "logs", "get_service", "get_deployment"):
                entities["namespace"] = parameters.get("namespace", "default")

            # 스케일링 복제수
            if command == "scale":
                raw_replicas = parameters.get("replicas", 1)
                try:
                    coerced_replicas = int(raw_replicas)
                except (TypeError, ValueError):
                    coerced_replicas = 1
                if coerced_replicas < 1:
                    coerced_replicas = 1
                if coerced_replicas > 100:  # 최대 100개로 제한
                    coerced_replicas = 100
                entities["replicas"] = coerced_replicas

            # 롤백 버전
            if command == "rollback":
                raw_version = parameters.get("version", "")
                if raw_version and isinstance(raw_version, str):
                    entities["version"] = raw_version.strip()
                else:
                    entities["version"] = ""

            # 로그 관련 옵션: lines, previous
            if command == "logs":
                raw_lines = parameters.get("lines", 30)
                try:
                    coerced_lines = int(raw_lines)
                except (TypeError, ValueError):
                    coerced_lines = 30
                if coerced_lines < 1:
                    coerced_lines = 1
                if coerced_lines >= 100:
                    coerced_lines = 100
                entities["lines"] = coerced_lines
                
                # 이전 파드 로그 여부
                raw_previous = parameters.get("previous", False)
                if isinstance(raw_previous, bool):
                    entities["previous"] = raw_previous
                elif isinstance(raw_previous, str):
                    entities["previous"] = raw_previous.lower() in ("true", "1", "yes", "on")
                else:
                    entities["previous"] = False

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
                "get_service": "Service 상세 정보 조회 명령을 해석했습니다.",
                "get_deployment": "Deployment 상세 정보 조회 명령을 해석했습니다.",
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
당신은 쿠버네티스 전문가 AI 어시스턴트입니다. 당신의 역할은 사용자의 자연어 명령을 분석하여, 미리 정의된 구조화된 JSON 형식으로 변환하는 것입니다. 

중요한 지침:
1. 한국어의 다양한 표현 방식과 뉘앙스를 이해하세요 (존댓말, 반말, 줄임말, 비격식 표현 등)
2. 동의어와 유사 표현을 모두 인식하세요 (예: "상태", "현황", "상황", "어때", "어떤가" 등)
3. 숫자 표현을 정확히 파악하세요 (예: "3개", "3대", "3개로", "3개까지", "3개씩" 등)
4. 리소스 타입을 명확히 구분하세요 (Pod, Deployment, Service)
5. 당신의 답변에는 어떠한 추가 설명이나 대화도 포함되어서는 안 되며, 오직 JSON 객체만을 반환해야 합니다.

명령어 및 반환 형식:

1. 상태 확인 (command: "status")
설명: 배포된 애플리케이션의 현재 상태를 확인하는 명령입니다.
중요: "app", "앱"이라는 호칭은 Pod를 의미합니다.
사용자 입력 예시: 
- 기본 표현: "내 앱 상태 보여줘", "chat-app 상태 어때?", "서버 목록 확인"
- 자연스러운 표현: "nginx-pod 상태 확인", "frontend 앱 상태는?", "백엔드 서버 상태 보여줘"
- 다양한 뉘앙스: "nginx 잘 돌아가고 있어?", "frontend 앱 어떻게 되고 있어?", "서버들 다 정상인가?", "앱 현황 알려줘", "상황 파악해줘", "서버 상태 체크", "모든 게 잘 돌아가고 있나?", "앱이 정상 작동하고 있나?"
- App 호칭 예시: "k-le-paas-test01 app 상태", "my-app 상태 확인", "앱 상태 보여줘"
필수 JSON 형식: { "command": "status", "parameters": { "podName": "<추출된_파드이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

2. 로그 조회 (command: "logs")
설명: 배포된 애플리케이션의 로그를 조회하는 명령입니다.
중요: "app", "앱"이라는 호칭은 Pod를 의미합니다.
사용자 입력 예시:
- 기본 표현: "최신 로그 100줄 보여줘", "로그 확인", "에러 로그 찾아줘", "이전 로그 확인해줘"
- 자연스러운 표현: "test 네임스페이스 nginx 로그 보여줘", "frontend 앱 로그 확인해줘"
- 다양한 뉘앙스: "로그 좀 봐줘", "에러 메시지 확인", "앱이 왜 안 되지? 로그 봐줘", "최근 로그 50줄만", "로그 파일 보여줘", "어떤 에러가 나고 있어?", "앱 로그 체크", "문제 원인 찾아줘", "로그 분석해줘", "디버깅 로그 확인"
- App 호칭 예시: "k-le-paas-test01 app 로그", "my-app 로그 확인", "앱 로그 보여줘"
제한사항: 로그 줄 수는 최대 100줄까지 조회 가능합니다.
네임스페이스 추출 규칙: "test 네임스페이스", "default 네임스페이스", "kube-system에서" 등의 표현에서 네임스페이스명을 정확히 추출하세요.
필수 JSON 형식: { "command": "logs", "parameters": { "podName": "<추출된_파드이름_없으면_null>", "lines": <추출된_줄_수_없으면_30_최대_100>, "previous": <이전_파드_로그_요청시_true>, "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

3. 엔드포인트/URL 확인 (command: "endpoint")
설명: 배포된 서비스의 접속 주소를 확인하는 명령입니다.
기능: Service 확인 → LoadBalancer/NodePort/ClusterIP 엔드포인트 제공
사용자 입력 예시:
- 기본 표현: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?", "내 앱 주소 알려줘", "앱 URL 확인"
- 자연스러운 표현: "접속 주소 보여줘", "서비스 주소 알려줘", "엔드포인트 확인", "외부 접속 주소", "로드밸런서 주소"
- 다양한 뉘앙스: "앱 주소가 뭐야?", "어떻게 접속해?", "URL 좀 알려줘", "도메인 주소 확인", "외부에서 접근할 수 있는 주소", "웹사이트 주소", "앱에 어떻게 들어가?", "접속 방법 알려줘", "서비스 주소 체크", "외부 IP 확인"
필수 JSON 형식: { "command": "endpoint", "parameters": { "serviceName": "<추출된_서비스이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

4. 재시작 (command: "restart")
설명: 애플리케이션을 재시작하는 명령입니다.
기능: kubectl rollout restart deployment로 Pod 재시작
중요: "app", "앱"이라는 호칭은 Pod를 의미합니다.
사용자 입력 예시:
- 기본 표현: "앱 재시작해줘", "chat-app 껐다 켜줘", "nginx-test 재시작", "서비스 재시작해줘"
- 자연스러운 표현: "앱 다시 켜줘", "서버 재부팅", "앱 껐다 켜줘"
- 다양한 뉘앙스: "앱 다시 시작해줘", "서비스 재시작", "앱 리셋해줘", "서버 껐다 켜줘", "앱 새로고침", "서비스 재가동", "앱 재시작 필요", "서버 재시작해줘", "앱 다시 로드", "서비스 리부트"
- App 호칭 예시: "k-le-paas-test01 app 재시작", "my-app 재시작해줘", "앱 재시작"
필수 JSON 형식: { "command": "restart", "parameters": { "podName": "<추출된_파드이름_없으면_null>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

5. 스케일링 (command: "scale")
설명: Deployment의 서버(파드) 개수를 조절하는 명령입니다.
중요: "app", "앱"이라는 호칭은 Pod를 의미하므로, 스케일링은 "deployment", "배포" 등의 명시적 표현을 사용합니다.
사용자 입력 예시:
- 기본 표현: "서버 3대로 늘려줘", "chat-app 스케일 아웃", "서버 1개로 줄여"
- 자연스러운 표현: "nginx-deployment 5개로 늘려줘", "frontend-deployment 2개로 줄여줘", "백엔드 서버 4개로 스케일", "deployment 복제본 3개로 조정"
- 다양한 뉘앙스: "서버 개수 3개로", "deployment를 5개로 늘려줘", "인스턴스 2개로 줄여", "복제본 4개로 설정", "서버 수를 3개로 조정", "deployment 개수 늘려줘", "서버 추가해줘", "인스턴스 줄여줘", "스케일 업해줘", "스케일 다운", "deployment 확장", "서버 축소", "복제본 늘려줘", "파드 개수 조정"
필수 JSON 형식: { "command": "scale", "parameters": { "deploymentName": "<추출된_배포이름_없으면_null>", "replicas": <추출된_숫자> } }

6. 이미지 롤백 (command: "rollback")
설명: 애플리케이션을 이전 버전으로 되돌리는 명령입니다.
사용자 입력 예시:
- 기본 표현: "v1.1 버전으로 롤백해줘", "이전 배포로 되돌려"
- 자연스러운 표현: "앱 이전 버전으로 되돌려줘", "서비스 롤백"
- 다양한 뉘앙스: "이전 버전으로 복구", "앱 되돌리기", "서비스 리셋", "이전 상태로 복원", "버전 되돌리기", "배포 취소", "앱 복구", "이전 이미지로 변경"
필수 JSON 형식: { "command": "rollback", "parameters": { "deploymentName": "<추출된_배포이름_없으면_null>", "version": "<추출된_버전_태그>" } }

7. 배포 (command: "deploy")
설명: 사용자의 최신 코드를 빌드하고 클러스터에 배포합니다.
사용자 입력 예시:
- 기본 표현: "배포해줘", "최신 코드로 업데이트해줘"
- 자연스러운 표현: "앱 배포", "서비스 배포", "최신 버전 배포"
- 다양한 뉘앙스: "앱 업데이트", "서비스 업데이트", "새 버전 배포", "코드 배포", "앱 새로 배포", "서비스 새로 올려줘", "최신 코드 반영", "앱 새로고침"
필수 JSON 형식: { "command": "deploy", "parameters": { "deploymentName": "<추출된_배포이름>" } }

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

15. Service 상세 정보 조회 (command: "get_service")
설명: 특정 Service의 상세 정보를 조회하는 명령입니다.
사용자 입력 예시:
- 기본 표현: "nginx-service 정보 보여줘", "frontend 서비스 상세 확인", "my-app 서비스 자세히 보여줘"
- 자연스러운 표현: "서비스 상세 정보", "서비스 설정 확인", "서비스 구성 보여줘"
- 다양한 뉘앙스: "서비스 어떻게 설정되어 있어?", "서비스 설정 확인해줘", "서비스 정보 자세히", "서비스 구성 체크", "서비스 상세 분석", "서비스 설정 파악", "서비스 정보 분석"
필수 JSON 형식: { "command": "get_service", "parameters": { "serviceName": "<추출된_서비스_이름>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

16. Deployment 상세 정보 조회 (command: "get_deployment")
설명: 특정 Deployment의 상세 정보를 조회하는 명령입니다.
중요: "app", "앱"이라는 호칭은 Pod를 의미하므로, Deployment 조회는 "deployment", "배포" 등의 명시적 표현을 사용합니다.
사용자 입력 예시:
- 기본 표현: "nginx-deployment 정보 보여줘", "frontend-deployment 상세 확인", "my-deployment 배포 자세히 보여줘"
- 자연스러운 표현: "배포 상세 정보", "deployment 설정 확인", "배포 구성 보여줘"
- 다양한 뉘앙스: "deployment 어떻게 설정되어 있어?", "배포 설정 확인해줘", "deployment 정보 자세히", "배포 구성 체크", "deployment 상세 분석", "배포 설정 파악", "deployment 정보 분석", "배포 상태 상세히"
필수 JSON 형식: { "command": "get_deployment", "parameters": { "deploymentName": "<추출된_배포_이름>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 16가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
- 리소스 이름이 명시되지 않은 경우, 컨텍스트상 기본 리소스가 있다면 그 이름을 사용하거나 null을 반환합니다.
- 리소스 타입별 파라미터 사용: podName(파드), deploymentName(배포), serviceName(서비스)
- **중요한 리소스 타입 구분 규칙:**
  * "app", "앱"이라는 호칭은 Pod 관련 명령어(status, logs, restart)에서 사용
  * Deployment 관련 명령어(scale, get_deployment)에서는 "deployment", "배포" 등의 명시적 표현 사용
  * Service 관련 명령어(endpoint, get_service)에서는 "service", "서비스" 등의 명시적 표현 사용
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