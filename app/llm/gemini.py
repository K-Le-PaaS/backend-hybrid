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
            elif command in ("scale", "deploy", "get_deployment"):
                # Deployment 관련 명령어
                if parameters.get("deploymentName") is not None:
                    entities["deployment_name"] = parameters.get("deploymentName")
            elif command in ("endpoint", "get_service"):
                # Service 관련 명령어
                if parameters.get("serviceName") is not None:
                    entities["service_name"] = parameters.get("serviceName")

            # namespace 기본값 포함이 필요한 명령어들
            if command in ("status", "endpoint", "restart", "overview", "list_pods", "list_apps", "logs", "get_service", "get_deployment", "cost_analysis", "current_node_cost", "scaling_cost", "network_cost"):
                entities["namespace"] = parameters.get("namespace", "default")

            # 현재 노드 비용 조회 파라미터
            if command == "current_node_cost":
                entities["node_spec"] = parameters.get("node_spec")
                entities["node_count"] = parameters.get("node_count", 1)

            # 노드 스케일링 비용 계산 파라미터
            if command == "scaling_cost":
                entities["node_spec"] = parameters.get("node_spec")
                entities["current_node_count"] = parameters.get("current_node_count", 1)
                entities["target_node_count"] = parameters.get("target_node_count")

            # 네트워크 비용 계산 파라미터
            if command == "network_cost":
                entities["public_ip_count"] = parameters.get("public_ip_count", 1)
                entities["traffic_gb"] = parameters.get("traffic_gb", 0)

            # 비용 분석 파라미터
            if command == "cost_analysis":
                entities["analysis_type"] = parameters.get("analysis_type", "usage")

            # 스케일링 복제수 및 GitHub 저장소 정보
            if command == "scale":
                # GitHub 저장소 정보 (필수)
                owner = parameters.get("owner", "")
                repo = parameters.get("repo", "")
                
                # owner/repo가 비어있는 경우 에러 처리
                if not owner or not repo:
                    entities["error"] = "GitHub 저장소 정보가 필요합니다. 'K-Le-PaaS/test01 4개로 스케일링 해줘' 형식으로 입력해주세요."
                    return {
                        "intent": "error",
                        "entities": entities,
                        "message": entities["error"]
                    }
                
                entities["github_owner"] = owner
                entities["github_repo"] = repo

                # 복제수 파싱
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

            # 비용 분석 명령어 파라미터 처리
            if command in ("current_node_cost", "scaling_cost", "network_cost", "cost_analysis"):
                # 네임스페이스
                entities["namespace"] = parameters.get("namespace", "default")
                
                if command == "current_node_cost":
                    entities["node_spec"] = parameters.get("node_spec")
                    entities["node_count"] = parameters.get("node_count", 1)
                    
                elif command == "scaling_cost":
                    entities["node_spec"] = parameters.get("node_spec")
                    entities["current_node_count"] = parameters.get("current_node_count", 1)
                    entities["target_node_count"] = parameters.get("target_node_count")
                    
                    # 스케일링 비용 계산에서 파라미터가 부족한 경우 인터랙티브 UI 제공
                    if not entities["node_spec"] or not entities["target_node_count"]:
                        entities["interactive"] = True
                        entities["type"] = "scaling_type_selection"
                    
                elif command == "network_cost":
                    entities["public_ip_count"] = parameters.get("public_ip_count", 1)
                    entities["traffic_gb"] = parameters.get("traffic_gb", 0)
                    
                    # 네트워크 비용 계산에서 파라미터가 부족한 경우 인터랙티브 UI 제공
                    if entities["public_ip_count"] == 1 and entities["traffic_gb"] == 0:
                        entities["interactive"] = True
                        entities["type"] = "network_cost_input"
                    
                elif command == "cost_analysis":
                    entities["analysis_type"] = parameters.get("analysis_type", "usage")

            # NCP 롤백 파라미터
            if command == "rollback":
                # GitHub 저장소 정보 (필수)
                owner = parameters.get("owner", "")
                repo = parameters.get("repo", "")
                
                # owner/repo가 비어있는 경우 에러 처리
                if not owner or not repo:
                    entities["error"] = "GitHub 저장소 정보가 필요합니다. 'K-Le-PaaS/test01 롤백해줘' 형식으로 입력해주세요."
                    return {
                        "intent": "error",
                        "entities": entities,
                        "message": entities["error"]
                    }
                
                entities["github_owner"] = owner
                entities["github_repo"] = repo

                # 커밋 SHA (선택: commitSha가 있으면 커밋 기반 롤백)
                commit_sha = parameters.get("commitSha")
                if commit_sha and isinstance(commit_sha, str):
                    entities["target_commit_sha"] = commit_sha.strip()
                else:
                    entities["target_commit_sha"] = None

                # N번째 전 (선택: stepsBack이 있으면 N번째 전 롤백)
                steps_back = parameters.get("stepsBack")
                if steps_back is not None:
                    try:
                        steps = int(steps_back)
                        entities["steps_back"] = max(1, min(steps, 10))  # 1~10 제한
                    except (TypeError, ValueError):
                        entities["steps_back"] = 1  # 기본값
                else:
                    entities["steps_back"] = None

            # 롤백 목록 조회 파라미터
            if command == "list_rollback":
                # GitHub 저장소 정보 (필수)
                entities["github_owner"] = parameters.get("owner", "")
                entities["github_repo"] = parameters.get("repo", "")

            # 배포 파라미터
            if command == "deploy":
                # GitHub 저장소 정보 (필수)
                owner = parameters.get("owner", "")
                repo = parameters.get("repo", "")
                
                # owner/repo가 비어있는 경우 에러 처리
                if not owner or not repo:
                    entities["error"] = "GitHub 저장소 정보가 필요합니다. 'K-Le-PaaS/test01 배포해줘' 형식으로 입력해주세요."
                    return {
                        "intent": "error",
                        "entities": entities,
                        "message": entities["error"]
                    }
                
                entities["github_owner"] = owner
                entities["github_repo"] = repo
                # 브랜치 (선택, 기본값 main)
                entities["branch"] = parameters.get("branch", "main")

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
                "list_rollback": "롤백 목록 조회 명령을 해석했습니다.",
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
                "current_node_cost": "현재 노드 비용 조회 명령을 해석했습니다.",
                "scaling_cost": "노드 스케일링 비용 계산 명령을 해석했습니다.",
                "network_cost": "네트워크 비용 계산 명령을 해석했습니다.",
                "cost_analysis": "비용 분석 명령을 해석했습니다.",
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
설명: NCP SourceCommit 매니페스트 기반으로 배포의 replicas를 조절하는 명령입니다.
중요: GitHub 저장소(owner/repo) 정보가 반드시 필요합니다.

