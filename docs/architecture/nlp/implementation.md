# NLP 명령어 구현 가이드

> **목적**: NLP 시스템에 새로운 명령어를 추가하는 방법과 기존 명령어들의 구현 방식을 상세히 설명하는 가이드 문서

---

## 📋 목차
1. [명령어 구현 개요](#명령어-구현-개요)
2. [현재 구현된 명령어 목록](#현재-구현된-명령어-목록)
3. [명령어별 상세 구현](#명령어별-상세-구현)
4. [새 명령어 추가 방법](#새-명령어-추가-방법)
5. [공통 구현 패턴](#공통-구현-패턴)
6. [테스트 방법](#테스트-방법)
7. [트러블슈팅](#트러블슈팅)

---

## 🎯 명령어 구현 개요

### 전체 아키텍처
```
사용자 자연어 입력
    ↓
Gemini API 해석 (자연어 → JSON)
    ↓
CommandRequest 생성 (JSON → 구조화된 객체)
    ↓
CommandPlan 생성 (CommandRequest → 실행 계획)
    ↓
Kubernetes API 실행 (CommandPlan → 실제 K8s 작업)
    ↓
결과 반환 (K8s 결과 → 사용자 응답)
```

### 핵심 파일들
- **`app/llm/gemini.py`**: 자연어 해석 및 시스템 프롬프트
- **`app/services/commands.py`**: 명령어 계획 수립 및 실행
- **`app/services/k8s_client.py`**: Kubernetes API 클라이언트 관리
- **`app/api/v1/nlp.py`**: API 엔드포인트 및 오케스트레이션

---

## 📊 현재 구현된 명령어 목록

| 번호 | 명령어 | 자연어 예시 | 구현 상태 | 주요 기능 |
|------|--------|-------------|-----------|-----------|
| 1 | **`status`** | "nginx 상태 확인해줘" | ✅ 완전 구현 | 앱 상태, 파드 정보 조회 |
| 2 | **`logs`** | "nginx 로그 20줄 보여줘" | ✅ 완전 구현 | 앱 로그 조회 (최대 100줄) |
| 3 | **`endpoint`** | "nginx 접속 주소 알려줘" | ✅ 완전 구현 | Ingress 도메인 조회 |
| 4 | **`restart`** | "nginx 재시작해줘" | ✅ 완전 구현 | kubectl rollout restart |
| 5 | **`scale`** | "nginx 스케일 3개로 늘려줘" | ⚠️ 미래 구현 | 매니페스트 기반 스케일링 |
| 6 | **`rollback`** | "v1.1 버전으로 롤백해줘" | ✅ 완전 구현 | 이전 버전으로 되돌리기 |
| 7 | **`deploy`** | "배포해줘" | ✅ 완전 구현 | 새 애플리케이션 배포 |
| 8 | **`overview`** | "전체 상황 보여줘" | ✅ 완전 구현 | 통합 대시보드 조회 |
| 9 | **`list_pods`** | "모든 파드 조회해줘" | ✅ 완전 구현 | 파드 목록 조회 |
| 10 | **`list_deployments`** | "모든 Deployment 조회해줘" | ✅ 완전 구현 | 전체 Deployment 목록 |
| 11 | **`list_services`** | "모든 Service 조회해줘" | ✅ 완전 구현 | 전체 Service 목록 |
| 12 | **`list_ingresses`** | "모든 도메인 조회해줘" | ✅ 완전 구현 | 전체 Ingress/도메인 목록 |
| 13 | **`list_namespaces`** | "모든 네임스페이스 조회해줘" | ✅ 완전 구현 | 네임스페이스 목록 |
| 14 | **`list_apps`** | "test 네임스페이스 앱 목록 보여줘" | ✅ 완전 구현 | 특정 네임스페이스 앱 목록 |

---

## 🔧 명령어별 상세 구현

### 1️⃣ **`status` - 상태 확인**

#### **자연어 예시**
- "nginx 상태 확인해줘"
- "내 앱 상태 보여줘"
- "chat-app 상태 어때?"
- "서버 목록 확인"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "status",
  "parameters": {
    "appName": "nginx",        # 앱 이름 (필수)
    "namespace": "default"     # 네임스페이스 (선택사항)
  }
}
```

#### **실행 과정**
```python
async def _execute_get_status(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Apps V1 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    
    # 2단계: Deployment 정보 조회
    deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
    
    # 3단계: Core V1 API 클라이언트 획득
    core_v1 = get_core_v1_api()
    
    # 4단계: 관련 Pod 목록 조회
    pods = core_v1.list_namespaced_pod(
        namespace=namespace, 
        label_selector=f"app={name}"  # "app=nginx"
    )
    
    # 5단계: 데이터 가공 및 반환
    return {
        "status": "success",
        "deployment": {...},
        "pods": [...]
    }
```

---

### 2️⃣ **`logs` - 로그 조회**

#### **자연어 예시**
- "nginx 로그 20줄 보여줘"
- "최신 로그 100줄 보여줘"
- "로그 확인"
- "에러 로그 찾아줘"

#### **특징**
- **최대 100줄 제한**: API 성능 및 리소스 보호
- **CrashLoopBackOff 대응**: `--previous` 옵션으로 이전 파드 로그 조회
- **네임스페이스별 조회**: 특정 네임스페이스의 앱 로그 확인

#### **실행 과정**
```python
async def _execute_get_logs(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    lines = args.get("lines", 30) # 20
    previous = args.get("previous", False)  # True if CrashLoopBackOff
    
    # 1단계: 네임스페이스 존재 확인
    core_v1.read_namespace(name=namespace)
    
    # 2단계: Deployment와 연결된 Pod 찾기
    pods = core_v1.list_namespaced_pod(
        namespace=namespace, 
        label_selector=f"app={name}"
    )
    
    # 3단계: Pod 존재 확인
    if not pods.items:
        return {"status": "error", "message": f"'{name}' 관련 Pod를 찾을 수 없습니다."}
    
    # 4단계: 첫 번째 Pod의 로그 조회
    pod_name = pods.items[0].metadata.name
    logs = core_v1.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        tail_lines=lines,
        previous=previous  # CrashLoopBackOff 대응
    )
    
    return {
        "status": "success",
        "pod_name": pod_name,
        "lines": lines,
        "logs": logs
    }
```

---

### 3️⃣ **`endpoint` - 엔드포인트 조회**

#### **자연어 예시**
- "nginx 접속 주소 알려줘"
- "내 앱 접속 주소 알려줘"
- "서비스 URL 뭐야?"
- "앱 URL 확인"

#### **특징**
- **Ingress 우선**: `https://<service-name>.klepaas.app` 도메인 반환
- **도메인 미설정 시**: 구체적인 에러 메시지 제공
- **NodePort 제외**: Ingress 기반 접속만 지원

#### **실행 과정**
```python
async def _execute_get_endpoints(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Networking V1 API 클라이언트 획득
    networking_v1 = get_networking_v1_api()
    
    # 2단계: 네임스페이스의 모든 Ingress 조회
    ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
    
    # 3단계: 해당 서비스와 연결된 Ingress 찾기
    for ingress in ingresses.items:
        for rule in ingress.spec.rules or []:
            for path in rule.http.paths or []:
                if hasattr(path.backend.service, 'name') and path.backend.service.name == name:
                    # 도메인 추출
                    host = rule.host
                    if host:
                        domain = f"https://{host}"
                        return {
                            "status": "success",
                            "service_name": name,
                            "namespace": namespace,
                            "endpoints": [domain],
                            "message": "Ingress 도메인으로 접속 가능합니다."
                        }
    
    # 4단계: Ingress를 찾지 못한 경우
    return {
        "status": "error",
        "service_name": name,
        "namespace": namespace,
        "message": f"'{name}' 서비스에 대한 Ingress 도메인이 설정되지 않았습니다. 도메인 설정이 필요합니다."
    }
```

---

### 4️⃣ **`restart` - 재시작**

#### **자연어 예시**
- "nginx 재시작해줘"
- "앱 재시작해줘"
- "chat-app 껐다 켜줘"

#### **특징**
- **kubectl rollout restart 방식**: 무중단 Rolling Update
- **서비스 중단 없음**: 새 Pod Ready 확인 후 기존 Pod 제거
- **Production 안전**: 실제 운영 환경에서 사용하는 방식

#### **실행 과정**
```python
async def _execute_restart(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Apps V1 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    
    # 2단계: Deployment 존재 확인
    deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
    
    # 3단계: Pod template에 재시작 annotation 추가
    if deployment.spec.template.metadata.annotations is None:
        deployment.spec.template.metadata.annotations = {}
    
    # 재시작 시간을 annotation에 추가
    deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now(timezone.utc).isoformat()
    
    # 4단계: Deployment 업데이트 (Rolling Update 트리거)
    apps_v1.patch_namespaced_deployment(
        name=name,
        namespace=namespace,
        body=deployment
    )
    
    return {
        "status": "success",
        "message": f"Deployment '{name}'이 재시작되었습니다. Pod들이 새로 생성됩니다.",
        "deployment": name,
        "namespace": namespace,
        "restart_method": "kubectl rollout restart"
    }
```

---

### 8️⃣ **`overview` - 통합 대시보드 조회**

#### **자연어 예시**
- "전체 상황 보여줘"
- "대시보드 확인"
- "모든 리소스 상태"
- "네임스페이스 전체 현황"
- "클러스터 상태 확인"

#### **특징**
- **통합 조회**: Deployment, Pod, Service, Ingress 모두 한번에
- **요약 통계**: 전체 리소스 개수와 상태 요약
- **네임스페이스별**: 특정 네임스페이스만 조회 가능

#### **실행 과정**
```python
async def _execute_get_overview(args: Dict[str, Any]) -> Dict[str, Any]:
    namespace = args.get("namespace", "default")
    
    # 1단계: 모든 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    core_v1 = get_core_v1_api()
    networking_v1 = get_networking_v1_api()
    
    overview_data = {
        "namespace": namespace,
        "deployments": [],
        "pods": [],
        "services": [],
        "ingresses": []
    }
    
    # 2단계: 각 리소스 타입별 조회
    # Deployments, Pods, Services, Ingresses 조회
    
    # 3단계: 요약 통계 생성
    summary = {
        "total_deployments": len(overview_data["deployments"]),
        "total_pods": len(overview_data["pods"]),
        "total_services": len(overview_data["services"]),
        "total_ingresses": len(overview_data["ingresses"]),
        "running_pods": len([p for p in overview_data["pods"] if p["phase"] == "Running"]),
        "ready_deployments": len([d for d in overview_data["deployments"] if d["status"] == "Running"])
    }
    
    return {
        "status": "success",
        "message": f"'{namespace}' 네임스페이스 통합 대시보드 조회 완료",
        "summary": summary,
        "resources": overview_data
    }
```

---

### 9️⃣ **`list_pods` - 파드 목록 조회**

#### **자연어 예시**
- "모든 파드 조회해줘"
- "파드 목록 보여줘"
- "실행 중인 파드들 확인"

#### **특징**
- **네임스페이스별 조회**: 특정 네임스페이스의 파드만 조회
- **상세한 상태 정보**: Ready 상태, 재시작 횟수, 실행 노드 포함
- **생성 시간**: Age 정보로 파드 생성 시점 확인

---

### 🔟 **`list_deployments` - 전체 Deployment 조회**

#### **자연어 예시**
- "모든 Deployment 조회해줘"
- "전체 앱 목록 보여줘"
- "모든 배포 확인"

#### **특징**
- **전체 클러스터**: 모든 네임스페이스의 Deployment 조회
- **상세한 정보**: Replica 상태, 이미지, 네임스페이스 포함

---

### 1️⃣1️⃣ **`list_services` - 전체 Service 조회**

#### **자연어 예시**
- "모든 Service 조회해줘"
- "전체 서비스 목록 보여줘"
- "모든 서비스 확인"

#### **특징**
- **서비스 타입별**: ClusterIP, LoadBalancer, NodePort 구분
- **포트 정보**: 각 서비스의 포트 매핑 정보 포함

---

### 1️⃣2️⃣ **`list_ingresses` - 전체 Ingress/도메인 조회**

#### **자연어 예시**
- "모든 도메인 조회해줘"
- "전체 Ingress 목록 보여줘"
- "모든 접속 주소 확인"

#### **특징**
- **도메인 중심**: 실제 접속 가능한 도메인 정보 제공
- **LoadBalancer 주소**: Ingress Controller의 외부 접속 주소 포함

---

### 1️⃣3️⃣ **`list_namespaces` - 네임스페이스 목록 조회**

#### **자연어 예시**
- "모든 네임스페이스 조회해줘"
- "네임스페이스 목록 보여줘"
- "전체 네임스페이스 확인"

#### **특징**
- **클러스터 전체**: 모든 네임스페이스 조회
- **생성 시간**: Age 정보로 네임스페이스 생성 시점 확인

---

### 1️⃣4️⃣ **`list_apps` - 네임스페이스 앱 목록 조회**

#### **자연어 예시**
- "test 네임스페이스 앱 목록 보여줘"
- "default 네임스페이스 모든 앱 확인"
- "특정 네임스페이스 앱 목록 조회"

#### **특징**
- **네임스페이스별**: 특정 네임스페이스의 앱만 조회
- **Deployment 중심**: 해당 네임스페이스의 모든 Deployment 정보

---

## 🆕 새 명령어 추가 방법

### **Step 1: Gemini 시스템 프롬프트 업데이트**
```python
# app/llm/gemini.py - _call_gemini_api() 메서드
system_prompt = """
15. 새로운 명령어 (command: "new_command")
설명: 새로운 기능에 대한 설명
기능: 구체적인 기능 설명
사용자 입력 예시: "예시 명령어", "다른 표현 방식"
필수 JSON 형식: { "command": "new_command", "parameters": { "param1": "<값1>", "param2": "<값2>", "namespace": "<추출된_네임스페이스_없으면_'default'>" } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 15가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
"""
```

### **Step 2: 명령 계획 추가**
```python
# app/services/commands.py - plan_command() 함수
elif command == "new_command":
    return CommandPlan(
        tool="k8s_new_command",
        args={
            "param1": req.param1,
            "namespace": req.namespace or ns
        }
    )
```

### **Step 3: 실행 로직 추가**
```python
# app/services/commands.py - execute_command() 함수
if plan.tool == "k8s_new_command":
    return await _execute_new_command(plan.args)

# 새로운 실행 함수 구현
async def _execute_new_command(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    새로운 명령어 실행 로직
    예: "새로운 기능 테스트"
    """
    param1 = args.get("param1")
    namespace = args.get("namespace", "default")
    
    try:
        # 1단계: 필요한 K8s API 클라이언트 획득
        core_v1 = get_core_v1_api()
        apps_v1 = get_apps_v1_api()
        networking_v1 = get_networking_v1_api()  # 필요시
        
        # 2단계: 실제 K8s API 호출
        # 예: 리소스 조회, 생성, 수정, 삭제 등
        
        # 3단계: 결과 가공 및 반환
        return {
            "status": "success",
            "message": "새로운 명령어가 성공적으로 실행되었습니다.",
            "data": {
                # 실제 결과 데이터
            }
        }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"리소스를 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"명령어 실행 실패: {str(e)}"}
```

---

## 🔄 공통 구현 패턴

### **1. 에러 처리 패턴**
```python
try:
    # K8s API 호출
    result = k8s_api_call()
    return {"status": "success", "data": result}
    
except ApiException as e:
    if e.status == 404:
        return {"status": "error", "message": f"리소스를 찾을 수 없습니다."}
    return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    
except Exception as e:
    return {"status": "error", "message": f"명령어 실행 실패: {str(e)}"}
```

### **2. K8s API 클라이언트 사용**
```python
# Apps V1 API (Deployment 관리)
apps_v1 = get_apps_v1_api()

# Core V1 API (Pod, Service, Node 관리)
core_v1 = get_core_v1_api()

# Networking V1 API (Ingress 관리)
networking_v1 = get_networking_v1_api()
```

### **3. 네임스페이스 처리**
```python
# 네임스페이스 존재 확인
try:
    core_v1.read_namespace(name=namespace)
except ApiException as e:
    if e.status == 404:
        return {
            "status": "error",
            "message": f"네임스페이스 '{namespace}'가 존재하지 않습니다."
        }
```

---

## 🧪 테스트 방법

### **1. API 테스트**
```bash
# 새로운 명령어 테스트
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "새로운 명령어 테스트",
       "timestamp": "2025-10-13T11:20:00Z",
       "context": {"project_name": "test"}
     }'
```

### **2. 개별 명령어 테스트**
```bash
# status 명령어
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{"command": "k-le-paas-test01-deploy 상태 확인해줘"}'

# logs 명령어
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{"command": "k-le-paas-test01-deploy 로그 50줄 보여줘"}'

# overview 명령어
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{"command": "전체 상황 보여줘"}'
```

---

## 🔧 트러블슈팅

### **자주 발생하는 문제들**

#### **1. Gemini가 명령어를 인식하지 못함**
```python
# 문제: Gemini가 "unknown" 반환
# 해결: 시스템 프롬프트에 더 많은 예시 추가

system_prompt = """
15. 새로운 명령어 (command: "new_command")
설명: 새로운 기능에 대한 설명
기능: 구체적인 기능 설명
사용자 입력 예시: 
- "예시 명령어"
- "다른 표현 방식"  
- "세 번째 표현"
- "네 번째 표현"
필수 JSON 형식: { "command": "new_command", "parameters": {} }
"""
```

#### **2. 네임스페이스 오류**
```python
# 문제: 존재하지 않는 네임스페이스 조회
# 해결: 네임스페이스 존재 확인

try:
    core_v1.read_namespace(name=namespace)
except ApiException as e:
    if e.status == 404:
        return {
            "status": "error",
            "namespace": namespace,
            "message": f"네임스페이스 '{namespace}'가 존재하지 않습니다. 네임스페이스 이름을 확인해주세요."
        }
```

#### **3. 로그 줄 수 제한**
```python
# 문제: 100줄 초과 요청
# 해결: API 레벨에서 검증

if req.lines > 100:
    raise HTTPException(status_code=400, detail="로그 줄 수는 최대 100줄까지 조회 가능합니다.")
```

---

## 📚 참고 자료

### **관련 문서**
- [NLP 실행 아키텍처](./execution.md) - 전체 시스템 아키텍처
- [NLP 퀵 스타트 가이드](./quick_start.md) - 빠른 시작 가이드

### **Kubernetes API 문서**
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)
- [Apps V1 API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#deployment-v1-apps)
- [Core V1 API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#pod-v1-core)
- [Networking V1 API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#ingress-v1-networking)

---

## 🔄 업데이트 이력

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| 1.0.0 | 2025-10-12 | 초기 8개 명령어 구현 가이드 작성 |
| 1.1.0 | 2025-10-12 | 상세 구현 과정 및 트러블슈팅 추가 |
| 2.0.0 | 2025-10-13 | 14개 명령어로 확장, 코드리뷰 반영, 아키텍처 개선 |

---

**작성자**: AI Assistant  
**최종 수정**: 2025-10-13  
**다음 업데이트**: 새 명령어 추가 시

> **💡 참고**: 이 문서는 새로운 명령어가 추가될 때마다 업데이트됩니다. 새로운 명령어를 구현한 후에는 반드시 이 문서에 추가해주세요!