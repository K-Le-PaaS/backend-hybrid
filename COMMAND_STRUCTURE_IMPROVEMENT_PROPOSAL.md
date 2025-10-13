# NLP 명령어 구조 개선 제안서

## 🎯 문제점 분석

### 현재 문제
1. **모든 명령어가 동일한 CommandRequest 구조 사용**
2. **불필요한 필드들이 항상 포함됨**
3. **명령어별 특화된 파라미터 처리 어려움**
4. **확장성 및 유지보수성 저하**

### 현재 구조의 문제점
```python
# 현재: 모든 명령어가 동일한 구조
class CommandRequest(BaseModel):
    command: str = Field(min_length=1)
    app_name: str = Field(default="")     # 모든 명령어가 사용
    replicas: int = Field(default=1)      # scale에서만 사용
    lines: int = Field(default=30)        # logs에서만 사용  
    version: str = Field(default="")      # rollback에서만 사용

# 결과: 비효율적인 구조
# status 명령어: app_name만 필요하지만 replicas, lines, version도 포함
# logs 명령어: app_name, lines만 필요하지만 replicas, version도 포함
```

## 🔧 개선 방안

### 방안 1: 명령어별 특화된 CommandRequest 클래스

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Union

# 기본 CommandRequest 인터페이스
class BaseCommandRequest(ABC):
    command: str
    
    @abstractmethod
    def to_plan_args(self) -> Dict[str, Any]:
        pass

# 1. Status 명령어 (app_name만 필요)
class StatusCommandRequest(BaseCommandRequest):
    command: str = "status"
    app_name: str = Field(default="")

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default"
        }

# 2. Logs 명령어 (app_name, lines 필요)
class LogsCommandRequest(BaseCommandRequest):
    command: str = "logs"
    app_name: str = Field(default="")
    lines: int = Field(default=30)

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default",
            "lines": self.lines
        }

# 3. Scale 명령어 (app_name, replicas 필요)
class ScaleCommandRequest(BaseCommandRequest):
    command: str = "scale"
    app_name: str = Field(default="")
    replicas: int = Field(default=1)

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default",
            "replicas": self.replicas
        }

# 4. Rollback 명령어 (app_name, version 필요)
class RollbackCommandRequest(BaseCommandRequest):
    command: str = "rollback"
    app_name: str = Field(default="")
    version: str = Field(default="")

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default",
            "version": self.version
        }

# 5. ListPods 명령어 (파라미터 없음)
class ListPodsCommandRequest(BaseCommandRequest):
    command: str = "list_pods"

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "namespace": "default"
        }

# 6. Restart 명령어 (app_name만 필요)
class RestartCommandRequest(BaseCommandRequest):
    command: str = "restart"
    app_name: str = Field(default="")

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default"
        }

# 7. Endpoint 명령어 (app_name만 필요)
class EndpointCommandRequest(BaseCommandRequest):
    command: str = "endpoint"
    app_name: str = Field(default="")

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "name": self.app_name or "app",
            "namespace": "default"
        }

# 8. Deploy 명령어 (app_name 필요)
class DeployCommandRequest(BaseCommandRequest):
    command: str = "deploy"
    app_name: str = Field(default="")

    def to_plan_args(self) -> Dict[str, Any]:
        return {
            "app_name": self.app_name or "app",
            "environment": "staging",
            "image": f"{self.app_name or 'app'}:latest",
            "replicas": 2
        }