사용자 입력 예시:
- **저장소 지정 패턴** (권장):
  * "K-Le-PaaS/test01을 3개로 늘려줘"
  * "K-Le-PaaS/test01 4개로 스케일링 해줘"
  * "K-Le-Paas/test01 4개로 스케일링 해줘"
  * "owner/repo 레플리카 5개로 스케일"
  * "myorg/myapp 서버 2개로 줄여"
  * "저장소 K-Le-PaaS/backend-hybrid을 4개로 확장"
  * "test01 저장소 3개로 스케일 아웃"

- **간단한 패턴** (저장소 정보 필수):
  * "test01을 3개로 늘려줘" → owner는 컨텍스트에서 추론
  * "backend 5개로 스케일" → owner는 컨텍스트에서 추론

- **스케일링 키워드 감지**:
  * "스케일링", "스케일", "scale", "레플리카", "replicas", "개로", "개로 조정", "개로 늘려", "개로 줄여"
  * "서버 개수", "인스턴스 개수", "pod 개수", "컨테이너 개수"

추출 규칙:
1. **스케일링 키워드**: "스케일링", "스케일", "scale", "레플리카", "replicas", "개로", "개로 조정", "개로 늘려", "개로 줄여" 등이 있으면 scale 명령으로 인식
2. **owner/repo 패턴**: "K-Le-PaaS/test01", "owner/repo", "저장소명" 등에서 GitHub 저장소 정보 추출
3. **숫자 추출**: "3개", "4개", "5개로" 등에서 숫자 추출 (1-100 범위)

필수 JSON 형식: { "command": "scale", "parameters": { "owner": "<GitHub_저장소_소유자>", "repo": "<GitHub_저장소_이름>", "replicas": <추출된_숫자> } }

6. NCP 배포 롤백 (command: "rollback")
설명: NCP SourceBuild/SourceDeploy 기반으로 이전 배포 버전으로 되돌리는 명령입니다.
중요: GitHub 저장소(owner/repo) 정보가 반드시 필요합니다.

