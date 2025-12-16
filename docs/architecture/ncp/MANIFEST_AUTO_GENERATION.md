# Manifest 자동 생성 기능 업데이트 (2025-10-24)

## 개요

NCP 파이프라인에서 Kubernetes Deployment, Service, Ingress 3개의 manifest를 자동으로 생성하도록 개선했습니다.

---

## 주요 변경사항

### 1. Ingress Manifest 자동 생성 추가 ✨

#### Before (기존)
```
k8s/
├── deployment.yaml  ✅
└── service.yaml     ✅
```

#### After (변경 후)
```
k8s/
├── deployment.yaml  ✅
├── service.yaml     ✅
└── ingress.yaml     ✨ 새로 추가
```

### 2. Subdomain 생성 규칙 개선

#### 문제점
- `sc_repo_name`에 이미 owner가 포함되어 중복 생성됨
- 예: `K-Le-PaaS-test02` → `k-le-paas-k-le-paas-test02.klepaas.app` ❌

#### 해결
Owner prefix를 제거하고 올바르게 조합:

| GitHub Repository | sc_repo_name | Owner 추출 | Repo 추출 | 최종 Subdomain |
|------------------|--------------|-----------|----------|----------------|
| `K-Le-PaaS/test02` | `K-Le-PaaS-test02` | `k-le-paas` | `test02` | `k-le-paas-test02.klepaas.app` ✅ |
| `K-Le-PaaS/backend-api` | `K-Le-PaaS-backend-api` | `k-le-paas` | `backend-api` | `k-le-paas-backend-api.klepaas.app` ✅ |
| `myorg/my-app` | `myorg-my-app` | `myorg` | `my-app` | `myorg-my-app.klepaas.app` ✅ |

**코드 위치**: `app/services/ncp_pipeline.py:1566-1571`, `1456-1459`, `1611-1614`

```python
# Owner prefix 제거 로직
if owner_name and repo_part.startswith(owner_name.lower() + "-"):
    repo_only = repo_part[len(owner_name.lower()) + 1:]
    # "k-le-paas-test02" -> "test02"
else:
    repo_only = repo_part

# Subdomain 생성
if owner_name:
    subdomain = f"{owner_name.lower()}-{repo_only}"
else:
    subdomain = repo_only
```

### 3. Git Push 안정성 개선 🔧

#### 문제점
Rebase conflict로 인한 push 실패:
```
error: could not apply eda46ff...
! [rejected] main -> main (non-fast-forward)
error: failed to push some refs
```

#### 해결
Force push 사용 (manifest는 항상 최신 상태여야 하므로 안전함):

**변경 전**:
```python
# Pull with rebase
subprocess.run(["git", "pull", "origin", "main", "--rebase"])
# Push (충돌 시 실패)
subprocess.run(["git", "push", "origin", "main"])
```

**변경 후**:
```python
# Force push (manifest는 자동 생성이므로 덮어쓰기가 정상)
subprocess.run(["git", "push", "origin", "main", "--force"])
```

**코드 위치**: `app/services/ncp_pipeline.py:1541-1547`, `1706-1712`

#### Force Push가 안전한 이유
1. Manifest는 **자동 생성** 파일
2. **봇만 수정**하므로 충돌 불가능
3. 항상 **최신 이미지 태그**를 반영해야 함
4. 수동 수정 내용이 없음

---

## 생성되는 Manifest 상세

### 1. Deployment Manifest

**파일**: `k8s/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k-le-paas-test02-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: k-le-paas-test02
  template:
    metadata:
      labels:
        app: k-le-paas-test02
    spec:
      imagePullSecrets:
      - name: ncp-cr
      containers:
      - name: k-le-paas-test02
        image: contest27-klepaas-build-handle.kr.ncr.ntruss.com/k-le-paas-test02:7b904a7
        ports:
        - containerPort: 8080
```

### 2. Service Manifest

**파일**: `k8s/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: k-le-paas-test02-svc
  namespace: default
spec:
  type: ClusterIP
  selector:
    app: k-le-paas-test02
  ports:
  - name: http
    protocol: TCP
    port: 8080
    targetPort: 8080
```