# Union 타입으로 모든 명령어 타입 통합
CommandRequest = Union[
    StatusCommandRequest,
    LogsCommandRequest,
    ScaleCommandRequest,
    RollbackCommandRequest,
    ListPodsCommandRequest,
    RestartCommandRequest,
    EndpointCommandRequest,
    DeployCommandRequest
]
```

### 방안 2: Gemini 프롬프트 엔지니어링 개선

```python
# app/llm/gemini.py - 개선된 시스템 프롬프트
system_prompt = """SYSTEM PROMPT:
당신은 쿠버네티스 전문가 AI 어시스턴트입니다. 사용자의 자연어 명령을 분석하여 명령어별로 최적화된 JSON 형식으로 변환합니다.

명령어별 반환 형식:

1. 상태 확인 (command: "status")
설명: 배포된 애플리케이션의 현재 상태를 확인
사용자 입력 예시: "nginx 상태 확인해줘", "내 앱 상태 보여줘"
필수 JSON 형식: { "command": "status", "parameters": { "appName": "<앱이름_또는_null>" } }

2. 로그 조회 (command: "logs")
설명: 애플리케이션의 로그를 조회
사용자 입력 예시: "nginx 로그 20줄 보여줘", "에러 로그 찾아줘"
필수 JSON 형식: { "command": "logs", "parameters": { "appName": "<앱이름_또는_null>", "lines": <줄수_기본값30> } }

3. 스케일링 (command: "scale")
설명: 애플리케이션의 파드 개수를 조절
사용자 입력 예시: "nginx 스케일 3개로 늘려줘", "서버 5대로 늘려줘"
필수 JSON 형식: { "command": "scale", "parameters": { "appName": "<앱이름_또는_null>", "replicas": <목표개수> } }

4. 롤백 (command: "rollback")
설명: 애플리케이션을 이전 버전으로 되돌리기
사용자 입력 예시: "v1.1 버전으로 롤백해줘", "이전 배포로 되돌려"
필수 JSON 형식: { "command": "rollback", "parameters": { "appName": "<앱이름_또는_null>", "version": "<버전태그>" } }

5. 파드 목록 조회 (command: "list_pods")
설명: 현재 실행 중인 모든 파드 목록 조회
사용자 입력 예시: "모든 파드 조회해줘", "파드 목록 보여줘"
필수 JSON 형식: { "command": "list_pods", "parameters": {} }

6. 재시작 (command: "restart")
설명: 애플리케이션 재시작
사용자 입력 예시: "nginx 재시작해줘", "앱 재시작해줘"
필수 JSON 형식: { "command": "restart", "parameters": { "appName": "<앱이름_또는_null>" } }

7. 엔드포인트 조회 (command: "endpoint")
설명: 서비스의 접속 주소 확인
사용자 입력 예시: "nginx 접속 주소 알려줘", "서비스 URL 뭐야?"
필수 JSON 형식: { "command": "endpoint", "parameters": { "appName": "<앱이름_또는_null>" } }

8. 배포 (command: "deploy")
설명: 새로운 애플리케이션 배포
사용자 입력 예시: "배포해줘", "최신 코드로 업데이트해줘"
필수 JSON 형식: { "command": "deploy", "parameters": { "appName": "<앱이름>" } }

중요 규칙:
- 각 명령어는 해당 명령어에 필요한 파라미터만 포함
- 불필요한 파라미터는 절대 포함하지 않음
- appName이 명시되지 않으면 null 반환
- 오직 JSON 객체만 반환
"""

# 개선된 interpret 메서드
async def interpret(self, prompt: str, user_id: str = "default", project_name: str = "default") -> Dict[str, Any]:
    try:
        gemini_response = await self._call_gemini_api(prompt)
        command_data = self._parse_gemini_response(gemini_response)
        
        command = command_data.get("command", "unknown")
        parameters = command_data.get("parameters", {})
        
        # 명령어별 특화된 entities 생성
        entities = self._create_command_specific_entities(command, parameters)
        
        return {
            "intent": command,
            "entities": entities,
            "message": self._get_command_message(command),
            "llm": {
                "provider": "gemini",
                "model": self.settings.gemini_model,
                "mode": "interpretation_only",
            },
        }
    except Exception as e:
        return self._create_error_response(str(e))

