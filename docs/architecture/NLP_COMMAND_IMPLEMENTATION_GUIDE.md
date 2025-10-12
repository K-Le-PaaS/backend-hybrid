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
- **`app/api/v1/nlp.py`**: API 엔드포인트 및 오케스트레이션

---

## 📊 현재 구현된 명령어 목록

| 번호 | 명령어 | 자연어 예시 | 구현 상태 | 주요 기능 |
|------|--------|-------------|-----------|-----------|
| 1 | **`status`** | "nginx 상태 확인해줘" | ✅ 완전 구현 | 앱 상태, 파드 정보 조회 |
| 2 | **`logs`** | "nginx 로그 20줄 보여줘" | ✅ 완전 구현 | 앱 로그 조회 |
| 3 | **`scale`** | "nginx 스케일 3개로 늘려줘" | ✅ 완전 구현 | 파드 개수 조정 |
| 4 | **`restart`** | "nginx 재시작해줘" | ✅ 완전 구현 | 앱 재시작 |
| 5 | **`rollback`** | "v1.1 버전으로 롤백해줘" | ✅ 완전 구현 | 이전 버전으로 되돌리기 |
| 6 | **`endpoint`** | "nginx 접속 주소 알려줘" | ✅ 완전 구현 | 서비스 엔드포인트 조회 |
| 7 | **`deploy`** | "배포해줘" | ✅ 완전 구현 | 새 애플리케이션 배포 |
| 8 | **`list_pods`** | "모든 파드 조회해줘" | ✅ 완전 구현 | 파드 목록 조회 |

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
    "appName": "nginx"  # 앱 이름 (선택사항, 없으면 "app" 기본값)
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="status",
    app_name="nginx",      # 또는 "" (빈 문자열)
    replicas=1,           # status에서는 사용 안함
    lines=30,             # status에서는 사용 안함
    version=""            # status에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
# plan_command()에서 생성
CommandPlan(
    tool="k8s_get_status",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default"     # 네임스페이스 (고정)
    }
)
```

#### **실행 과정**
```python
async def _execute_get_status(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Apps V1 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    
    # 2단계: Deployment 정보 조회
    deployment = apps_v1.read_namespaced_deployment(
        name=name, 
        namespace=namespace
    )
    
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

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "deployment": {
    "name": "nginx",
    "replicas": {"desired": 3, "current": 3, "ready": 3, "available": 3},
    "image": "nginx:1.21",
    "created_at": "2025-10-12T00:50:00Z"
  },
  "pods": [
    {
      "name": "nginx-xxx-1",
      "phase": "Running",
      "ready": true,
      "restarts": 0
    }
  ]
}
```

---

### 2️⃣ **`logs` - 로그 조회**

#### **자연어 예시**
- "nginx 로그 20줄 보여줘"
- "최신 로그 100줄 보여줘"
- "로그 확인"
- "에러 로그 찾아줘"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "logs",
  "parameters": {
    "appName": "nginx",    # 앱 이름
    "lines": 20            # 로그 줄 수 (기본값: 30)
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="logs",
    app_name="nginx",
    replicas=1,           # logs에서는 사용 안함
    lines=20,             # 실제 사용됨
    version=""            # logs에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_get_logs",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default",    # 네임스페이스
        "lines": 20               # 로그 줄 수
    }
)
```

#### **실행 과정**
```python
async def _execute_get_logs(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    lines = args.get("lines", 30) # 20
    
    # 1단계: Core V1 API 클라이언트 획득
    core_v1 = get_core_v1_api()
    
    # 2단계: Deployment와 연결된 Pod 찾기
    pods = core_v1.list_namespaced_pod(
        namespace=namespace, 
        label_selector=f"app={name}"  # "app=nginx"
    )
    
    # 3단계: Pod 존재 확인
    if not pods.items:
        return {"status": "error", "message": f"'{name}' 관련 Pod를 찾을 수 없습니다."}
    
    # 4단계: 첫 번째 Pod의 로그 조회
    pod_name = pods.items[0].metadata.name  # "nginx-xxx-1"
    logs = core_v1.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        tail_lines=lines  # 20줄
    )
    
    # 5단계: 로그 반환
    return {
        "status": "success",
        "pod_name": pod_name,
        "lines": lines,
        "logs": logs  # 실제 로그 내용
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "pod_name": "nginx-xxx-1",
  "lines": 20,
  "logs": "2025-10-12 00:50:00 [info] Starting nginx...\n2025-10-12 00:50:01 [info] nginx started"
}
```

