# NLP 시스템 퀵 스타트 가이드

> **🎯 목적**: 새로운 팀원이 NLP 시스템을 빠르게 이해하고 개발에 참여할 수 있도록 하는 가이드

---

## 🚀 5분 만에 NLP 시스템 이해하기

### 핵심 개념
```
사용자 자연어 → Gemini 해석 → Kubernetes 실행 → 결과 반환
```

### 실제 동작 예시
1. **사용자**: "nginx 상태 확인해줘"
2. **Gemini**: `{"intent": "status", "entities": {"app_name": "nginx"}}`
3. **Commands**: `kubectl get deployment nginx`
4. **결과**: nginx 배포 상태 정보 반환

---

## 📂 핵심 파일 3개만 기억하세요

### 1. `app/api/v1/nlp.py` - 진입점
```python
# 사용자 요청을 받아서 전체 플로우를 조율
@router.post("/nlp/process")
async def process_command(command_data: NaturalLanguageCommand):
    # 1. Gemini 호출
    # 2. Commands 실행  
    # 3. 결과 반환
```

### 2. `app/llm/gemini.py` - AI 해석기
```python
# 자연어를 구조화된 명령으로 변환
async def interpret(self, prompt: str) -> Dict[str, Any]:
    # Gemini API 호출 → JSON 파싱 → entities 추출
```

### 3. `app/services/commands.py` - 실행기
```python
# 구조화된 명령을 실제 K8s 작업으로 실행
async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    # K8s API 호출 → 결과 반환
```

---

## 🔧 개발 환경 설정

### 1. 환경 변수 설정
```bash
# .env 파일에 추가
KLEPAAS_GEMINI_API_KEY=your_gemini_api_key_here
KLEPAAS_K8S_CONFIG_FILE=/path/to/your/nks-kubeconfig.yaml
```

### 2. 서버 실행
```bash
cd /path/to/backend-hybrid
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. 테스트
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 파드 조회해줘",
       "timestamp": "2025-10-12T00:50:00Z"
     }'
```

---

## 🎯 새로운 명령어 추가하기 (5분 튜토리얼)

### 예시: "서비스 목록 조회" 명령어 추가

#### Step 1: Gemini에게 새 명령어 알려주기
```python
# app/llm/gemini.py - _call_gemini_api() 메서드
system_prompt = """
9. 서비스 목록 조회 (command: "list_services")
설명: 현재 실행 중인 모든 서비스의 목록을 조회하는 명령입니다.
사용자 입력 예시: "서비스 목록 보여줘", "모든 서비스 조회해줘"
필수 JSON 형식: { "command": "list_services", "parameters": {} }
"""
```

#### Step 2: 명령 계획 추가
```python
# app/services/commands.py - plan_command() 함수
elif command == "list_services":
    return CommandPlan(
        tool="k8s_list_services",
        args={"namespace": ns}
    )
```

#### Step 3: 실행 로직 추가
```python
# app/services/commands.py - execute_command() 함수
if plan.tool == "k8s_list_services":
    return await _execute_list_services(plan.args)

# 새로운 실행 함수 추가
async def _execute_list_services(args: Dict[str, Any]) -> Dict[str, Any]:
    namespace = args.get("namespace", "default")
    try:
        core_v1 = get_core_v1_api()
        services = core_v1.list_namespaced_service(namespace=namespace)
        
        service_list = []
        for service in services.items:
            service_info = {
                "name": service.metadata.name,
                "type": service.spec.type,
                "cluster_ip": service.spec.cluster_ip,
                "external_ip": service.spec.external_ips or "None"
            }
            service_list.append(service_info)
        
        return {
            "status": "success",
            "namespace": namespace,
            "total_services": len(service_list),
            "services": service_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

#### Step 4: 메시지 맵 업데이트
```python
# app/llm/gemini.py - interpret() 메서드
messages = {
    # ... 기존 메시지들
    "list_services": "서비스 목록 조회 명령을 해석했습니다."
}
```

#### Step 5: 테스트
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "서비스 목록 보여줘",
       "timestamp": "2025-10-12T00:50:00Z"
     }'
```

**🎉 완료!** 새로운 명령어가 추가되었습니다.

---

## 🐛 디버깅 체크리스트

### 문제가 생겼을 때 확인할 것들

#### 1. Gemini API 관련
```bash
# 환경변수 확인
echo $KLEPAAS_GEMINI_API_KEY

# API 키 유효성 확인 (Gemini 콘솔에서)
```

#### 2. Kubernetes 연결 관련
```bash
# kubeconfig 파일 확인
ls -la $KLEPAAS_K8S_CONFIG_FILE

# K8s 연결 테스트
kubectl --kubeconfig=$KLEPAAS_K8S_CONFIG_FILE get pods
```

#### 3. 로그 확인
```bash
# 서버 로그에서 확인할 키워드
grep "자연어 명령 처리 시작" logs/
grep "Gemini 해석 결과" logs/
grep "K8s 실행 결과" logs/
```

#### 4. 일반적인 문제들
| 문제 | 원인 | 해결방법 |
|------|------|----------|
| "명령 해석 중 오류" | Gemini API 키 문제 | API 키 재확인 |
| "Deployment를 찾을 수 없습니다" | 앱 이름 오타 | 정확한 앱 이름 사용 |
| "K8s 연결 실패" | kubeconfig 문제 | 파일 경로 및 권한 확인 |

---

## 📊 성능 최적화 팁