롤백 방식 2가지:
A) 커밋 해시로 롤백: 특정 커밋 SHA를 지정하여 해당 버전으로 롤백
B) N번째 전으로 롤백: 숫자를 지정하여 N번째 이전 성공 배포로 롤백

사용자 입력 예시:
- **저장소 지정 패턴** (권장):
  * "K-Le-PaaS/test01 롤백해줘"
  * "K-Le-PaaS/test01 롤백 목록 보여줘"
  * "K-Le-PaaS/test01을 3번 전으로 롤백"
  * "K-Le-PaaS/test01 커밋 abc1234로 롤백"
  * "myorg/myapp 롤백해줘"
  * "저장소 K-Le-PaaS/backend-hybrid 롤백"

- **간단한 패턴** (저장소 정보 필수):
  * "test01 롤백해줘" → owner는 컨텍스트에서 추론
  * "backend 롤백" → owner는 컨텍스트에서 추론

- **커밋 해시 패턴**:
  * "owner/repo를 커밋 abc1234로 롤백해줘"
  * "myorg/myapp을 abc1234 커밋으로 되돌려"
  * "K-Le-PaaS/backend-hybrid 커밋 a1b2c3d로 복구"
  * "저장소 owner/repo 커밋 해시 abc1234로 롤백"

- **N번째 전 패턴**:
  * "owner/repo를 3번 전으로 롤백해줘"
  * "myorg/myapp 2번 전 배포로 되돌려"
  * "K-Le-PaaS/backend-hybrid 이전 배포로 복구" (1번 전으로 해석)
  * "저장소 owner/repo를 5번 전으로 롤백"
  * "owner/repo 바로 이전 버전으로 되돌려" (1번 전)
  * **"5번 전으로 롤백해줘" (owner/repo 없음, 컨텍스트에서 추론)**
  * **"3번 전으로 되돌려" (owner/repo 없음, 컨텍스트에서 추론)**
  * **"이전 버전으로 롤백" (owner/repo 없음, stepsBack=1)**

- **자연스러운 표현**:
  * "myorg/myapp 롤백해줘" (기본: 1번 전)
  * "owner/repo 예전 버전으로 되돌려"
  * **"롤백해줘" (owner/repo 없음, 컨텍스트에서 추론, stepsBack=1)**
  * **"이전으로 되돌려" (owner/repo 없음, stepsBack=1)**

추출 규칙:
1. **롤백 키워드 감지**: "롤백", "rollback", "되돌려", "revert", "복구", "restore", "이전" 등이 있으면 rollback 명령으로 인식
2. **owner/repo 패턴 추출**: "owner/repo", "저장소명", "myorg/myapp" 등에서 GitHub 저장소 정보 추출 (없으면 빈 문자열 또는 null)
3. **커밋 해시 추출**: "커밋", "commit", "해시", "hash" 키워드 뒤의 영숫자 조합 (최소 7자)
4. **숫자 추출**: "N번 전", "N개 전", "N번째 전", "previous N" 등에서 숫자 추출
5. **이전/previous**: 숫자 없이 "이전", "바로 전", "previous"만 있으면 1로 간주
6. **owner/repo 없을 때**: 롤백 키워드가 있고 숫자/커밋이 있으면 rollback으로 인식, owner/repo는 빈 문자열 반환 (컨텍스트에서 복원됨)

필수 JSON 형식:
{
  "command": "rollback",
  "parameters": {
    "owner": "<추출된_GitHub_owner_없으면_빈_문자열>",
    "repo": "<추출된_GitHub_repo_없으면_빈_문자열>",
    "commitSha": "<커밋_해시_패턴이면_추출_없으면_null>",
    "stepsBack": <N번째_전_패턴이면_숫자_없으면_null>
  }
}

예시 변환:
- "myorg/myapp을 abc1234로 롤백" → { "command": "rollback", "parameters": { "owner": "myorg", "repo": "myapp", "commitSha": "abc1234", "stepsBack": null } }
- "owner/repo 3번 전으로 롤백" → { "command": "rollback", "parameters": { "owner": "owner", "repo": "repo", "commitSha": null, "stepsBack": 3 } }
- "K-Le-PaaS/backend 이전 배포로" → { "command": "rollback", "parameters": { "owner": "K-Le-PaaS", "repo": "backend", "commitSha": null, "stepsBack": 1 } }
- **"5번 전으로 롤백해줘" → { "command": "rollback", "parameters": { "owner": "", "repo": "", "commitSha": null, "stepsBack": 5 } }**
- **"이전 버전으로 되돌려" → { "command": "rollback", "parameters": { "owner": "", "repo": "", "commitSha": null, "stepsBack": 1 } }**