---

### 3️⃣ **`scale` - 스케일링**

#### **자연어 예시**
- "nginx 스케일 3개로 늘려줘"
- "서버 3대로 늘려줘"
- "chat-app 스케일 아웃"
- "서버 1개로 줄여"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "scale",
  "parameters": {
    "appName": "nginx",    # 앱 이름
    "replicas": 3          # 목표 레플리카 수
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="scale",
    app_name="nginx",
    replicas=3,            # 실제 사용됨
    lines=30,              # scale에서는 사용 안함
    version=""             # scale에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_scale_deployment",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default",    # 네임스페이스
        "replicas": 3             # 목표 레플리카 수
    }
)
```

#### **실행 과정**
```python
async def _execute_scale(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    replicas = args["replicas"]   # 3
    
    # 1단계: Apps V1 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    
    # 2단계: 스케일링 요청 body 생성
    body = {
        "spec": {
            "replicas": replicas  # 3
        }
    }
    
    # 3단계: Deployment 스케일 업데이트
    apps_v1.patch_namespaced_deployment_scale(
        name=name,                # "nginx"
        namespace=namespace,      # "default"
        body=body                 # {"spec": {"replicas": 3}}
    )
    
    # 4단계: 성공 응답 반환
    return {
        "status": "success",
        "message": f"Deployment '{name}'의 replicas를 {replicas}개로 변경했습니다.",
        "deployment": name,
        "replicas": replicas
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "message": "Deployment 'nginx'의 replicas를 3개로 변경했습니다.",
  "deployment": "nginx",
  "replicas": 3
}
```

---

### 4️⃣ **`restart` - 재시작**

#### **자연어 예시**
- "nginx 재시작해줘"
- "앱 재시작해줘"
- "chat-app 껐다 켜줘"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "restart",
  "parameters": {
    "appName": "nginx"     # 앱 이름
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="restart",
    app_name="nginx",
    replicas=1,            # restart에서는 사용 안함
    lines=30,              # restart에서는 사용 안함
    version=""             # restart에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_restart_deployment",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default"     # 네임스페이스
    }
)
```

#### **실행 과정**
```python
async def _execute_restart(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Apps V1 API 클라이언트 획득
    apps_v1 = get_apps_v1_api()
    
    # 2단계: Deployment 조회
    deployment = apps_v1.read_namespaced_deployment(
        name=name, 
        namespace=namespace
    )
    
    # 3단계: Pod template에 재시작 annotation 추가
    if deployment.spec.template.metadata.annotations is None:
        deployment.spec.template.metadata.annotations = {}
    
    # 재시작 시간을 annotation에 추가
    deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now(timezone.utc).isoformat()
    
    # 4단계: Deployment 업데이트 (annotation 변경으로 Pod 재생성 트리거)
    apps_v1.patch_namespaced_deployment(
        name=name,
        namespace=namespace,
        body=deployment  # 수정된 Deployment 객체
    )
    
    # 5단계: 성공 응답 반환
    return {
        "status": "success",
        "message": f"Deployment '{name}'이 재시작되었습니다.",
        "deployment": name,
        "namespace": namespace
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "message": "Deployment 'nginx'이 재시작되었습니다.",
  "deployment": "nginx",
  "namespace": "default"
}
```

---

### 5️⃣ **`rollback` - 롤백**

#### **자연어 예시**
- "v1.1 버전으로 롤백해줘"
- "이전 배포로 되돌려"
- "nginx v2.0으로 롤백"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "rollback",
  "parameters": {
    "appName": "nginx",    # 앱 이름
    "version": "v1.1"      # 롤백할 버전 태그
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="rollback",
    app_name="nginx",
    replicas=1,            # rollback에서는 사용 안함
    lines=30,              # rollback에서는 사용 안함
    version="v1.1"         # 실제 사용됨
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_rollback_deployment",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default",    # 네임스페이스
        "version": "v1.1"         # 롤백할 버전
    }
)
```

#### **실행 과정**
```python
async def _execute_rollback(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    version = args.get("version") # "v1.1"
    
    if version:
        # 1단계: Apps V1 API 클라이언트 획득
        apps_v1 = get_apps_v1_api()
        
        # 2단계: Deployment 조회
        deployment = apps_v1.read_namespaced_deployment(
            name=name, 
            namespace=namespace
        )
        
        # 3단계: 현재 이미지 태그에서 버전 추출
        current_image = deployment.spec.template.spec.containers[0].image
        # 예: "nginx:1.21" → image_base = "nginx"
        image_base = current_image.rsplit(":", 1)[0]
        
        # 4단계: 새 이미지 태그 생성
        new_image = f"{image_base}:{version}"  # "nginx:v1.1"
        
        # 5단계: Deployment의 컨테이너 이미지 변경
        deployment.spec.template.spec.containers[0].image = new_image
        
        # 6단계: Deployment 업데이트
        apps_v1.patch_namespaced_deployment(
            name=name,
            namespace=namespace,
            body=deployment
        )
        
        # 7단계: 성공 응답 반환
        return {
            "status": "success",
            "message": f"Deployment '{name}'을 {version} 버전으로 롤백했습니다.",
            "deployment": name,
            "version": version,
            "image": new_image
        }
    else:
        return {
            "status": "error",
            "message": "버전을 명시해주세요. 예: 'v1.0으로 롤백'"
        }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "message": "Deployment 'nginx'을 v1.1 버전으로 롤백했습니다.",
  "deployment": "nginx",
  "version": "v1.1",
  "image": "nginx:v1.1"
}
```

---

### 6️⃣ **`endpoint` - 엔드포인트 조회**

#### **자연어 예시**
- "nginx 접속 주소 알려줘"
- "내 앱 접속 주소 알려줘"
- "서비스 URL 뭐야?"
- "앱 URL 확인"
- "접속 주소 보여줘"
- "서비스 주소 알려줘"
- "엔드포인트 확인"
- "외부 접속 주소"
- "인그레스 URL"
- "로드밸런서 주소"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "endpoint",
  "parameters": {
    "appName": "nginx"     # 앱 이름
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="endpoint",
    app_name="nginx",
    replicas=1,            # endpoint에서는 사용 안함
    lines=30,              # endpoint에서는 사용 안함
    version=""             # endpoint에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_get_endpoints",
    args={
        "name": "nginx",           # 앱 이름
        "namespace": "default"     # 네임스페이스
    }
)
```