### 응답 시간 단축하기

#### 1. Gemini API 최적화
```python
# 타임아웃 줄이기 (주의: 너무 짧으면 실패)
async with httpx.AsyncClient() as client:
    response = await client.post(url, timeout=10.0)  # 30초 → 10초
```

#### 2. 캐싱 활용
```python
# 자주 사용되는 명령어 결과 캐싱 (향후 구현)
cache_key = f"status_{app_name}_{namespace}"
cached_result = redis.get(cache_key)
if cached_result:
    return cached_result
```

#### 3. 병렬 처리
```python
# 여러 K8s API 호출을 병렬로 실행 (향후 구현)
import asyncio

async def get_deployment_and_pods(deployment_name, namespace):
    tasks = [
        get_deployment_info(deployment_name, namespace),
        get_pods_info(deployment_name, namespace)
    ]
    return await asyncio.gather(*tasks)
```

---

## 🧪 테스트 작성 가이드

### 단위 테스트 예시
```python
# tests/test_nlp_commands.py
import pytest
from app.llm.gemini import GeminiClient
from app.services.commands import plan_command, CommandRequest

@pytest.mark.asyncio
async def test_nginx_status_command():
    # Given
    gemini_client = GeminiClient()
    command = "nginx 상태 확인해줘"
    
    # When
    result = await gemini_client.interpret(command)
    
    # Then
    assert result["intent"] == "status"
    assert result["entities"]["app_name"] == "nginx"

@pytest.mark.asyncio
async def test_command_planning():
    # Given
    req = CommandRequest(
        command="status",
        app_name="nginx",
        replicas=1,
        lines=30,
        version=""
    )
    
    # When
    plan = plan_command(req)
    
    # Then
    assert plan.tool == "k8s_get_status"
    assert plan.args["name"] == "nginx"
    assert plan.args["namespace"] == "default"
```

### 통합 테스트 예시
```python
# tests/test_nlp_integration.py
@pytest.mark.asyncio
async def test_full_nlp_flow():
    # Given
    test_client = TestClient(app)
    
    # When
    response = test_client.post("/api/v1/nlp/process", json={
        "command": "모든 파드 조회해줘",
        "timestamp": "2025-10-12T00:50:00Z"
    })
    
    # Then
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["action"] == "list_pods"
    assert "pods" in data["data"]["k8s_result"]
```

---

## 📚 학습 자료

### 필수 읽기 자료
1. **[NLP 실행 아키텍처](./NLP_EXECUTION_ARCHITECTURE.md)** - 전체 시스템 이해
2. **[환경 설정 가이드](../ENVIRONMENT_AND_CONFIG.md)** - 개발 환경 구축
3. **[Kubernetes 설정](./KUBERNETES_CONFIG.md)** - K8s 연결 설정

### 참고 문서
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)
- [Gemini API 문서](https://ai.google.dev/docs)

### 팀 내부 자료
- 코드 리뷰 가이드라인
- 배포 프로세스 문서
- 모니터링 대시보드

---

## 🤝 팀 협업 가이드

### 코드 리뷰 체크리스트
- [ ] 새로운 명령어가 Gemini 시스템 프롬프트에 추가되었나?
- [ ] 에러 처리가 적절히 구현되었나?
- [ ] 테스트 케이스가 작성되었나?
- [ ] 로깅이 충분히 추가되었나?
- [ ] API 문서가 업데이트되었나?

### Git 커밋 메시지 규칙
```
feat(nlp): add list_services command
fix(nlp): handle empty app_name in status command
docs(nlp): update API documentation
test(nlp): add integration tests for new commands
```

### 브랜치 전략
```
main
├── feature/nlp-new-command
├── bugfix/nlp-error-handling
└── docs/nlp-architecture-update
```

---

## 🆘 도움이 필요할 때

### 팀 내 연락처
- **NLP 시스템 담당자**: [담당자명]
- **Kubernetes 전문가**: [담당자명]
- **DevOps 담당자**: [담당자명]

### 자주 묻는 질문
**Q: 새로운 명령어를 추가했는데 작동하지 않아요.**  
A: Gemini 시스템 프롬프트에 명령어가 추가되었는지, commands.py에 실행 로직이 구현되었는지 확인하세요.

**Q: K8s 연결이 안 돼요.**  
A: `KLEPAAS_K8S_CONFIG_FILE` 환경변수가 올바른 kubeconfig 파일을 가리키고 있는지, 파일 권한이 올바른지 확인하세요.

**Q: Gemini API 호출이 실패해요.**  
A: API 키가 유효한지, 네트워크 연결이 정상인지, API 할당량이 남아있는지 확인하세요.

---

## 🎯 다음 단계

### 학습 로드맵
1. **Week 1**: 기본 명령어 이해 및 테스트
2. **Week 2**: 새로운 명령어 추가 연습
3. **Week 3**: 에러 처리 및 성능 최적화
4. **Week 4**: 고급 기능 개발 (캐싱, 모니터링 등)

### 기여 방법
- [ ] 새로운 명령어 추가
- [ ] 테스트 케이스 작성
- [ ] 문서 개선
- [ ] 버그 수정
- [ ] 성능 최적화

---

**💡 팁**: 이 문서는 계속 업데이트됩니다. 새로운 내용이나 개선사항이 있으면 언제든 제안해주세요!

**작성자**: AI Assistant  
**최종 수정**: 2025-10-12  
**다음 리뷰**: 2025-10-19