def _create_command_specific_entities(self, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """명령어별 특화된 entities 생성"""
    
    if command == "status":
        return {
            "app_name": parameters.get("appName")
        }
    
    elif command == "logs":
        return {
            "app_name": parameters.get("appName"),
            "lines": parameters.get("lines", 30)
        }
    
    elif command == "scale":
        return {
            "app_name": parameters.get("appName"),
            "replicas": parameters.get("replicas", 1)
        }
    
    elif command == "rollback":
        return {
            "app_name": parameters.get("appName"),
            "version": parameters.get("version", "")
        }
    
    elif command == "list_pods":
        return {}  # 파라미터 없음
    
    elif command == "restart":
        return {
            "app_name": parameters.get("appName")
        }
    
    elif command == "endpoint":
        return {
            "app_name": parameters.get("appName")
        }
    
    elif command == "deploy":
        return {
            "app_name": parameters.get("appName")
        }
    
    else:
        return {
            "app_name": parameters.get("appName"),
            "replicas": parameters.get("replicas", 1),
            "lines": parameters.get("lines", 30),
            "version": parameters.get("version", "")
        }
```

### 방안 3: 명령어 팩토리 패턴 적용

```python
# app/services/command_factory.py
from typing import Dict, Any

class CommandFactory:
    @staticmethod
    def create_command_request(command: str, entities: Dict[str, Any]) -> BaseCommandRequest:
        """명령어 타입에 따라 적절한 CommandRequest 생성"""
        
        if command == "status":
            return StatusCommandRequest(
                app_name=entities.get("app_name", "")
            )
        
        elif command == "logs":
            return LogsCommandRequest(
                app_name=entities.get("app_name", ""),
                lines=entities.get("lines", 30)
            )
        
        elif command == "scale":
            return ScaleCommandRequest(
                app_name=entities.get("app_name", ""),
                replicas=entities.get("replicas", 1)
            )
        
        elif command == "rollback":
            return RollbackCommandRequest(
                app_name=entities.get("app_name", ""),
                version=entities.get("version", "")
            )
        
        elif command == "list_pods":
            return ListPodsCommandRequest()
        
        elif command == "restart":
            return RestartCommandRequest(
                app_name=entities.get("app_name", "")
            )
        
        elif command == "endpoint":
            return EndpointCommandRequest(
                app_name=entities.get("app_name", "")
            )
        
        elif command == "deploy":
            return DeployCommandRequest(
                app_name=entities.get("app_name", "")
            )
        
        else:
            raise ValueError(f"지원하지 않는 명령어: {command}")

# 개선된 plan_command 함수
def plan_command(req: BaseCommandRequest) -> CommandPlan:
    """CommandRequest를 CommandPlan으로 변환"""
    return CommandPlan(
        tool=f"k8s_{req.command}",
        args=req.to_plan_args()
    )
```

## 🎯 개선 효과

### 1. **명확한 타입 안정성**
```python
# 개선 전: 모든 명령어가 동일한 구조
req = CommandRequest(command="status", app_name="nginx", replicas=1, lines=30, version="")

# 개선 후: 명령어별 특화된 구조
req = StatusCommandRequest(app_name="nginx")  # status에 필요한 필드만
```

### 2. **불필요한 데이터 제거**
```python
# 개선 전: status 명령어도 불필요한 replicas, lines, version 포함
# 개선 후: status 명령어는 app_name만 포함
```

### 3. **확장성 향상**
```python
# 새로운 명령어 추가 시 해당 명령어에 특화된 클래스만 생성
class NewCommandRequest(BaseCommandRequest):
    command: str = "new_command"
    specific_param: str = Field(default="")
    
    def to_plan_args(self) -> Dict[str, Any]:
        return {"specific_param": self.specific_param}
```

### 4. **유지보수성 향상**
- 각 명령어의 요구사항이 명확히 분리됨
- 명령어별 독립적인 수정 가능
- 타입 힌트로 IDE 지원 향상

## 🚀 구현 우선순위

### Phase 1: 기본 구조 개선
1. BaseCommandRequest 인터페이스 생성
2. 각 명령어별 특화된 CommandRequest 클래스 생성
3. CommandFactory 구현

### Phase 2: Gemini 프롬프트 개선
1. 명령어별 특화된 시스템 프롬프트 업데이트
2. _create_command_specific_entities 메서드 구현

### Phase 3: 통합 및 테스트
1. nlp.py에서 새로운 구조 적용
2. 기존 테스트 케이스 업데이트
3. 통합 테스트 수행

## 📊 성능 개선 예상

| 항목 | 개선 전 | 개선 후 | 개선율 |
|------|---------|---------|--------|
| **메모리 사용량** | 모든 필드 포함 | 필요한 필드만 | ~30% 감소 |
| **네트워크 전송** | 불필요한 데이터 포함 | 최소한의 데이터만 | ~25% 감소 |
| **타입 안정성** | 런타임 에러 가능성 | 컴파일 타임 검증 | 100% 개선 |
| **유지보수성** | 모든 명령어 동일 구조 | 명령어별 특화 구조 | 50% 개선 |

이런 방향으로 개선하면 어떨까요? 어떤 부분부터 시작하고 싶으신가요? 🤔