#### **실행 과정**
```python
async def _execute_get_endpoints(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args["name"]           # "nginx"
    namespace = args["namespace"] # "default"
    
    # 1단계: Core V1 API 클라이언트 획득
    core_v1 = get_core_v1_api()
    
    # 2단계: Service 조회
    service = core_v1.read_namespaced_service(
        name=name, 
        namespace=namespace
    )
    
    # 3단계: 서비스 타입 및 포트 정보 추출
    service_type = service.spec.type  # "LoadBalancer", "NodePort", "ClusterIP"
    ports = service.spec.ports        # 포트 정보 리스트
    
    # 4단계: 서비스 타입별 엔드포인트 생성
    endpoints = []
    
    if service_type == "LoadBalancer":
        # LoadBalancer의 외부 IP/Hostname 사용
        for ingress in service.status.load_balancer.ingress:
            ip_or_host = ingress.ip or ingress.hostname
            for port in ports:
                endpoints.append(f"http://{ip_or_host}:{port.port}")
    
    elif service_type == "NodePort":
        # Node IP + NodePort 사용
        nodes = core_v1.list_node()
        node_ip = nodes.items[0].status.addresses[0].address
        for port in ports:
            if port.node_port:
                endpoints.append(f"http://{node_ip}:{port.node_port}")
    
    else:  # ClusterIP
        # 클러스터 내부 전용
        cluster_ip = service.spec.cluster_ip
        for port in ports:
            endpoints.append(f"http://{cluster_ip}:{port.port} (클러스터 내부 전용)")
    
    # 5단계: 결과 반환
    return {
        "status": "success",
        "service_name": name,
        "service_type": service_type,
        "endpoints": endpoints if endpoints else ["서비스 엔드포인트를 찾을 수 없습니다."]
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "service_name": "nginx",
  "service_type": "LoadBalancer",
  "endpoints": [
    "http://192.168.1.100:80",
    "http://192.168.1.100:443"
  ]
}
```