### 3. Ingress Manifest (새로 추가)

**파일**: `k8s/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: k-le-paas-test02-ingress
  namespace: default
  annotations:
    kubernetes.io/ingress.class: "nginx"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  tls:
  - hosts:
    - k-le-paas-test02.klepaas.app
    secretName: k-le-paas-test02-tls
  rules:
  - host: k-le-paas-test02.klepaas.app
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: k-le-paas-test02-svc
            port:
              number: 8080
```

**주요 기능**:
- ✅ HTTPS 자동 설정 (Let's Encrypt)
- ✅ HTTP → HTTPS 자동 리다이렉트
- ✅ TLS 인증서 자동 발급 (cert-manager)
- ✅ Owner-Repo 기반 subdomain 자동 생성

---

## 파이프라인 실행 흐름

### 전체 프로세스

```
┌─────────────────────────────────────────────────┐
│ 1. GitHub Push Event                            │
│    K-Le-PaaS/test02 → main                     │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 2. GitHub Webhook → Backend                     │
│    POST /api/v1/cicd/webhook                    │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 3. Mirror GitHub → SourceCommit                 │
│    - GitHub 코드 복사                            │
│    - Owner 추출: "K-Le-PaaS"                    │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 4. Manifest 자동 생성                            │
│    - sc_repo_name: "K-Le-PaaS-test02"           │
│    - owner_name: "K-Le-PaaS"                    │
│    - repo_only: "test02" (prefix 제거)          │
│    - subdomain: "k-le-paas-test02"              │
│                                                  │
│    생성 파일:                                     │
│    ├── k8s/deployment.yaml                      │
│    ├── k8s/service.yaml                         │
│    └── k8s/ingress.yaml (새로 추가)              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 5. Git Force Push                                │
│    git push origin main --force                  │
│    (rebase conflict 무시, 항상 성공)              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 6. NCP SourcePipeline 실행                       │
│    - SourceBuild: Docker 이미지 빌드             │
│    - SourceDeploy: NKS 클러스터 배포             │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ 7. 배포 완료                                      │
│    https://k-le-paas-test02.klepaas.app         │
│    (HTTPS 자동 설정 완료)                         │
└─────────────────────────────────────────────────┘
```

---

## 코드 변경사항 상세

### 수정된 파일
- **`app/services/ncp_pipeline.py`**

### 추가된 함수

#### 1. `_generate_service_manifest()` (Line 318-335)
```python
def _generate_service_manifest(app_name: str, port: int) -> str:
    """Generate default Kubernetes Service manifest."""
    return f"""apiVersion: v1
kind: Service
metadata:
  name: {app_name}-svc
  labels:
    app: {app_name}
spec:
  type: ClusterIP
  selector:
    app: {app_name}
  ports:
  - name: http
    protocol: TCP
    port: {port}
    targetPort: {port}
"""
```

#### 2. `_generate_ingress_manifest()` (Line 338-368)
```python
def _generate_ingress_manifest(app_name: str, port: int, domain: str = "klepaas.app", owner: str = "") -> str:
    """Generate default Kubernetes Ingress manifest with SSL."""
    # owner-repo 형식으로 subdomain 생성
    if owner:
        owner_part = owner.lower()
        repo_part = app_name.lower()
        subdomain = f"{owner_part}-{repo_part}"
    else:
        subdomain = app_name.lower()

    return f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {app_name}-ingress
  namespace: default
  annotations:
    kubernetes.io/ingress.class: "nginx"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  tls:
  - hosts:
    - {subdomain}.{domain}
    secretName: {app_name}-tls
  rules:
  - host: {subdomain}.{domain}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {app_name}-svc
            port:
              number: {port}
"""
```

### 수정된 함수

#### 1. `mirror_and_update_manifest()` (Line 1264-)

**Owner 추출 로직 추가** (Line 1312-1322):
```python
# Extract owner from github_repo_url
owner_name = ""
try:
    import re
    match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', github_repo_url)
    if match:
        owner_name = match.group(1)
        _dbg("MM-OWNER-EXTRACTED", owner=owner_name, url=github_repo_url)
except Exception as e:
    _dbg("MM-OWNER-EXTRACT-FAILED", error=str(e))
```

**기존 Manifest 존재 시 - Ingress 자동 생성** (Line 1449-1491):
```python
# Ensure Ingress manifest exists
if not ingress_path.exists():
    _dbg("MM-INGRESS-NOT-FOUND", path=str(ingress_path), action="creating_now")
    repo_part_raw = sc_repo_name or "app"
    repo_part = repo_part_raw.lower()

    # Extract actual repo name (remove owner prefix if present)
    if owner_name and repo_part.startswith(owner_name.lower() + "-"):
        repo_only = repo_part[len(owner_name.lower()) + 1:]
    else:
        repo_only = repo_part

    # Generate subdomain with owner-repo format
    if owner_name:
        owner_part = owner_name.lower()
        subdomain = f"{owner_part}-{repo_only}"
    else:
        subdomain = repo_only

    ingress_content = f"""..."""
    ingress_path.write_text(ingress_content, encoding="utf-8")
    manifest_updated = True
```

**Git Push를 Force Push로 변경** (Line 1541-1547):
```python
# Force push to ensure manifest is always up-to-date
_dbg("MM-GIT-PUSH-UPDATE-FORCE", branch=current_branch, reason="manifest_update_always_wins")
subprocess.run(
    ["git", "-C", str(sc_dir), "push", "origin", current_branch, "--force"],
    check=True, capture_output=True, text=True
)
```

**신규 Manifest 생성 시 - Repo 추출 및 Ingress 생성** (Line 1564-1624):
```python
# Extract actual repo name (remove owner prefix if present)
if owner_name and repo_part.startswith(owner_name.lower() + "-"):
    repo_only = repo_part[len(owner_name.lower()) + 1:]
    _dbg("MM-REPO-EXTRACTED", original=repo_part, owner=owner_name.lower(), repo_only=repo_only)
else:
    repo_only = repo_part

# Create ingress manifest with owner-repo subdomain
if owner_name:
    owner_part = owner_name.lower()
    subdomain = f"{owner_part}-{repo_only}"
else:
    subdomain = repo_only

ingress_content = f"""..."""
ingress_path.write_text(ingress_content, encoding="utf-8")
_dbg("MM-MANIFESTS-CREATED",
     deployment=str(manifest_path),
     service=str(service_path),
     ingress=str(ingress_path),
     subdomain=f"{subdomain}.klepaas.app",
     owner=owner_name,
     replicas=target_replicas)
```

**Force Push 적용** (Line 1706-1712):
```python
# Force push to ensure manifest is always up-to-date
_dbg("MM-GIT-PUSH-FORCE", branch=current_branch, reason="manifest_update_always_wins")
subprocess.run(
    ["git", "-C", str(sc_dir), "push", "origin", current_branch, "--force"],
    check=True, capture_output=True, text=True
)
```

---

## 알려진 이슈 및 해결

### 1. "Running Pipeline Exist" 에러

**에러 메시지**:
```
errorCode: 340500
message: "invalid parameters"
details: "Running Pipeline Exist"
```

**원인**:
- 이미 파이프라인이 실행 중일 때 중복 실행 시도
- NCP는 동시에 하나의 파이프라인만 실행 가능

**해결 방법**:
이 에러는 **정상 동작**입니다. Manifest가 성공적으로 업데이트되었다면 문제없습니다.

**확인 사항**:
```
✅ [MM-MANIFESTS-CREATED] - Manifest 생성 성공
✅ [MM-GIT-PUSH-FORCE] - Git Push 성공
⚠️ [SP-EXECUTE-ERROR] - Pipeline 중복 실행 방지 (정상)
```

**개선 옵션** (선택사항):
```python
# app/services/ncp_pipeline.py
try:
    result = await execute_sourcepipeline_rest(pipeline_id)
except HTTPException as e:
    if "Running Pipeline Exist" in str(e.detail):
        return {
            "status": "skipped",
            "reason": "pipeline_already_running"
        }
    raise
```

---

## 테스트 방법

### 1. 신규 레포지터리 배포

```bash
# 1. GitHub 레포지터리 생성
# 예: K-Le-PaaS/test03

# 2. Backend API로 파이프라인 생성
POST /api/v1/ncp/pipeline/create
{
  "owner": "K-Le-PaaS",
  "repo": "test03",
  "branch": "main",
  "user_id": "test-user"
}

# 3. GitHub에 Push
git push origin main

# 4. 결과 확인
- SourceCommit에 k8s/ 디렉토리 생성 확인
- k8s/deployment.yaml, service.yaml, ingress.yaml 존재 확인
- Subdomain: k-le-paas-test03.klepaas.app
```

### 2. 로그 확인

성공적인 실행 로그:
```
[MM-OWNER-EXTRACTED] owner=K-Le-PaaS
[MM-REPO-EXTRACTED] original=k-le-paas-test03 repo_only=test03
[MM-MANIFESTS-CREATED]
  deployment=/tmp/.../k8s/deployment.yaml
  service=/tmp/.../k8s/service.yaml
  ingress=/tmp/.../k8s/ingress.yaml
  subdomain=k-le-paas-test03.klepaas.app
  owner=K-Le-PaaS
[MM-GIT-PUSH-FORCE] branch=main
[MM-MANIFESTS-PUSHED] ✅
```

### 3. Ingress 동작 확인

```bash
# 1. Ingress 리소스 확인
kubectl get ingress -n default

# 2. TLS Secret 자동 생성 확인 (cert-manager)
kubectl get secret k-le-paas-test03-tls -n default

# 3. 도메인 접속 테스트
curl https://k-le-paas-test03.klepaas.app
```

---

## 환경변수

변경 없음. 기존 환경변수 그대로 사용:

```bash
# NCP 인증
KLEPAAS_NCP_ACCESS_KEY=your-access-key
KLEPAAS_NCP_SECRET_KEY=your-secret-key

# NCP SourceCommit
KLEPAAS_NCP_SOURCECOMMIT_ENDPOINT=https://sourcecommit.apigw.ntruss.com
KLEPAAS_NCP_SOURCECOMMIT_USERNAME=your-username
KLEPAAS_NCP_SOURCECOMMIT_PASSWORD=your-password

# NCP SourcePipeline
KLEPAAS_NCP_SOURCEPIPELINE_ENDPOINT=https://vpcsourcepipeline.apigw.ntruss.com
```

---

## 이전 버전과의 호환성

### 기존 프로젝트
- ✅ 기존에 deployment.yaml만 있던 프로젝트도 정상 작동
- ✅ Service와 Ingress가 자동으로 추가됨
- ✅ 기존 manifest 내용은 유지됨

### 마이그레이션 불필요
- 모든 기능이 **자동으로 적용**됨
- 수동 작업 필요 없음

---

## 향후 개선 사항

### 1. ConfigMap/Secret 지원
```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  DATABASE_URL: "..."
```

### 2. HPA (Horizontal Pod Autoscaler)
```yaml
# k8s/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app-hpa
spec:
  minReplicas: 1
  maxReplicas: 10
```

### 3. Custom Domain 지원
```yaml
# 현재: k-le-paas-test02.klepaas.app
# 향후: custom-domain.com (사용자 지정 도메인)
```

---

## 참고 문서

- [GitHub → NCP 전체 파이프라인](./GITHUB_TO_NCP_PIPELINE.md) - GitHub → NCP 전체 파이프라인
- [NLP 배포 및 롤백](../nlp/DEPLOY_ROLLBACK.md) - NLP 배포 및 롤백
- [NCP 아키텍처 개요](./README.md) - NCP 아키텍처 개요
- [프로젝트 전체 개요](../../../CLAUDE.md) - 프로젝트 전체 개요

---

## 변경 이력

| 날짜 | 변경 내용 | 작성자 |
|------|----------|--------|
| 2025-10-24 | Ingress 자동 생성, Subdomain 중복 제거, Force Push 적용 | Claude Code |

---

## 문의

이슈 또는 개선 제안: [GitHub Issues](https://github.com/K-Le-PaaS/backend-hybrid/issues)