6-1. 롤백 목록 조회 (command: "list_rollback")
설명: 프로젝트의 현재 배포 상태, 롤백 가능한 버전 목록, 최근 롤백 히스토리를 조회하는 명령입니다.
사용자 입력 예시:
  * "K-Le-PaaS/test01 롤백 목록 보여줘"
  * "owner/repo 배포 이력 확인"
  * "myorg/myapp 롤백 가능한 버전 보여줘"
  * "배포 히스토리 확인"
  * "롤백 리스트 조회"
필수 JSON 형식: { "command": "list_rollback", "parameters": { "owner": "<저장소_소유자>", "repo": "<저장소_이름>" } }
예시:
- "K-Le-PaaS/test01 롤백 목록" → { "command": "list_rollback", "parameters": { "owner": "K-Le-PaaS", "repo": "test01" } }
- "myorg/myapp 배포 이력" → { "command": "list_rollback", "parameters": { "owner": "myorg", "repo": "myapp" } }

7. 배포 (command: "deploy")
설명: GitHub 저장소의 최신 main 브랜치 커밋을 빌드하고 클러스터에 배포합니다.
중요: GitHub 저장소(owner/repo) 정보가 반드시 필요합니다.

사용자 입력 예시:
- **저장소 지정 패턴** (권장):
  * "K-Le-PaaS/test01 배포해줘"
  * "owner/repo 배포"
  * "myorg/myapp 최신 코드로 배포해줘"
  * "저장소 K-Le-PaaS/backend-hybrid 배포"
  * "test01 저장소 배포해줘"

- **간단한 패턴** (저장소 정보 필수):
  * "test01 배포해줘" → owner는 컨텍스트에서 추론
  * "backend 배포" → owner는 컨텍스트에서 추론

- **자연스러운 표현**:
  * "최신 코드로 업데이트해줘"
  * "앱 배포", "서비스 배포", "최신 버전 배포"
  * "앱 업데이트", "서비스 업데이트", "새 버전 배포"
  * "코드 배포", "앱 새로 배포", "서비스 새로 올려줘"
  * "최신 코드 반영", "앱 새로고침"

추출 규칙:
1. **owner/repo 패턴 추출**: "owner/repo", "저장소명", "myorg/myapp" 등에서 GitHub 저장소 정보 추출
2. **간단한 repo 이름**: "test01 배포" → repo="test01", owner는 컨텍스트 또는 빈 문자열
3. **브랜치**: 명시되지 않으면 기본값 "main" 사용

필수 JSON 형식: { "command": "deploy", "parameters": { "owner": "<추출된_GitHub_owner>", "repo": "<추출된_GitHub_repo>", "branch": "<추출된_브랜치_없으면_'main'>" } }

예시 변환:
- "K-Le-PaaS/test01 배포해줘" → { "command": "deploy", "parameters": { "owner": "K-Le-PaaS", "repo": "test01", "branch": "main" } }
- "test01 배포" → { "command": "deploy", "parameters": { "owner": "", "repo": "test01", "branch": "main" } }
- "myorg/backend-hybrid 최신 코드로 배포" → { "command": "deploy", "parameters": { "owner": "myorg", "repo": "backend-hybrid", "branch": "main" } }

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

17. 현재 노드 비용 조회 (command: "current_node_cost")
설명: 현재 사용 중인 NCP 노드의 비용 정보를 조회하는 명령입니다. 스펙이나 개수가 명시되지 않은 경우 인터랙티브 UI를 제공합니다.
사용자 입력 예시:
- 기본 표현: "현재 내가 쓰는 노드 비용은?", "내 노드 비용 얼마나 나와?", "현재 서버 비용 확인"
- 스펙 지정: "c2-g3 노드 비용은?", "내가 쓰는 c4-g3 비용 얼마나?", "c8-g3 비용 확인"
- 개수 포함: "c2-g3 노드 2개 비용은?", "c4-g3 서버 3대 비용", "내 노드 5개 비용"
- 자연스러운 표현: "현재 클러스터 비용", "노드 비용 확인", "서버 요금 조회", "내 서버 비용"
- 다양한 뉘앙스: "노드 요금", "서버 비용", "인스턴스 비용", "컴퓨트 비용", "현재 비용"
- 불완전한 질문: "노드 비용", "서버 비용", "비용 확인", "얼마나 나와?"