---

### 7️⃣ **`deploy` - 배포**

#### **자연어 예시**
- "배포해줘"
- "최신 코드로 업데이트해줘"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "deploy",
  "parameters": {
    "appName": "my-app"     # 앱 이름
  }
}

# CommandRequest로 변환
req = CommandRequest(
    command="deploy",
    app_name="my-app",
    replicas=1,             # deploy에서는 사용 안함 (기본값 2)
    lines=30,               # deploy에서는 사용 안함
    version=""              # deploy에서는 사용 안함 (latest 사용)
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="deploy_application",
    args={
        "app_name": "my-app",        # 앱 이름
        "environment": "staging",    # 환경 (고정)
        "image": "my-app:latest",    # 이미지 태그
        "replicas": 2,              # 레플리카 수 (고정)
    }
)
```

#### **실행 과정**
```python
# deploy_application() 함수 (deployments.py에서 구현)
# NCP SourceBuild/SourceDeploy 연동

async def deploy_application(args: Dict[str, Any]) -> Dict[str, Any]:
    app_name = args["app_name"]      # "my-app"
    environment = args["environment"] # "staging"
    image = args["image"]            # "my-app:latest"
    replicas = args["replicas"]      # 2
    
    # 1단계: NCP SourceBuild 트리거
    # 2단계: 이미지 빌드 대기
    # 3단계: NCP SourceDeploy로 배포
    # 4단계: 배포 상태 확인
    
    return {
        "status": "success",
        "message": "배포가 완료되었습니다.",
        "deployment": {
            "name": app_name,
            "image": image,
            "replicas": replicas
        }
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "message": "배포가 완료되었습니다.",
  "deployment": {
    "name": "my-app",
    "image": "my-app:latest",
    "replicas": 2
  }
}
```

---

### 8️⃣ **`list_pods` - 파드 목록 조회**

#### **자연어 예시**
- "모든 파드 조회해줘"
- "파드 목록 보여줘"
- "실행 중인 파드들 확인"

#### **필요한 값 (Parameters)**
```python
# Gemini에서 추출되는 값
{
  "command": "list_pods",
  "parameters": {}         # 파라미터 없음 (네임스페이스 전체 조회)
}

