# GitHub 레포지터리 등록부터 NCP 빌드/배포 파이프라인 전체 흐름

## 목차
1. [개요](#개요)
2. [전체 아키텍처](#전체-아키텍처)
3. [GitHub 레포지터리 등록](#1-github-레포지터리-등록)
4. [NCP SourceCommit 생성](#2-ncp-sourcecommit-생성)
5. [NCP SourceBuild 생성](#3-ncp-sourcebuild-생성)
6. [NCP SourceDeploy 생성](#4-ncp-sourcedeploy-생성)
7. [NCP SourcePipeline 생성](#5-ncp-sourcepipeline-생성)
8. [GitHub Webhook 연동](#6-github-webhook-연동)
9. [자동 배포 파이프라인 실행](#7-자동-배포-파이프라인-실행)
10. [코드 레벨 상세 분석](#코드-레벨-상세-분석)

---

## 개요

이 문서는 GitHub 레포지터리를 NCP(Naver Cloud Platform)에 등록하고, 자동 빌드/배포 파이프라인을 구축하는 전 과정을 **코드 레벨에서 상세하게** 설명합니다.

### 핵심 컴포넌트
- **GitHub**: 소스 코드 저장소
- **NCP SourceCommit**: Git 미러 저장소
- **NCP SourceBuild**: Docker 이미지 빌드 서비스
- **NCP Container Registry (NCR)**: Docker 이미지 저장소
- **NCP SourceDeploy**: Kubernetes 배포 서비스
- **NCP SourcePipeline**: 빌드 → 배포 자동화 워크플로우
- **K-Le-PaaS Backend**: 파이프라인 orchestration 및 webhook 처리

---

## 전체 아키텍처

```
┌─────────────────┐
│  GitHub Repo    │
│  (소스 코드)     │
└────────┬────────┘
         │ (1) Push Event
         │ GitHub Webhook
         ▼
┌─────────────────────────────────────────────────────┐
│  K-Le-PaaS Backend (FastAPI)                       │
│  app/api/v1/cicd.py - handle_push_event()          │
└────────┬────────────────────────────────────────────┘
         │ (2) Mirror + Pipeline Execute
         ▼
┌─────────────────────────────────────────────────────┐
│  NCP SourceCommit                                   │
│  - GitHub 코드 미러링                                │
│  - k8s/deployment.yaml 자동 업데이트                 │
└────────┬────────────────────────────────────────────┘
         │ (3) Trigger Build
         ▼
┌─────────────────────────────────────────────────────┐
│  NCP SourceBuild                                    │
│  - Dockerfile 빌드                                   │
│  - Docker 이미지 생성                                │
│  - NCR에 푸시 (owner-repo:commit_sha)                │
└────────┬────────────────────────────────────────────┘
         │ (4) Trigger Deploy
         ▼
┌─────────────────────────────────────────────────────┐
│  NCP SourceDeploy                                   │
│  - SourceCommit에서 k8s manifest 읽기                │
│  - NKS 클러스터에 배포                               │
│  - Deployment, Service 생성/업데이트                 │
└─────────────────────────────────────────────────────┘
         │ (5) 배포 완료
         ▼
┌─────────────────────────────────────────────────────┐
│  NKS (Naver Kubernetes Service)                     │
│  - 실제 애플리케이션 실행 환경                        │
└─────────────────────────────────────────────────────┘
```

---

## 1. GitHub 레포지터리 등록

### API 엔드포인트
- **POST** `/api/v1/ncp/pipeline/create`
- 파일: `app/api/v1/ncp_pipeline_api.py`

### 요청 예시
```json
{
  "owner": "K-Le-PaaS",
  "repo": "test-01",
  "branch": "main",
  "user_id": "user123"
}
```

### 내부 동작 흐름

#### 1.1 파이프라인 생성 요청 처리
**파일**: `app/api/v1/ncp_pipeline_api.py:69-116`

```python
@router.post("/create", response_model=CreatePipelineResponse)
async def create_pipeline(
    request: CreatePipelineRequest,
    db: Session = Depends(get_db)
):
    """
    전체 CI/CD 파이프라인 생성:
    - SourceCommit 저장소 (GitHub 미러)
    - SourceBuild 프로젝트 (Docker 이미지 빌드)
    - SourceDeploy 프로젝트 (NKS 배포)
    - SourcePipeline 프로젝트 (Build → Deploy 자동화)
    """
    result = await create_split_build_deploy_pipeline(
        pipeline_name=f"pipeline-{request.owner}-{request.repo}",
        owner=request.owner,
        repo=request.repo,
        branch=request.branch,
        sc_project_id=request.sc_project_id,
        sc_repo_name=request.sc_repo_name,
        db=db,
        user_id=request.user_id
    )
```

#### 1.2 핵심 함수: `create_split_build_deploy_pipeline()`
**파일**: `app/services/ncp_pipeline.py` (약 1500줄 이상의 대형 파일)

이 함수는 다음 작업을 순차적으로 수행합니다:

1. **SourceCommit 저장소 생성** → `ensure_sourcecommit_repo()`
2. **SourceBuild 프로젝트 생성** → `create_sourcebuild_project_rest()`
3. **SourceDeploy 프로젝트 생성** → `create_sourcedeploy_project_rest()`
4. **SourcePipeline 프로젝트 생성** → `ensure_sourcepipeline_project()`
5. **DB에 통합 정보 저장** → `upsert_integration()`

---

## 2. NCP SourceCommit 생성

### 목적
- GitHub 레포지터리를 NCP 내부로 미러링
- SourceBuild/SourceDeploy가 접근할 수 있는 내부 Git 저장소 제공

### 코드 분석

#### 2.1 SourceCommit 저장소 생성
**파일**: `app/services/ncp_pipeline.py:448-471`

```python
async def ensure_sourcecommit_repo(project_id: str, repo_name: str) -> dict:
    """
    SourceCommit 저장소 생성 (없으면 생성, 있으면 exists 반환)

    Returns:
        {status: 'created'|'exists'|'error', id?: str}
    """
    base = settings.ncp_sourcecommit_endpoint  # https://sourcecommit.apigw.ntruss.com
    create_path = f"/api/v1/projects/{project_id}/repositories"
    body = {"name": repo_name}

    try:
        data = await _call_ncp_rest_api('POST', base, create_path, body)
        repo_id = data.get('result', {}).get('id')
        return {"status": "created", "id": repo_id}
    except HTTPException as e:
        # 중복 이름 에러(310405) → 이미 존재
        if e.status_code == 400 and '310405' in str(e.detail):
            return {"status": "exists"}
        return {"status": "error", "detail": str(e.detail)}
```

#### 2.2 NCP REST API 인증
**파일**: `app/services/ncp_pipeline.py:148-166`

```python
def _sign(method: str, path: str, timestamp: str, access_key: str, secret_key: str) -> str:
    """NCP API Signature v2 생성"""
    message = f"{method} {path}\n{timestamp}\n{access_key}"
    signature = hmac.new(
        bytes(secret_key, 'utf-8'),
        bytes(message, 'utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

def _get_ncp_api_headers(method: str, path: str) -> dict:
    """NCP REST API 요청 헤더 생성"""
    timestamp = str(int(time.time() * 1000))
    signature = _sign(method, path, timestamp,
                     settings.ncp_access_key,
                     settings.ncp_secret_key)

    return {
        'x-ncp-apigw-timestamp': timestamp,
        'x-ncp-iam-access-key': settings.ncp_access_key,
        'x-ncp-apigw-signature-v2': signature,
        'Content-Type': 'application/json',
        'x-ncp-region_code': settings.ncp_region  # 'KR'
    }
```

#### 2.3 환경변수
```bash
KLEPAAS_NCP_ACCESS_KEY=your-access-key
KLEPAAS_NCP_SECRET_KEY=your-secret-key
KLEPAAS_NCP_SOURCECOMMIT_ENDPOINT=https://sourcecommit.apigw.ntruss.com
KLEPAAS_NCP_REGION=KR
```

---

## 3. NCP SourceBuild 생성

### 목적
- Dockerfile 기반 Docker 이미지 빌드
- NCR(Naver Container Registry)에 이미지 푸시
- 태그 형식: `{owner}-{repo}:{commit_sha}`

### 코드 분석

#### 3.1 SourceBuild 프로젝트 생성
**파일**: `app/services/ncp_pipeline.py:474-550` (약 500줄 이상)

```python
async def create_sourcebuild_project_rest(
    owner: str,
    repo: str,
    branch: str,
    image_repo: str,
    sc_project_id: str | None = None,
    sc_repo_name: str | None = None
) -> str:
    """
    SourceBuild 프로젝트 생성

    Args:
        owner: GitHub 소유자 (예: K-Le-PaaS)
        repo: GitHub 저장소 이름 (예: test-01)
        branch: 빌드할 브랜치 (예: main)
        image_repo: NCR 이미지 레포지토리 URL
        sc_project_id: SourceCommit 프로젝트 ID
        sc_repo_name: SourceCommit 저장소 이름

    Returns:
        생성된 SourceBuild 프로젝트 ID
    """
    base = settings.ncp_sourcebuild_endpoint

    # NCR 이미지 이름 생성 (소문자, 하이픈 유지)
    ncr_image_name = _generate_ncr_image_name(owner, repo)
    # 예: "K-Le-PaaS/test-01" → "k-le-paas-test-01"

    # Registry 프로젝트 이름 추출
    registry_host, _ = image_repo.split("/", 1)
    registry_project = registry_host.split(".")[0]  # "klepaas-test"

    # SourceBuild 설정
    body = {
        "name": f"build-{owner}-{repo}",
        "source": {
            "type": "SourceCommit",
            "projectId": sc_project_id,
            "repository": sc_repo_name,
            "branch": branch
        },
        "env": [
            {"name": "DOCKER_IMAGE_NAME", "value": ncr_image_name},
            {"name": "REGISTRY_PROJECT_NAME", "value": registry_project}
        ],
        "compute": {
            "id": 1  # vCPU 2개, 메모리 4GB
        },
        "runtime": "Docker",
        "runtimeVersion": "latest",
        "dockerImageRegistry": registry_project,
        "dockerImageName": ncr_image_name,
        "dockerImageTag": "latest",  # 실제 태그는 빌드 시 동적 지정
        "timeout": 3600,
        "buildEnv": [
            {"name": "GIT_COMMIT_SHORT_SHA", "value": ""}
        ]
    }

    data = await _call_ncp_rest_api('POST', base, '/api/v1/project', body)
    project_id = data.get('result', {}).get('projectId')
    return project_id
```

#### 3.2 NCR 이미지 이름 규칙
**파일**: `app/services/ncp_pipeline.py:83-97`

```python
def _generate_ncr_image_name(owner: str, repo: str) -> str:
    """
    NCR 규칙 준수 이미지 이름 생성

    NCR 명명 규칙:
    - 소문자만 사용
    - 하이픈(-) 허용

    Examples:
        "K-Le-PaaS/test-01" → "k-le-paas-test-01"
        "myorg/myrepo" → "myorg-myrepo"
    """
    safe_owner = owner.lower()
    safe_repo = repo.lower()
    return f"{safe_owner}-{safe_repo}"
```

#### 3.3 실제 빌드 실행
**파일**: `app/services/ncp_pipeline.py` (함수: `run_sourcebuild()`)

```python
async def run_sourcebuild(
    build_project_id: str,
    tag: str,
    db: Session,
    user_id: str,
    owner: str,
    repo: str
) -> dict:
    """
    SourceBuild 프로젝트 실행 (이미지 빌드 및 NCR 푸시)

    Args:
        build_project_id: SourceBuild 프로젝트 ID
        tag: Docker 이미지 태그 (일반적으로 commit SHA)
        db: 데이터베이스 세션
        user_id: 사용자 ID
        owner: GitHub 소유자
        repo: GitHub 저장소

    Returns:
        {
            "status": "started",
            "build_id": "12345",
            "image": "klepaas-test.kr.ncr.ntruss.com/k-le-paas-test-01:abc123"
        }
    """
    base = settings.ncp_sourcebuild_endpoint
    path = f"/api/v1/project/{build_project_id}/run"

    # 빌드 환경변수로 태그 전달
    body = {
        "env": [
            {"name": "IMAGE_TAG", "value": tag},
            {"name": "GIT_COMMIT_SHORT_SHA", "value": tag[:7]}
        ]
    }

    data = await _call_ncp_rest_api('POST', base, path, body)
    build_id = data.get('result', {}).get('buildId')

    # 빌드 완료 대기 (폴링)
    for attempt in range(60):  # 최대 30분 대기
        await asyncio.sleep(30)
        status_data = await _call_ncp_rest_api(
            'GET',
            base,
            f"/api/v1/project/{build_project_id}/build/{build_id}"
        )
        build_status = status_data.get('result', {}).get('status')

        if build_status == 'success':
            # 빌드 성공 - 이미지 URL 반환
            image_url = status_data.get('result', {}).get('containerImageUrl')
            return {
                "status": "completed",
                "build_id": build_id,
                "image": image_url
            }
        elif build_status in ['failed', 'stopped']:
            raise HTTPException(500, f"Build failed: {build_status}")

    raise HTTPException(408, "Build timeout")
```

---

## 4. NCP SourceDeploy 생성

### 목적
- NKS(Naver Kubernetes Service) 클러스터에 애플리케이션 배포
- SourceCommit의 k8s/deployment.yaml 사용
- 이미지 업데이트 및 롤링 배포

### 코드 분석

#### 4.1 SourceDeploy 프로젝트 생성
**파일**: `app/services/ncp_pipeline.py` (함수: `create_sourcedeploy_project_rest()`)

```python
async def create_sourcedeploy_project_rest(
    owner: str,
    repo: str,
    branch: str,
    sc_project_id: str,
    sc_repo_name: str,
    nks_cluster_id: str,
    image_repo: str
) -> str:
    """
    SourceDeploy 프로젝트 생성

    Args:
        owner: GitHub 소유자
        repo: GitHub 저장소
        branch: 배포할 브랜치
        sc_project_id: SourceCommit 프로젝트 ID
        sc_repo_name: SourceCommit 저장소 이름
        nks_cluster_id: NKS 클러스터 UUID
        image_repo: NCR 이미지 레포지토리 URL

    Returns:
        생성된 SourceDeploy 프로젝트 ID
    """
    base = settings.ncp_sourcedeploy_endpoint

    body = {
        "name": f"deploy-{owner}-{repo}",
        "sourceCommit": {
            "projectId": sc_project_id,
            "repositoryName": sc_repo_name,
            "branch": branch
        },
        "targetCluster": {
            "id": nks_cluster_id,
            "type": "NKS"
        },
        "stages": [
            {
                "name": "production",
                "scenarios": [
                    {
                        "name": "deploy-app",
                        "manifestPath": "k8s/deployment.yaml",
                        "strategy": "RollingUpdate"
                    }
                ]
            }
        ]
    }

    data = await _call_ncp_rest_api('POST', base, '/api/v1/project', body)
    project_id = data.get('result', {}).get('projectId')
    return project_id
```

#### 4.2 Manifest 자동 생성
**파일**: `app/services/ncp_pipeline.py:280-353`

```python
def _generate_default_manifest(app_name: str, image_url: str, port: int) -> str:
    """
    기본 Kubernetes Deployment manifest 생성

    Args:
        app_name: 애플리케이션 이름 (예: k-le-paas-test-01)
        image_url: 전체 이미지 URL (예: klepaas-test.kr.ncr.ntruss.com/k-le-paas-test-01:abc123)
        port: 컨테이너 포트 (기본: 8080)

    Returns:
        YAML 형식의 Deployment manifest
    """
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      imagePullSecrets:
      - name: ncp-cr  # NCR 접근용 Secret
      containers:
      - name: {app_name}
        image: {image_url}  # 전체 이미지 URL (태그 포함)
        ports:
        - containerPort: {port}
        env:
        - name: PORT
          value: "{port}"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
"""
```

#### 4.3 SourceCommit Manifest 업데이트
**파일**: `app/services/ncp_pipeline.py` (함수: `mirror_and_update_manifest()`)

```python
def mirror_and_update_manifest(
    github_repo_url: str,
    installation_or_access_token: str,
    sc_project_id: str,
    sc_repo_name: str,
    image_repo: str,
    image_tag: str,
    sc_endpoint: str,
    replicas: int = 1
) -> dict:
    """
    GitHub → SourceCommit 미러링 및 manifest 업데이트

    Process:
    1. GitHub 저장소 Clone
    2. k8s/deployment.yaml 생성/업데이트 (이미지 태그, replicas)
    3. SourceCommit에 Push

    Args:
        github_repo_url: GitHub 저장소 URL
        installation_or_access_token: GitHub 인증 토큰
        sc_project_id: SourceCommit 프로젝트 ID
        sc_repo_name: SourceCommit 저장소 이름
        image_repo: NCR 이미지 레포 (예: klepaas-test.kr.ncr.ntruss.com/k-le-paas-test-01)
        image_tag: 이미지 태그 (예: abc1234)
        sc_endpoint: SourceCommit API 엔드포인트
        replicas: Pod 복제 수

    Returns:
        {
            "status": "mirrored",
            "commit_sha": "abc123...",
            "old_replicas": 1,
            "new_replicas": 3,
            "old_image_tag": "old123",
            "new_image_tag": "abc1234"
        }
    """
    temp_dir = f"/tmp/git-mirror-{uuid.uuid4()}"

    try:
        # 1. GitHub Clone
        github_clone_url = github_repo_url.replace(
            "https://",
            f"https://x-access-token:{installation_or_access_token}@"
        )
        subprocess.run(
            ["git", "clone", github_clone_url, temp_dir],
            check=True,
            capture_output=True
        )

        # 2. k8s/deployment.yaml 읽기/생성
        manifest_path = Path(temp_dir) / "k8s" / "deployment.yaml"
        manifest_path.parent.mkdir(exist_ok=True)

        image_url = f"{image_repo}:{image_tag}"

        if manifest_path.exists():
            # 기존 manifest 업데이트
            import yaml
            with open(manifest_path, 'r') as f:
                manifest = yaml.safe_load(f)

            old_replicas = manifest['spec']['replicas']
            old_image = manifest['spec']['template']['spec']['containers'][0]['image']
            old_image_tag = old_image.split(':')[-1] if ':' in old_image else 'unknown'

            # 업데이트
            manifest['spec']['replicas'] = replicas
            manifest['spec']['template']['spec']['containers'][0]['image'] = image_url

            with open(manifest_path, 'w') as f:
                yaml.dump(manifest, f, default_flow_style=False)
        else:
            # 새 manifest 생성
            app_name = sc_repo_name.lower()
            manifest_content = _generate_default_manifest(app_name, image_url, 8080)
            with open(manifest_path, 'w') as f:
                f.write(manifest_content)
            old_replicas = None
            old_image_tag = None

        # 3. Git Commit & Push to SourceCommit
        os.chdir(temp_dir)
        subprocess.run(["git", "add", "k8s/deployment.yaml"], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Update image to {image_tag}, replicas to {replicas}"],
            check=True
        )

        # SourceCommit remote 추가
        sc_url = get_sourcecommit_repo_public_url(sc_project_id, sc_repo_name)
        sc_clone_url = sc_url.replace(
            "https://",
            f"https://{settings.ncp_sourcecommit_username}:{settings.ncp_sourcecommit_password}@"
        )

        subprocess.run(
            ["git", "remote", "add", "sc", sc_clone_url],
            check=True
        )
        subprocess.run(
            ["git", "push", "sc", "main", "--force"],
            check=True
        )

        # Commit SHA 추출
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        commit_sha = result.stdout.strip()

        return {
            "status": "mirrored",
            "commit_sha": commit_sha,
            "old_replicas": old_replicas,
            "new_replicas": replicas,
            "old_image_tag": old_image_tag,
            "new_image_tag": image_tag
        }

    finally:
        # 임시 디렉토리 정리
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
```

#### 4.4 SourceDeploy 실행
**파일**: `app/services/ncp_pipeline.py` (함수: `run_sourcedeploy()`)

```python
async def run_sourcedeploy(
    deploy_project_id: str,
    stage_name: str,
    scenario_name: str,
    sc_project_id: str,
    db: Session,
    user_id: str,
    owner: str,
    repo: str,
    tag: str,
    is_rollback: bool = False,
    skip_mirror: bool = False
) -> dict:
    """
    SourceDeploy 실행 (NKS 배포)

    Args:
        deploy_project_id: SourceDeploy 프로젝트 ID
        stage_name: 배포 스테이지 (예: production)
        scenario_name: 시나리오 이름 (예: deploy-app)
        sc_project_id: SourceCommit 프로젝트 ID
        db: 데이터베이스 세션
        user_id: 사용자 ID
        owner: GitHub 소유자
        repo: GitHub 저장소
        tag: 배포할 이미지 태그
        is_rollback: 롤백 배포 여부
        skip_mirror: 미러링 건너뛰기 (manifest 이미 업데이트된 경우)

    Returns:
        {
            "status": "started",
            "deploy_id": "67890",
            "deploy_history_id": 123
        }
    """
    # 1. Manifest 업데이트 (skip_mirror=False인 경우)
    if not skip_mirror:
        from .github_app import github_app_auth
        github_token, _ = await github_app_auth.get_installation_token_for_repo(owner, repo, db)
        github_repo_url = f"https://github.com/{owner}/{repo}.git"

        integration = get_integration(db, user_id=user_id, owner=owner, repo=repo)
        sc_repo_name = integration.sc_repo_name or repo

        image_name = _generate_ncr_image_name(owner, repo)
        image_repo = f"{settings.ncp_container_registry_url}/{image_name}"

        mirror_result = mirror_and_update_manifest(
            github_repo_url=github_repo_url,
            installation_or_access_token=github_token,
            sc_project_id=sc_project_id,
            sc_repo_name=sc_repo_name,
            image_repo=image_repo,
            image_tag=tag,
            sc_endpoint=settings.ncp_sourcecommit_endpoint,
            replicas=1
        )

    # 2. SourceDeploy 실행
    base = settings.ncp_sourcedeploy_endpoint
    path = f"/api/v1/project/{deploy_project_id}/stage/{stage_name}/scenario/{scenario_name}/run"

    data = await _call_ncp_rest_api('POST', base, path, {})
    deploy_id = data.get('result', {}).get('deployId')

    # 3. 배포 히스토리 기록
    from .deployment_history import record_deployment
    deploy_history = record_deployment(
        db=db,
        user_id=user_id,
        github_owner=owner,
        github_repo=repo,
        github_commit_sha=tag,
        github_commit_message=f"Deploy {tag}",
        environment="production",
        status="success",
        image_name=f"{image_repo}:{tag}",
        is_rollback=is_rollback
    )

    return {
        "status": "started",
        "deploy_id": deploy_id,
        "deploy_history_id": deploy_history.id
    }
```

---

## 5. NCP SourcePipeline 생성

### 목적
- SourceBuild → SourceDeploy 자동 연결
- 빌드 완료 시 자동으로 배포 트리거
- 파이프라인 실행 히스토리 관리

### 코드 분석

#### 5.1 SourcePipeline 프로젝트 생성
**파일**: `app/services/ncp_pipeline.py` (함수: `ensure_sourcepipeline_project()`)

```python
async def ensure_sourcepipeline_project(
    owner: str,
    repo: str,
    build_project_id: str,
    deploy_project_id: str,
    deploy_stage_id: int,
    deploy_scenario_id: int,
    branch: str,
    sc_repo_name: str | None,
    db: Session,
    user_id: str
) -> str:
    """
    SourcePipeline 프로젝트 생성/업데이트

    파이프라인 구조:
    Task 1: SourceBuild 실행
    Task 2: SourceDeploy 실행 (Task 1 성공 시)

    Args:
        owner: GitHub 소유자
        repo: GitHub 저장소
        build_project_id: SourceBuild 프로젝트 ID
        deploy_project_id: SourceDeploy 프로젝트 ID
        deploy_stage_id: Deploy 스테이지 ID
        deploy_scenario_id: Deploy 시나리오 ID
        branch: Git 브랜치
        sc_repo_name: SourceCommit 저장소 이름
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        생성된 SourcePipeline 프로젝트 ID
    """
    base = settings.ncp_sourcepipeline_endpoint

    body = {
        "name": f"pipeline-{owner}-{repo}",
        "description": f"Auto build and deploy for {owner}/{repo}",
        "tasks": [
            {
                "taskId": 1,
                "name": "Build",
                "taskType": "SourceBuild",
                "config": {
                    "projectId": build_project_id
                },
                "executeCondition": "always"
            },
            {
                "taskId": 2,
                "name": "Deploy",
                "taskType": "SourceDeploy",
                "config": {
                    "projectId": deploy_project_id,
                    "stageId": deploy_stage_id,
                    "scenarioId": deploy_scenario_id
                },
                "executeCondition": "on_success",  # Task 1 성공 시만 실행
                "dependencies": [1]  # Task 1에 의존
            }
        ],
        "trigger": {
            "type": "SourceCommit",
            "repository": sc_repo_name or repo,
            "branch": branch,
            "enabled": True  # 자동 트리거 활성화
        }
    }

    data = await _call_ncp_rest_api('POST', base, '/api/v1/project', body)
    pipeline_id = data.get('result', {}).get('projectId')

    # DB에 저장
    upsert_integration(
        db=db,
        user_id=user_id,
        owner=owner,
        repo=repo,
        pipeline_id=pipeline_id
    )

    return pipeline_id
```

#### 5.2 SourcePipeline 실행
**파일**: `app/services/ncp_pipeline.py` (함수: `execute_sourcepipeline_rest()`)

```python
async def execute_sourcepipeline_rest(pipeline_id: str) -> dict:
    """
    SourcePipeline 수동 실행

    Args:
        pipeline_id: SourcePipeline 프로젝트 ID

    Returns:
        {
            "status": "started",
            "project_id": "12345",
            "history_id": 67890
        }
    """
    base = settings.ncp_sourcepipeline_endpoint
    path = f"/api/v1/project/{pipeline_id}/run"

    data = await _call_ncp_rest_api('POST', base, path, {})
    history_id = data.get('result', {}).get('historyId')

    return {
        "status": "started",
        "project_id": pipeline_id,
        "history_id": history_id
    }
```

#### 5.3 Pipeline 실행 히스토리 조회
**파일**: `app/services/ncp_pipeline.py` (함수: `get_sourcepipeline_history_detail()`)

```python
async def get_sourcepipeline_history_detail(pipeline_id: str, history_id: int) -> dict:
    """
    Pipeline 실행 히스토리 상세 조회

    Returns:
        {
            "status": "InProgress" | "success" | "failed",
            "tasks": [
                {
                    "taskId": 1,
                    "name": "Build",
                    "status": "success",
                    "startTime": "2024-01-01T12:00:00Z",
                    "endTime": "2024-01-01T12:05:00Z"
                },
                {
                    "taskId": 2,
                    "name": "Deploy",
                    "status": "InProgress",
                    "startTime": "2024-01-01T12:05:00Z"
                }
            ]
        }
    """
    base = settings.ncp_sourcepipeline_endpoint
    path = f"/api/v1/project/{pipeline_id}/history/{history_id}"

    data = await _call_ncp_rest_api('GET', base, path)
    return data.get('result', {})
```

---

## 6. GitHub Webhook 연동

### 목적
- GitHub Push 이벤트 감지
- 자동으로 파이프라인 실행
- HMAC-SHA256 서명 검증

### 코드 분석

#### 6.1 Webhook 엔드포인트
**파일**: `app/api/v1/cicd.py` (웹훅 라우터)

```python
@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    db: Session = Depends(get_db)
):
    """
    GitHub Webhook 수신 엔드포인트

    지원하는 이벤트:
    - push: main 브랜치 PR merge 시 자동 배포
    - release: published 시 프로덕션 배포
    """
    # 1. 서명 검증
    body_bytes = await request.body()
    verify_github_signature(body_bytes, x_hub_signature_256)

    # 2. 이벤트 파싱
    event = await request.json()

    # 3. 이벤트 타입별 처리
    if x_github_event == "push":
        result = await handle_push_event(event)
    elif x_github_event == "release":
        result = await handle_release_event(event)
    else:
        return {"status": "ignored", "reason": f"unsupported event {x_github_event}"}

    return result
```

#### 6.2 서명 검증
**파일**: `app/services/cicd.py:20-43`

```python
def verify_github_signature(payload_bytes: bytes, signature_header: str | None) -> None:
    """
    GitHub Webhook 서명 검증 (HMAC-SHA256)

    GitHub는 다음 형식으로 서명을 보냅니다:
    X-Hub-Signature-256: sha256=<signature>
    """
    settings = get_settings()

    # GitHub App 방식 우선
    if settings.github_app_webhook_secret:
        if not signature_header:
            raise HTTPException(400, "Missing signature header")

        if not github_app_auth.verify_webhook_signature(payload_bytes, signature_header):
            raise HTTPException(401, "Invalid GitHub App signature")
        return

    # Personal Access Token 방식 (레거시)
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(400, "webhook secret not configured")

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(401, "invalid signature header")

    signature = signature_header.split("=", 1)[1]
    mac = hmac.new(secret.encode(), msg=payload_bytes, digestmod=hashlib.sha256)
    expected = mac.hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "signature mismatch")
```

#### 6.3 Push 이벤트 처리
**파일**: `app/services/cicd.py:69-258`

```python
async def handle_push_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    GitHub Push 이벤트 처리

    Process:
    1. main 브랜치 체크
    2. PR merge commit 확인
    3. auto_deploy_enabled 체크
    4. SourcePipeline 실행 (우선) 또는 직접 배포
    """
    settings = get_settings()

    # 1. main 브랜치 체크
    ref = event.get("ref", "")
    branch = ref.split("/")[-1] if ref else ""
    if branch != (settings.github_branch_main or "main"):
        return {"status": "ignored", "reason": "not main branch", "branch": branch}

    # 2. PR merge commit 확인 (보안)
    head = event.get("head_commit") or {}
    message = (head.get("message") or "").lower()
    pusher = (event.get("pusher") or {}).get("name", "").lower()
    is_merge = ("merge pull request" in message) or (pusher == "web-flow")

    if not is_merge:
        return {"status": "ignored", "reason": "not a PR merge commit"}

    # 3. Installation ID로 integration 조회
    installation_id = event.get("installation", {}).get("id")
    integration = None

    if installation_id:
        from ..database import SessionLocal
        from ..models.user_project_integration import UserProjectIntegration

        db = SessionLocal()
        try:
            integration = db.query(UserProjectIntegration).filter(
                UserProjectIntegration.github_installation_id == str(installation_id)
            ).first()

            # auto_deploy_enabled 체크
            if integration and not getattr(integration, 'auto_deploy_enabled', False):
                return {
                    "status": "skipped",
                    "reason": "auto_deploy_disabled"
                }
        finally:
            db.close()

    # 4. 저장소 정보 추출
    repo_data = event.get("repository", {})
    repo = repo_data.get("name", "app")
    owner = repo_data.get("owner", {}).get("login", "")
    commit = (event.get("after") or "")[:7] or "latest"

    # 5. SourcePipeline 모드 (우선)
    if integration:
        pipeline_id = getattr(integration, 'pipeline_id', None)
        build_project_id = getattr(integration, 'build_project_id', None)
        deploy_project_id = getattr(integration, 'deploy_project_id', None)

        # Pipeline 자동 생성 (build/deploy만 있고 pipeline 없는 경우)
        if not pipeline_id and build_project_id and deploy_project_id:
            from .ncp_pipeline import ensure_sourcepipeline_project

            db = SessionLocal()
            try:
                pipeline_id = await ensure_sourcepipeline_project(
                    owner=owner,
                    repo=repo,
                    build_project_id=str(build_project_id),
                    deploy_project_id=str(deploy_project_id),
                    deploy_stage_id=1,
                    deploy_scenario_id=1,
                    branch=branch,
                    sc_repo_name=getattr(integration, 'sc_repo_name', None),
                    db=db,
                    user_id=getattr(integration, 'user_id', None)
                )
            finally:
                db.close()

        # Pipeline 실행
        if pipeline_id:
            from .ncp_pipeline import execute_sourcepipeline_rest

            pipeline_result = await execute_sourcepipeline_rest(pipeline_id)

            # Slack 알림
            try:
                import asyncio
                asyncio.create_task(slack_notify(
                    f"[SourcePipeline] Execution triggered for {repo}:{commit}\n"
                    f"Pipeline ID: {pipeline_id}\n"
                    f"History ID: {pipeline_result.get('history_id', 'N/A')}"
                ))
            except Exception:
                pass

            return {
                "status": "pipeline_triggered",
                "mode": "sourcepipeline",
                "pipeline_id": pipeline_id,
                "history_id": pipeline_result.get("history_id"),
                "repository": repo,
                "commit": commit
            }

    # 6. 직접 배포 모드 (Fallback)
    from .deployments import DeployApplicationInput, perform_deploy

    image = f"{repo}:{commit}"
    payload = DeployApplicationInput(
        app_name=repo,
        environment="staging",
        image=image,
        replicas=2
    )

    result = perform_deploy(payload)

    # Slack 알림
    try:
        import asyncio
        asyncio.create_task(slack_notify(f"[Staging] Deploy triggered: {repo}:{commit}"))
    except Exception:
        pass

    return {"status": "triggered", "deploy": result}
```

---

## 7. 자동 배포 파이프라인 실행

### 전체 흐름

```
┌──────────────────────────────────────────────┐
│ 1. Developer: git push origin main          │
│    (PR merge commit)                         │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 2. GitHub: Send Webhook                      │
│    POST /api/v1/cicd/webhook                 │
│    X-Hub-Signature-256: sha256=...           │
│    {                                         │
│      "ref": "refs/heads/main",               │
│      "repository": {                         │
│        "name": "test-01",                    │
│        "owner": {"login": "K-Le-PaaS"}       │
│      },                                      │
│      "after": "abc1234567...",               │
│      "installation": {"id": 12345}           │
│    }                                         │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 3. Backend: Verify Signature                 │
│    - HMAC-SHA256 검증                         │
│    - GitHub App 또는 PAT 방식                 │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 4. Backend: Check Deployment Settings        │
│    - auto_deploy_enabled 확인                │
│    - pipeline_id 존재 여부 확인               │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 5. Backend: Execute SourcePipeline           │
│    POST /api/v1/project/{pipeline_id}/run    │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 6. NCP SourcePipeline: Task 1 (Build)        │
│    - SourceCommit에서 코드 fetch              │
│    - Dockerfile 빌드                          │
│    - NCR에 푸시 (k-le-paas-test-01:abc1234)   │
└──────────────┬───────────────────────────────┘
               │
               ▼ (Build 성공 시)
┌──────────────────────────────────────────────┐
│ 7. NCP SourcePipeline: Task 2 (Deploy)       │
│    - SourceCommit k8s/deployment.yaml 읽기    │
│    - NKS 클러스터에 배포                      │
│    - Rolling Update 수행                      │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│ 8. NKS Cluster: Pod Running                  │
│    - 새 이미지로 Pod 생성                     │
│    - 기존 Pod 종료 (Rolling)                 │
│    - Service 자동 연결                        │
└──────────────────────────────────────────────┘
```

### 타임라인 예시

```
00:00 - Developer pushes to main
00:01 - GitHub sends webhook
00:02 - Backend verifies signature, checks settings
00:03 - Backend triggers SourcePipeline
00:04 - SourceBuild starts (Docker build)
00:10 - Docker build completes, image pushed to NCR
00:11 - SourceDeploy starts
00:12 - Manifest fetched from SourceCommit
00:13 - kubectl apply executed on NKS
00:15 - New pod created and running
00:17 - Old pod terminated
00:18 - Deployment complete ✓
```

---

## 코드 레벨 상세 분석

### 주요 파일 구조

```
backend-hybrid/
├── app/
│   ├── api/v1/
│   │   ├── cicd.py                  # GitHub Webhook 엔드포인트
│   │   └── ncp_pipeline_api.py      # NCP Pipeline REST API
│   ├── services/
│   │   ├── cicd.py                  # Webhook 처리 로직
│   │   ├── ncp_pipeline.py          # NCP API 통합 (1500+ 줄)
│   │   ├── user_project_integration.py  # DB integration 관리
│   │   └── deployment_history.py    # 배포 히스토리 기록
│   ├── models/
│   │   ├── user_project_integration.py  # Integration 모델
│   │   └── deployment_history.py        # History 모델
│   └── core/
│       └── config.py                # 환경변수 설정
```

### 데이터베이스 모델

#### UserProjectIntegration
**파일**: `app/models/user_project_integration.py`

```python
class UserProjectIntegration(Base):
    """사용자-프로젝트-NCP 통합 정보"""
    __tablename__ = "user_project_integrations"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    github_owner = Column(String, nullable=False)
    github_repo = Column(String, nullable=False)
    github_installation_id = Column(String)  # GitHub App Installation ID

    # NCP 프로젝트 ID들
    sc_project_id = Column(String)           # SourceCommit
    sc_repo_name = Column(String)            # SourceCommit 저장소 이름
    build_project_id = Column(String)        # SourceBuild
    deploy_project_id = Column(String)       # SourceDeploy
    pipeline_id = Column(String)             # SourcePipeline

    # 설정
    branch = Column(String, default="main")
    auto_deploy_enabled = Column(Boolean, default=False)

    # 메타데이터
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### DeploymentHistory
**파일**: `app/models/deployment_history.py`

```python
class DeploymentHistory(Base):
    """배포 히스토리"""
    __tablename__ = "deployment_histories"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False)
    github_owner = Column(String, nullable=False)
    github_repo = Column(String, nullable=False)
    github_commit_sha = Column(String, nullable=False)
    github_commit_message = Column(String)

    environment = Column(String)  # staging, production
    status = Column(String)       # pending, success, failed
    image_name = Column(String)   # NCR 이미지 URL

    is_rollback = Column(Boolean, default=False)
    rollback_from_id = Column(Integer, ForeignKey("deployment_histories.id"))

    deployed_at = Column(DateTime)
    created_at = Column(DateTime, default=get_kst_now)
```

### 환경변수 전체 목록

```bash
# NCP 인증
KLEPAAS_NCP_ACCESS_KEY=your-access-key
KLEPAAS_NCP_SECRET_KEY=your-secret-key
KLEPAAS_NCP_REGION=KR

# NCP 서비스 엔드포인트
KLEPAAS_NCP_SOURCECOMMIT_ENDPOINT=https://sourcecommit.apigw.ntruss.com
KLEPAAS_NCP_SOURCEBUILD_ENDPOINT=https://sourcebuild.apigw.ntruss.com
KLEPAAS_NCP_SOURCEDEPLOY_ENDPOINT=https://sourcedeploy.apigw.ntruss.com
KLEPAAS_NCP_SOURCEPIPELINE_ENDPOINT=https://sourcepipeline.apigw.ntruss.com

# NCP Container Registry
KLEPAAS_NCP_CONTAINER_REGISTRY_URL=klepaas-test.kr.ncr.ntruss.com

# NCP SourceCommit 인증 (Git push용)
KLEPAAS_NCP_SOURCECOMMIT_USERNAME=your-username
KLEPAAS_NCP_SOURCECOMMIT_PASSWORD=your-password
KLEPAAS_NCP_SOURCECOMMIT_PROJECT_ID=your-project-id

# NCP NKS
KLEPAAS_NCP_NKS_CLUSTER_ID=your-cluster-uuid

# GitHub App
KLEPAAS_GITHUB_APP_ID=your-app-id
KLEPAAS_GITHUB_APP_PRIVATE_KEY=your-private-key
KLEPAAS_GITHUB_APP_WEBHOOK_SECRET=your-webhook-secret

# Database
KLEPAAS_DATABASE_URL=sqlite:////data/klepaas.db

# Slack (선택)
KLEPAAS_SLACK_WEBHOOK_URL=your-slack-webhook
```

### 에러 처리 및 재시도

#### NCR 이미지 검증
**파일**: `app/services/ncp_pipeline.py:356-408`

```python
async def _verify_ncr_manifest_exists(image_with_tag: str) -> dict:
    """
    NCR에 이미지가 존재하는지 확인

    Process:
    1. Docker Registry v2 API로 manifest HEAD 요청
    2. 401 응답 시 Bearer token 인증 시도
    3. 최종 200 응답 여부로 존재 확인

    Returns:
        {"exists": True/False, "code": HTTP_STATUS_CODE}
    """
    # 이미지 URL 파싱
    registry_host, name = image_with_tag.split("/", 1)
    name, tag = name.rsplit(":", 1)

    url = f"https://{registry_host}/v2/{name}/manifests/{tag}"
    headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            return {"exists": True, "code": 200}

        if resp.status_code != 401:
            return {"exists": False, "code": resp.status_code}

        # 401: Bearer token 인증 필요
        www = resp.headers.get("WWW-Authenticate", "")
        # realm, service, scope 파싱
        realm, service, scope = parse_www_authenticate(www)

        # Token 획득
        token_resp = await client.get(
            realm,
            params={"service": service, "scope": scope},
            auth=(settings.ncp_access_key, settings.ncp_secret_key)
        )

        if token_resp.status_code != 200:
            return {"exists": False, "code": 401}

        token = token_resp.json().get("token")

        # 재시도 (with token)
        headers["Authorization"] = f"Bearer {token}"
        resp2 = await client.get(url, headers=headers)

        return {"exists": resp2.status_code == 200, "code": resp2.status_code}
```

### API 호출 재시도 로직
**파일**: `app/services/ncp_pipeline.py:168-190`

```python
async def _call_ncp_rest_api(
    method: str,
    base_url: str,
    path: str | list[str],
    json_body: dict | None = None,
    query_params: dict | None = None
) -> dict:
    """
    NCP REST API 호출 (여러 경로 후보 시도)

    Args:
        path: 단일 경로 또는 경로 리스트 (여러 버전 API 대응)

    Returns:
        JSON 응답

    Raises:
        HTTPException: 모든 경로 실패 시
    """
    paths = path if isinstance(path, list) else [path]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in paths:
            url = base_url.rstrip('/') + p
            headers = _get_ncp_api_headers(method, p)

            if method.upper() == 'GET':
                resp = await client.request(method, url, headers=headers, params=query_params)
            else:
                resp = await client.request(method, url, headers=headers, json=json_body)

            if resp.status_code < 400:
                return resp.json() if resp.text else {}

            # 실패 시 다음 경로 시도
            last_status = resp.status_code
            last_text = resp.text

    # 모든 경로 실패
    raise HTTPException(
        status_code=last_status or 500,
        detail=f"NCP REST error {last_status}: {last_text}"
    )
```

---

## 마무리

이 문서는 GitHub 레포지터리 등록부터 NCP 자동 빌드/배포까지의 전체 파이프라인을 코드 레벨에서 상세하게 설명했습니다.

### 핵심 포인트
1. **모든 NCP 서비스는 REST API로 통합**됩니다.
2. **SourcePipeline은 Build → Deploy 자동화**를 담당합니다.
3. **GitHub Webhook은 HMAC-SHA256 서명 검증**이 필수입니다.
4. **Manifest 업데이트는 Git mirror를 통해** 이루어집니다.
5. **모든 배포는 DeploymentHistory에 기록**됩니다.

### 관련 문서
- [02-nlp-deploy-rollback.md](./02-nlp-deploy-rollback.md) - NLP 배포 및 롤백 기능
- [03-troubleshooting.md](./03-troubleshooting.md) - 트러블슈팅 가이드