추출 규칙:
1. **노드 스펙 추출**: "c2-g3", "c4-g3", "c8-g3", "c16-g3", "c32-g3", "c48-g3", "c64-g3" 등 NCP 서버 스펙명 추출
2. **노드 개수 추출**: "2개", "3개", "5개", "10개" 등 숫자 추출 (없으면 1개로 기본값)
3. **현재 비용 키워드**: "현재", "내가 쓰는", "내", "지금", "현재 사용" 등
4. **인터랙티브 UI 조건**: 스펙이나 개수가 명시되지 않은 경우 항상 인터랙티브 UI 제공

필수 JSON 형식: { "command": "current_node_cost", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>", "node_spec": "<추출된_노드_스펙_없으면_null>", "node_count": <추출된_노드_개수_없으면_1> } }

18. 노드 스케일링 비용 계산 (command: "scaling_cost")
설명: 노드 개수를 늘리거나 줄일 때의 비용 변화를 계산하는 명령입니다. 스펙이나 개수가 명시되지 않은 경우 인터랙티브 UI를 제공합니다.
사용자 입력 예시:
- 기본 표현: "내가 쓰는 노드를 3대로 늘리면 한달에 비용은?", "노드 5개로 늘리면 얼마나?", "서버 3대 추가하면 비용은?"
- 스펙 지정: "c2-g3을 3개로 스케일링하면 비용은?", "c4-g3을 5개로 늘리면 비용", "c8-g3 2개 추가 비용"
- 현재+목표: "c2-g3 노드 2개에서 5개로 늘리면 비용은?", "현재 3개에서 6개로 스케일링 비용"
- 자연스러운 표현: "스케일링 비용 계산", "노드 확장 비용", "서버 증설 비용", "스케일 아웃 비용", "스케일업 비용 계산", "스케일아웃 비용 계산"
- 다양한 뉘앙스: "노드 늘리면 비용", "서버 추가 비용", "인스턴스 확장 비용", "스케일링 요금"
- 불완전한 질문: "5개로 늘리면?", "3개로 스케일링하면?", "노드 늘리면?", "스케일링 비용", "확장 비용", "늘리면?", "스케일링하면?"

추출 규칙:
1. **노드 스펙 추출**: "c2-g3", "c4-g3", "c8-g3", "c16-g3", "c32-g3", "c48-g3", "c64-g3" 등 NCP 서버 스펙명 추출
2. **현재 개수 추출**: "2개에서", "현재 3개", "지금 5개" 등 현재 노드 개수 추출 (없으면 1개로 기본값)
3. **목표 개수 추출**: "3개로", "5개로", "10개로" 등 목표 노드 개수 추출
4. **스케일링 키워드**: "늘리면", "스케일링", "확장", "추가", "증설" 등
5. **인터랙티브 UI 조건**: 스펙이나 목표 개수가 명시되지 않은 경우 항상 인터랙티브 UI 제공

필수 JSON 형식: { "command": "scaling_cost", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>", "node_spec": "<추출된_노드_스펙_없으면_null>", "current_node_count": <현재_노드_개수_없으면_1>, "target_node_count": <목표_노드_개수_필수> } }

19. 네트워크 비용 계산 (command: "network_cost")
설명: Public IP와 트래픽 사용량에 따른 네트워크 비용을 계산하는 명령입니다. IP 개수나 트래픽 용량이 명시되지 않은 경우 인터랙티브 UI를 제공합니다.
사용자 입력 예시:
- 기본 표현: "네트워크 비용은 얼마나 나올까?", "Public IP 비용 확인", "트래픽 비용 계산"
- 트래픽 용량 지정: "아웃바운드 트래픽 100GB 비용은?", "인터넷 트래픽 1TB 비용", "트래픽 500GB 비용"
- Public IP 개수: "Public IP 2개 비용", "공인 IP 3개 비용", "외부 IP 비용"
- 조합: "Public IP 1개, 트래픽 200GB 비용", "네트워크 100GB 비용", "인터넷 트래픽 비용"
- 자연스러운 표현: "네트워크 요금", "트래픽 요금", "Public IP 요금", "인터넷 비용"
- 다양한 뉘앙스: "네트워크 비용", "트래픽 비용", "인터넷 요금", "외부 접속 비용"
- 불완전한 질문: "네트워크 비용", "트래픽 비용", "Public IP 비용", "인터넷 비용", "네트워크 요금"

추출 규칙:
1. **트래픽 용량 추출**: "100GB", "1TB", "500GB", "200GB" 등 용량 단위 추출 (없으면 0GB)
2. **Public IP 개수 추출**: "1개", "2개", "3개" 등 Public IP 개수 추출 (없으면 1개)
3. **네트워크 키워드**: "네트워크", "트래픽", "Public IP", "인터넷", "아웃바운드" 등
4. **인터랙티브 UI 조건**: IP 개수나 트래픽 용량이 명시되지 않은 경우 항상 인터랙티브 UI 제공

필수 JSON 형식: { "command": "network_cost", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>", "public_ip_count": <추출된_Public_IP_개수_없으면_1>, "traffic_gb": <추출된_트래픽_용량_없으면_0> } }

20. 비용 분석 및 최적화 (command: "cost_analysis")
설명: 클러스터의 전체적인 비용 현황을 분석하고 최적화 제안을 제공하는 명령입니다.
사용자 입력 예시:
- 기본 표현: "비용 분석해줘", "현재 클러스터 비용 확인", "비용 현황 보여줘", "얼마나 나와?"
- 최적화 요청: "비용 줄일 방법 알려줘", "비용 절감 방안", "저렴하게 운영하는 방법", "비용 최적화 제안"
- 상세 분석: "사용하지 않는 리소스 찾아줘", "낭비되는 비용 확인", "불필요한 리소스 확인"
- 예상 비용: "월간 예상 비용", "이번 달 예상 비용", "비용 예측해줘"
- 다양한 뉘앙스: "비용 얼마나 드나?", "클러스터 운영 비용", "요금 확인", "비용 체크", "지출 현황", "예산 확인", "리소스 비용", "인프라 비용", "운영 비용 분석"

추출 규칙:
1. **분석 타입 결정**:
   - 최적화: "줄일", "절감", "최적화", "저렴하게" 등
   - 예측: "예상", "예측", "예상치" 등
   - 기본: "현황", "분석", "확인" 등

필수 JSON 형식: { "command": "cost_analysis", "parameters": { "namespace": "<추출된_네임스페이스_없으면_'default'>", "analysis_type": "<optimization|forecast|usage>" } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 20가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
- 리소스 이름이 명시되지 않은 경우, 컨텍스트상 기본 리소스가 있다면 그 이름을 사용하거나 null을 반환합니다.
- 리소스 타입별 파라미터 사용: podName(파드), deploymentName(배포), serviceName(서비스)
- **중요한 리소스 타입 구분 규칙:**
  * "app", "앱"이라는 호칭은 Pod 관련 명령어(status, logs, restart)에서 사용
  * Deployment 관련 명령어(scale, get_deployment)에서는 "deployment", "배포" 등의 명시적 표현 사용
  * Service 관련 명령어(endpoint, get_service)에서는 "service", "서비스" 등의 명시적 표현 사용
- **롤백 명령 우선순위**:
  * commitSha와 stepsBack이 둘 다 있으면 commitSha 우선 (커밋 기반 롤백)
  * 둘 다 없으면 stepsBack=1로 기본 설정 (1번 전 배포로 롤백)
  * owner/repo가 없어도 롤백 키워드가 있으면 rollback 명령으로 인식 (저장소 정보는 컨텍스트에서 복원)
- **불완전한 질문 처리**:
  * "5개로 늘리면?", "3개로 스케일링하면?", "늘리면?", "스케일링하면?" → scaling_cost 명령으로 인식 (target_node_count 추출)
  * "노드 늘리면?", "스케일링 비용", "확장 비용" → scaling_cost 명령으로 인식
  * "네트워크 비용", "트래픽 비용", "Public IP 비용" → network_cost 명령으로 인식
  * "노드 비용", "서버 비용", "비용 확인", "얼마나 나와?" → current_node_cost 명령으로 인식
  * 불완전한 질문의 경우 해당 명령어로 인식하되 파라미터는 기본값으로 설정
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