# CommandRequest로 변환
req = CommandRequest(
    command="list_pods",
    app_name="",           # list_pods에서는 사용 안함
    replicas=1,            # list_pods에서는 사용 안함
    lines=30,              # list_pods에서는 사용 안함
    version=""             # list_pods에서는 사용 안함
)
```

#### **CommandPlan 생성**
```python
CommandPlan(
    tool="k8s_list_pods",
    args={
        "namespace": "default"     # 네임스페이스 (고정)
    }
)
```

#### **실행 과정**
```python
async def _execute_list_pods(args: Dict[str, Any]) -> Dict[str, Any]:
    namespace = args.get("namespace", "default")  # "default"
    
    # 1단계: Core V1 API 클라이언트 획득
    core_v1 = get_core_v1_api()
    
    # 2단계: 네임스페이스의 모든 파드 조회
    pods = core_v1.list_namespaced_pod(namespace=namespace)
    
    # 3단계: 각 파드 정보 추출 및 가공
    pod_list = []
    for pod in pods.items:
        pod_info = {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "ready": False,
            "restarts": 0,
            "age": None,
            "node": pod.spec.node_name if pod.spec else None
        }
        
        # 4단계: 컨테이너 상태 체크
        if pod.status.container_statuses:
            ready_count = 0
            total_count = len(pod.status.container_statuses)
            total_restarts = 0
            
            for container_status in pod.status.container_statuses:
                if container_status.ready:
                    ready_count += 1
                total_restarts += container_status.restart_count
            
            pod_info["ready"] = f"{ready_count}/{total_count}"  # "1/1"
            pod_info["restarts"] = total_restarts
        
        # 5단계: Pod 생성 시간 계산
        if pod.metadata.creation_timestamp:
            now = datetime.now(timezone.utc)
            age = now - pod.metadata.creation_timestamp
            pod_info["age"] = str(age).split('.')[0]  # "5:14:49"
        
        pod_list.append(pod_info)
    
    # 6단계: 결과 반환
    return {
        "status": "success",
        "namespace": namespace,
        "total_pods": len(pod_list),
        "pods": pod_list
    }
```

#### **반환 데이터 구조**
```json
{
  "status": "success",
  "namespace": "default",
  "total_pods": 2,
  "pods": [
    {
      "name": "nginx-xxx-1",
      "namespace": "default",
      "phase": "Running",
      "ready": "1/1",
      "restarts": 0,
      "age": "5:14:49",
      "node": "contest-27-node-w-2efc"
    },
    {
      "name": "busybox",
      "namespace": "default",
      "phase": "Running",
      "ready": "1/1",
      "restarts": 0,
      "age": "25 days, 19:59:53",
      "node": "contest-27-node-w-2efc"
    }
  ]
}
```

---

## 🆕 새 명령어 추가 방법

### **Step 1: Gemini 시스템 프롬프트 업데이트**
```python
# app/llm/gemini.py - _call_gemini_api() 메서드
system_prompt = """
9. 새로운 명령어 (command: "new_command")
설명: 새로운 기능에 대한 설명
사용자 입력 예시: "예시 명령어", "다른 표현 방식"
필수 JSON 형식: { "command": "new_command", "parameters": { "param1": "<값1>", "param2": <값2> } }

일반 규칙:
- 사용자의 의도가 불분명하거나 위 8가지 명령어 중 어느 것과도 일치하지 않으면: { "command": "unknown", "parameters": { "query": "<사용자_원본_입력>" } }
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
            "namespace": ns
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

### **Step 4: 메시지 맵 업데이트**
```python
# app/llm/gemini.py - interpret() 메서드
messages = {
    # ... 기존 메시지들
    "new_command": "새로운 명령을 해석했습니다."
}
```

### **Step 5: 테스트**
```bash
# API 테스트
curl -X POST "http://127.0.0.1:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "새로운 기능 테스트",
       "timestamp": "2025-10-12T00:50:00Z"
     }'
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

### **2. 응답 데이터 구조**
```python
# 성공 응답
{
    "status": "success",
    "message": "명령어가 성공적으로 실행되었습니다.",
    "data": {
        # 실제 결과 데이터
    }
}

# 에러 응답
{
    "status": "error",
    "message": "구체적인 에러 메시지"
}
```

### **3. K8s API 클라이언트 사용**
```python
# Apps V1 API (Deployment 관리)
apps_v1 = get_apps_v1_api()

# Core V1 API (Pod, Service, Node 관리)
core_v1 = get_core_v1_api()

# Networking V1 API (Ingress 관리)
networking_v1 = get_networking_v1_api()
```

---

## 🧪 테스트 방법

### **1. 단위 테스트**
```python
# tests/test_nlp_commands.py
import pytest
from app.services.commands import plan_command, CommandRequest
from app.llm.gemini import GeminiClient

@pytest.mark.asyncio
async def test_new_command_parsing():
    gemini_client = GeminiClient()
    result = await gemini_client.interpret("새로운 명령어 테스트")
    assert result["intent"] == "new_command"

def test_new_command_planning():
    req = CommandRequest(
        command="new_command",
        app_name="test-app",
        replicas=1,
        lines=30,
        version=""
    )
    plan = plan_command(req)
    assert plan.tool == "k8s_new_command"
    assert plan.args["param1"] == "test-app"
```

### **2. 통합 테스트**
```python
@pytest.mark.asyncio
async def test_new_command_execution():
    from app.services.commands import _execute_new_command
    
    args = {"param1": "test-app", "namespace": "default"}
    result = await _execute_new_command(args)
    
    assert result["status"] == "success"
    assert "data" in result
```

### **3. API 테스트**
```bash
# 새로운 명령어 테스트
curl -X POST "http://127.0.0.1:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "새로운 명령어 테스트",
       "timestamp": "2025-10-12T00:50:00Z"
     }'
```

---

## 🔧 트러블슈팅

### **자주 발생하는 문제들**

#### **1. Gemini가 명령어를 인식하지 못함**
```python
# 문제: Gemini가 "unknown" 반환
# 해결: 시스템 프롬프트에 더 많은 예시 추가

system_prompt = """
9. 새로운 명령어 (command: "new_command")
설명: 새로운 기능에 대한 설명
사용자 입력 예시: 
- "예시 명령어"
- "다른 표현 방식"  
- "세 번째 표현"
- "네 번째 표현"
필수 JSON 형식: { "command": "new_command", "parameters": {} }
"""
```

#### **2. K8s API 호출 실패**
```python
# 문제: 404 에러 또는 권한 오류
# 해결: 리소스 존재 확인 및 권한 체크

try:
    # 리소스 존재 확인
    resource = k8s_api.read_namespaced_resource(name=name, namespace=namespace)
except ApiException as e:
    if e.status == 404:
        return {"status": "error", "message": f"리소스 '{name}'을 찾을 수 없습니다."}
    elif e.status == 403:
        return {"status": "error", "message": "권한이 없습니다."}
    raise
```

#### **3. 응답 데이터 형식 오류**
```python
# 문제: JSON 직렬화 오류
# 해결: datetime 객체를 문자열로 변환

from datetime import datetime, timezone

# 문제가 되는 코드
return {
    "created_at": pod.metadata.creation_timestamp  # datetime 객체
}

# 해결된 코드
return {
    "created_at": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
}
```

---

## 📚 참고 자료

### **관련 문서**
- [NLP 실행 아키텍처](./NLP_EXECUTION_ARCHITECTURE.md) - 전체 시스템 아키텍처
- [NLP 퀵 스타트 가이드](./NLP_QUICK_START_GUIDE.md) - 빠른 시작 가이드

### **Kubernetes API 문서**
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)
- [Apps V1 API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#deployment-v1-apps)
- [Core V1 API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#pod-v1-core)

### **개발 도구**
- **API 테스트**: Postman, curl
- **디버깅**: 로그 확인, K8s 클러스터 상태 체크
- **모니터링**: kubectl 명령어로 실시간 상태 확인

---

## 🔄 업데이트 이력

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| 1.0.0 | 2025-10-12 | 초기 8개 명령어 구현 가이드 작성 |
| 1.1.0 | 2025-10-12 | 상세 구현 과정 및 트러블슈팅 추가 |

---

**작성자**: AI Assistant  
**최종 수정**: 2025-10-12  
**다음 업데이트**: 새 명령어 추가 시

> **💡 참고**: 이 문서는 새로운 명령어가 추가될 때마다 업데이트됩니다. 새로운 명령어를 구현한 후에는 반드시 이 문서에 추가해주세요!
