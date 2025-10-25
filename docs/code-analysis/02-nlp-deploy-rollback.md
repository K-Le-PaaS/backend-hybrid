# NLP 배포 및 롤백 기능 상세 분석

## 목차
1. [개요](#개요)
2. [NLP 시스템 아키텍처](#nlp-시스템-아키텍처)
3. [NLP 배포 명령어 처리](#nlp-배포-명령어-처리)
4. [NLP 롤백 명령어 처리](#nlp-롤백-명령어-처리)
5. [롤백 서비스 상세](#롤백-서비스-상세)
6. [스케일링 기능](#스케일링-기능)
7. [코드 레벨 상세 분석](#코드-레벨-상세-분석)

---

## 개요

K-Le-PaaS Backend는 **자연어 명령어(NLP)**를 통해 Kubernetes 및 NCP 리소스를 관리할 수 있는 강력한 기능을 제공합니다.

### 지원하는 명령어
- **배포**: "K-Le-PaaS/test-01을 배포해줘"
- **롤백**: "K-Le-PaaS/test-01을 3번 전으로 롤백해줘"
- **스케일링**: "K-Le-PaaS/test-01을 5개로 늘려줘"
- **상태 확인**: "nginx pod 상태 확인해줘"
- **로그 조회**: "chat-app 로그 50줄 보여줘"

### 핵심 컴포넌트
1. **Gemini AI**: 자연어 해석 및 의도 파악
2. **Command Service**: 명령어 계획 및 실행
3. **Rollback Service**: 배포 히스토리 기반 롤백
4. **NCP Pipeline**: 실제 빌드/배포 실행

---

## NLP 시스템 아키텍처

```
┌─────────────────────────────────────────────┐
│  사용자 입력                                 │
│  "K-Le-PaaS/test-01을 3번 전으로 롤백해줘"    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  1. NLP API 엔드포인트                       │
│  POST /api/v1/nlp/process                   │
│  app/api/v1/nlp.py                          │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  2. Gemini AI 해석                           │
│  app/llm/gemini.py - GeminiClient.interpret()│
│                                              │
│  Input: "K-Le-PaaS/test-01을 3번 전으로 롤백" │
│  Output: {                                   │
│    "intent": "rollback",                     │
│    "entities": {                             │
│      "github_owner": "K-Le-PaaS",            │
│      "github_repo": "test-01",               │
│      "steps_back": 3                         │
│    }                                         │
│  }                                           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  3. CommandRequest 생성                      │
│  app/services/commands.py                    │
│                                              │
│  req = CommandRequest(                       │
│    command="rollback",                       │
│    github_owner="K-Le-PaaS",                 │
│    github_repo="test-01",                    │
│    steps_back=3                              │
│  )                                           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  4. CommandPlan 생성                         │
│  plan_command(req) → CommandPlan             │
│                                              │
│  CommandPlan(                                │
│    tool="rollback_deployment",               │
│    args={                                    │
│      "owner": "K-Le-PaaS",                   │
│      "repo": "test-01",                      │
│      "steps_back": 3                         │
│    }                                         │
│  )                                           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  5. 명령 실행                                │
│  execute_command(plan)                       │
│  → _execute_rollback_deployment()            │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  6. Rollback Service 호출                    │
│  app/services/rollback.py                    │
│  rollback_to_previous(owner, repo, steps, db)│
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  7. NCP SourceDeploy 실행                    │
│  run_sourcedeploy(...)                       │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  8. NKS 클러스터 배포                        │
│  이전 버전으로 롤백 완료                      │
└─────────────────────────────────────────────┘
```

---

## NLP 배포 명령어 처리

### API 엔드포인트
- **POST** `/api/v1/nlp/process`
- 파일: `app/api/v1/nlp.py:41-216`

### 요청 예시
```json
{
  "command": "K-Le-PaaS/test-01을 배포해줘",
  "timestamp": "2024-01-01T12:00:00Z",
  "context": {
    "project_name": "test-project"
  }
}
```

### 코드 분석

#### Step 1: NLP API 요청 수신
**파일**: `app/api/v1/nlp.py:52-73`

```python
@router.post("/nlp/process", response_model=CommandResponse)
async def process_command(
    command_data: NaturalLanguageCommand,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    """
    자연어 명령을 처리합니다 (일반 K8s 명령 + 롤백 명령 지원).

    JWT 토큰이 있으면 인증된 사용자로, 없으면 'api_user'로 처리합니다.
    """
    # 사용자 ID 결정
    effective_user_id = user_id or "api_user"

    command = command_data.command.strip()
    logger.info(f"자연어 명령 처리 시작: {command} (user_id: {effective_user_id})")

    # 명령 유효성 검사
    if not command:
        raise HTTPException(400, "명령을 입력해주세요.")

    if len(command) < 3:
        raise HTTPException(400, "명령이 너무 짧습니다. (최소 3자 이상)")

    if len(command) > 500:
        raise HTTPException(400, "명령이 너무 깁니다. (최대 500자)")

    # 위험한 명령어 체크
    dangerous_keywords = ['rm -rf', 'sudo', 'kill', 'format', 'delete all']
    if any(keyword in command.lower() for keyword in dangerous_keywords):
        raise HTTPException(400, "위험한 명령어가 포함되어 있습니다.")
```

#### Step 2: Gemini AI 해석
**파일**: `app/api/v1/nlp.py:100-130`

```python
# Gemini API를 통한 자연어 해석
from ...llm.gemini import GeminiClient

gemini_client = GeminiClient()

# Gemini로 명령 해석
gemini_result = await gemini_client.interpret(
    prompt=command,
    user_id=effective_user_id,
    project_name=command_data.context.get("project_name", "default") if command_data.context else "default"
)

logger.info(f"Gemini 해석 결과: {gemini_result}")

# Gemini 결과 예시:
# {
#   "intent": "deploy",
#   "message": "K-Le-PaaS/test-01 애플리케이션을 배포합니다.",
#   "entities": {
#     "github_owner": "K-Le-PaaS",
#     "github_repo": "test-01"
#   }
# }
```

#### Step 3: CommandRequest 변환
**파일**: `app/api/v1/nlp.py:124-148`

```python
# Gemini 결과를 CommandRequest로 변환
entities = gemini_result.get("entities", {})
intent = gemini_result.get("intent", "status")

req = CommandRequest(
    command=intent,
    # 리소스 타입별 필드 설정
    pod_name=entities.get("pod_name") or "",
    deployment_name=entities.get("deployment_name") or "",
    service_name=entities.get("service_name") or "",
    # 기타 파라미터들
    replicas=entities.get("replicas", 1),
    lines=entities.get("lines", 30),
    version=entities.get("version") or "",
    namespace=entities.get("namespace") or "default",
    previous=bool(entities.get("previous", False)),
    # NCP 롤백 관련 필드
    github_owner=entities.get("github_owner") or "",
    github_repo=entities.get("github_repo") or "",
    target_commit_sha=entities.get("target_commit_sha") or "",
    steps_back=entities.get("steps_back", 0)
)
```

#### Step 4: 명령 실행
**파일**: `app/api/v1/nlp.py:153-180`

```python
# commands.py로 실제 작업 수행
from ...services.commands import plan_command, execute_command

plan = plan_command(req)
logger.info(f"CommandPlan 생성: {plan}")

# user_id를 plan.args에 추가
if not plan.args:
    plan.args = {}
plan.args["user_id"] = effective_user_id

k8s_result = await execute_command(plan)
logger.info(f"실행 결과: {k8s_result}")

# Gemini 메시지 + 실행 결과 조합
result = {
    "message": gemini_result.get("message", "명령이 완료되었습니다."),
    "action": gemini_result.get("intent", "unknown"),
    "entities": entities,
    "k8s_result": k8s_result  # 실제 작업 결과
}
```

#### Step 5: Command Planning (배포 명령)
**파일**: `app/services/commands.py:116-125`

```python
def plan_command(req: CommandRequest) -> CommandPlan:
    """
    CommandRequest를 실행 가능한 CommandPlan으로 변환
    """
    command = req.command.lower()

    if command == "deploy":
        # 배포 명령은 직접 K8s 배포 실행 (레거시)
        # 실제 NCP 배포는 webhook을 통해 이루어짐
        return CommandPlan(
            tool="deploy_application",
            args={
                "app_name": req.deployment_name or "app",
                "environment": "staging",
                "image": f"{req.deployment_name}:latest",
                "replicas": 2,
            },
        )
```

**참고**: 현재 NLP를 통한 직접 배포는 레거시 방식이며, **실제 배포는 GitHub Webhook → SourcePipeline을 통해 이루어집니다.**

---

## NLP 롤백 명령어 처리

### 명령어 예시
```
"K-Le-PaaS/test-01을 3번 전으로 롤백해줘"
"owner/repo를 이전 버전으로 되돌려줘"
"K-Le-PaaS/test-01을 commit abc1234로 롤백"
```

### 코드 분석

#### Step 1: Gemini 해석 (롤백)
**Gemini 출력 예시**:
```json
{
  "intent": "rollback",
  "message": "K-Le-PaaS/test-01 애플리케이션을 3번 전 버전으로 롤백합니다.",
  "entities": {
    "github_owner": "K-Le-PaaS",
    "github_repo": "test-01",
    "steps_back": 3
  }
}
```

#### Step 2: Command Planning (롤백)
**파일**: `app/services/commands.py:183-195`

```python
def plan_command(req: CommandRequest) -> CommandPlan:
    command = req.command.lower()

    if command == "rollback":
        # NCP 파이프라인 롤백 (deployment_histories 기반)
        if not req.github_owner or not req.github_repo:
            raise ValueError("NCP 롤백 명령어에는 GitHub 저장소 정보가 필요합니다. 예: 'owner/repo를 3번 전으로 롤백'")

        return CommandPlan(
            tool="rollback_deployment",
            args={
                "owner": req.github_owner,
                "repo": req.github_repo,
                "target_commit_sha": req.target_commit_sha,  # 특정 커밋 롤백 (선택)
                "steps_back": req.steps_back  # N번 전 롤백
            },
        )
```

#### Step 3: Rollback 실행
**파일**: `app/services/commands.py` (함수: `execute_command()`)

```python
async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    """
    CommandPlan 실행
    """
    if plan.tool == "rollback_deployment":
        return await _execute_rollback_deployment(plan.args)
    # ... 기타 도구들
```

**파일**: `app/services/commands.py` (함수: `_execute_rollback_deployment()`)

```python
async def _execute_rollback_deployment(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    NCP SourceDeploy 롤백 실행

    Args:
        args: {
            "owner": "K-Le-PaaS",
            "repo": "test-01",
            "target_commit_sha": "abc1234" (optional),
            "steps_back": 3 (optional),
            "user_id": "user123"
        }

    Process:
    1. target_commit_sha가 있으면 → rollback_to_commit()
    2. steps_back이 있으면 → rollback_to_previous()
    """
    from .rollback import rollback_to_commit, rollback_to_previous
    from ..database import SessionLocal

    owner = args.get("owner")
    repo = args.get("repo")
    target_commit_sha = args.get("target_commit_sha")
    steps_back = args.get("steps_back", 0)
    user_id = args.get("user_id")

    if not owner or not repo:
        raise ValueError("owner와 repo는 필수입니다.")

    db = SessionLocal()
    try:
        # 특정 커밋으로 롤백
        if target_commit_sha:
            result = await rollback_to_commit(
                owner=owner,
                repo=repo,
                target_commit_sha=target_commit_sha,
                db=db,
                user_id=user_id
            )
        # N번 전으로 롤백
        elif steps_back > 0:
            result = await rollback_to_previous(
                owner=owner,
                repo=repo,
                steps_back=steps_back,
                db=db,
                user_id=user_id
            )
        else:
            raise ValueError("target_commit_sha 또는 steps_back을 지정해야 합니다.")

        return {
            "message": f"{owner}/{repo} 롤백이 완료되었습니다.",
            "rollback_result": result
        }
    finally:
        db.close()
```

---

## 롤백 서비스 상세

### 롤백 종류
1. **rollback_to_previous**: N번 전 버전으로 롤백
2. **rollback_to_commit**: 특정 커밋 SHA로 롤백

### 코드 분석

#### 함수 1: `rollback_to_previous()`
**파일**: `app/services/rollback.py:265-408`

```python
async def rollback_to_previous(
    owner: str,
    repo: str,
    steps_back: int,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    N번 전 버전으로 롤백

    Process:
    1. 현재 배포 버전 조회 (가장 최근 성공한 배포)
    2. 원본 배포 목록 조회 (is_rollback=False)
    3. 현재 버전의 인덱스 찾기
    4. target_index = current_index + steps_back
    5. 해당 커밋으로 rollback_to_commit() 호출

    Args:
        owner: GitHub 소유자
        repo: GitHub 저장소
        steps_back: 몇 번 전으로 롤백할지 (1 = 이전 버전)
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        롤백 결과
    """
    logger.info(f"Starting rollback to previous: {owner}/{repo}, steps_back={steps_back}")

    # 1. 현재 배포 버전 조회
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).first()

    if not current_deployment:
        raise HTTPException(404, "배포 이력을 찾을 수 없습니다.")

    current_commit_sha = current_deployment.github_commit_sha
    logger.info(f"Current deployment: commit={current_commit_sha[:7]}")

    # 2. 원본 배포 목록 (롤백 제외)
    original_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False  # 롤백 제외
    ).order_by(
        DeploymentHistory.created_at.desc()  # 최신순
    ).all()

    if not original_deployments:
        raise HTTPException(404, "원본 배포 이력을 찾을 수 없습니다.")

    logger.info(f"Found {len(original_deployments)} original deployments")

    # 3. 현재 커밋의 인덱스 찾기
    current_index = None
    for idx, dep in enumerate(original_deployments):
        if dep.github_commit_sha[:7] == current_commit_sha[:7]:
            current_index = idx
            logger.info(f"Current commit found at index {idx}")
            break

    if current_index is None:
        logger.warning(f"Current commit not found in original deployments, using index 0")
        current_index = 0

    # 4. 타겟 인덱스 계산
    target_index = current_index + steps_back

    if target_index >= len(original_deployments):
        available = len(original_deployments) - current_index - 1
        raise HTTPException(
            400,
            f"배포 이력이 부족합니다. {available}개의 이전 버전만 사용 가능합니다."
        )

    # 5. 타겟 배포 선택
    target_deployment = original_deployments[target_index]
    logger.info(f"Target deployment: commit={target_deployment.github_commit_sha[:7]}")

    # 6. 너무 오래된 배포 체크 (30일)
    from ..models.deployment_history import get_kst_now
    if target_deployment.deployed_at and target_deployment.deployed_at < get_kst_now() - timedelta(days=30):
        raise HTTPException(400, "30일 이상 된 배포로는 롤백할 수 없습니다.")

    # 7. commit 기반 롤백 호출
    db.commit()  # 트랜잭션 커밋 (SQLite 락 방지)

    return await rollback_to_commit(
        owner=owner,
        repo=repo,
        target_commit_sha=target_deployment.github_commit_sha,
        db=db,
        user_id=user_id
    )
```

#### 함수 2: `rollback_to_commit()`
**파일**: `app/services/rollback.py:106-262`

```python
async def rollback_to_commit(
    owner: str,
    repo: str,
    target_commit_sha: str,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    특정 커밋으로 롤백

    Process:
    1. 프로젝트 통합 정보 조회
    2. 배포 히스토리에서 target commit 찾기
    3. NCR 이미지 검증 건너뛰기 (이미 배포된 이미지 재사용)
    4. run_sourcedeploy() 호출 (is_rollback=True)
    5. 롤백 히스토리 자동 기록

    Args:
        owner: GitHub 소유자
        repo: GitHub 저장소
        target_commit_sha: 롤백할 커밋 SHA (full 또는 short)
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        {
            "status": "success",
            "action": "rollback",
            "target_commit": "abc1234567...",
            "target_commit_short": "abc1234",
            "image": "klepaas-test.kr.ncr.ntruss.com/k-le-paas-test-01:abc1234",
            "deploy_result": {...},
            "rebuilt": false
        }
    """
    logger.info(f"Starting rollback for {owner}/{repo} to commit {target_commit_sha[:7]}")

    # 1. 프로젝트 통합 정보 조회
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        raise HTTPException(
            404,
            f"프로젝트 통합 정보를 찾을 수 없습니다: {owner}/{repo}\n"
            f"롤백을 하려면 먼저 프로젝트를 배포하여 통합 정보를 생성해야 합니다."
        )

    if not integ.build_project_id:
        raise HTTPException(400, "Build project ID not configured")

    if not integ.deploy_project_id:
        raise HTTPException(400, "Deploy project ID not configured")

    # 2. 배포 히스토리에서 target commit 찾기
    history = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).filter(
        # Full SHA 또는 Short SHA 지원
        (DeploymentHistory.github_commit_sha == target_commit_sha) |
        (DeploymentHistory.github_commit_sha.like(f"{target_commit_sha}%"))
    ).first()

    if not history:
        raise HTTPException(
            404,
            f"커밋 {target_commit_sha[:7]}에 대한 성공한 배포 이력을 찾을 수 없습니다."
        )

    logger.info(f"Found deployment history: deployed_at={history.deployed_at}, image={history.image_name}")

    # 3. NCR 이미지 검증 건너뛰기
    # Rationale: 이미 배포된 이미지는 NCR에 존재함
    # NCR 검증은 403 에러가 발생할 수 있어서 불필요한 재빌드를 유발
    logger.info("Rollback: skipping NCR verification and rebuild")

    # 4. 트랜잭션 커밋 (SQLite 락 방지)
    db.commit()

    # 5. SourceDeploy 실행 (재빌드 없이)
    from .ncp_pipeline import run_sourcedeploy

    deploy_result = await run_sourcedeploy(
        deploy_project_id=integ.deploy_project_id,
        stage_name="production",
        scenario_name="deploy-app",
        sc_project_id=integ.sc_project_id,
        db=db,
        user_id=user_id,
        owner=owner,
        repo=repo,
        tag=target_commit_sha,  # 특정 커밋 SHA를 태그로 사용
        is_rollback=True  # 롤백 플래그
    )

    # 6. 롤백 히스토리는 run_sourcedeploy()에서 자동 기록됨

    return {
        "status": "success",
        "action": "rollback",
        "target_commit": target_commit_sha,
        "target_commit_short": target_commit_sha[:7],
        "image": history.image_name,
        "build_result": None,  # 재빌드 안 함
        "deploy_result": deploy_result,
        "rebuilt": False,
        "previous_deployment": {
            "deployed_at": history.deployed_at,
            "deployed_by": getattr(history, 'deployed_by', None),
            "image": history.image_name
        }
    }
```

#### 롤백 히스토리 기록
**파일**: `app/services/ncp_pipeline.py` (함수: `run_sourcedeploy()` 내부)

```python
async def run_sourcedeploy(
    # ... args ...
    is_rollback: bool = False,
    skip_mirror: bool = False
) -> dict:
    """
    SourceDeploy 실행

    is_rollback=True인 경우 DeploymentHistory에 롤백으로 기록
    """
    # ... deployment 실행 ...

    # 배포 히스토리 기록
    from .deployment_history import record_deployment

    deploy_history = record_deployment(
        db=db,
        user_id=user_id,
        github_owner=owner,
        github_repo=repo,
        github_commit_sha=tag,
        github_commit_message=f"Rollback to {tag}" if is_rollback else f"Deploy {tag}",
        environment="production",
        status="success",
        image_name=f"{image_repo}:{tag}",
        is_rollback=is_rollback  # 롤백 플래그
    )

    return {
        "status": "started",
        "deploy_id": deploy_id,
        "deploy_history_id": deploy_history.id
    }
```

### 롤백 목록 조회

#### API 엔드포인트
- **Command**: `"K-Le-PaaS/test-01 롤백 목록 보여줘"`
- **Intent**: `"list_rollback"`

#### 코드 분석
**파일**: `app/services/rollback.py:467-558`

```python
async def get_rollback_list(
    owner: str,
    repo: str,
    db: Session,
    limit: int = 10
) -> Dict[str, Any]:
    """
    롤백 목록 조회: 현재 배포 상태, 롤백 가능한 버전, 최근 롤백 히스토리

    Returns:
        {
            "owner": "K-Le-PaaS",
            "repo": "test-01",
            "current_state": {
                "commit_sha": "abc1234567...",
                "commit_sha_short": "abc1234",
                "deployed_at": "2024-01-01T12:00:00Z",
                "is_rollback": false
            },
            "available_versions": [
                {
                    "steps_back": 0,
                    "commit_sha": "abc1234567...",
                    "commit_sha_short": "abc1234",
                    "deployed_at": "2024-01-01T12:00:00Z",
                    "is_current": true
                },
                {
                    "steps_back": 1,
                    "commit_sha": "def5678901...",
                    "commit_sha_short": "def5678",
                    "deployed_at": "2024-01-01T11:00:00Z",
                    "is_current": false
                }
            ],
            "rollback_history": [
                {
                    "commit_sha_short": "xyz9012",
                    "rolled_back_at": "2024-01-01T10:00:00Z"
                }
            ]
        }
    """
    # 1. 현재 배포 상태
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.deployed_at.desc()
    ).first()

    current_state = None
    if current_deployment:
        current_state = {
            "commit_sha": current_deployment.github_commit_sha,
            "commit_sha_short": current_deployment.github_commit_sha[:7],
            "deployed_at": current_deployment.deployed_at.isoformat(),
            "is_rollback": current_deployment.is_rollback
        }

    # 2. 롤백 가능한 버전 목록 (원본 배포만)
    original_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).limit(limit).all()

    available_versions = []
    current_commit_short = current_deployment.github_commit_sha[:7] if current_deployment else ""

    for idx, dep in enumerate(original_deployments):
        dep_commit_short = dep.github_commit_sha[:7]
        is_current = (dep_commit_short == current_commit_short)

        available_versions.append({
            "steps_back": idx,
            "commit_sha": dep.github_commit_sha,
            "commit_sha_short": dep_commit_short,
            "deployed_at": dep.deployed_at.isoformat(),
            "is_current": is_current
        })

    # 3. 최근 롤백 히스토리
    recent_rollbacks = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == True
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).limit(5).all()

    rollback_history = []
    for rb in recent_rollbacks:
        rollback_history.append({
            "commit_sha_short": rb.github_commit_sha[:7],
            "rolled_back_at": rb.deployed_at.isoformat()
        })

    return {
        "owner": owner,
        "repo": repo,
        "current_state": current_state,
        "available_versions": available_versions,
        "total_available": len(available_versions),
        "rollback_history": rollback_history,
        "total_rollbacks": len(rollback_history)
    }
```

---

## 스케일링 기능

### 명령어 예시
```
"K-Le-PaaS/test-01을 5개로 늘려줘"
"owner/repo를 3개로 스케일"
```

### 코드 분석

#### Step 1: Command Planning (스케일)
**파일**: `app/services/commands.py:127-140`

```python
def plan_command(req: CommandRequest) -> CommandPlan:
    if command == "scale":
        # NCP SourceCommit 기반 스케일링만 지원
        if not req.github_owner or not req.github_repo:
            raise ValueError("스케일링 명령어에는 GitHub 저장소 정보가 필요합니다.")

        return CommandPlan(
            tool="scale",
            args={
                "owner": req.github_owner,
                "repo": req.github_repo,
                "replicas": req.replicas
            },
        )
```

#### Step 2: 스케일링 실행
**파일**: `app/services/rollback.py:561-720`

```python
async def scale_deployment(
    owner: str,
    repo: str,
    replicas: int,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Deployment 스케일링 (Replicas 조정)

    Process:
    1. 프로젝트 통합 정보 조회
    2. 현재 배포 이미지 태그 확인
    3. mirror_and_update_manifest()로 replicas 업데이트
    4. run_sourcedeploy() 호출 (같은 이미지, replicas만 변경)

    Args:
        owner: GitHub 소유자
        repo: GitHub 저장소
        replicas: 목표 replica 수
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        {
            "status": "success",
            "action": "scale",
            "old_replicas": 1,
            "new_replicas": 5,
            "image_tag": "abc1234",
            "deploy_result": {...}
        }
    """
    logger.info(f"Starting scaling for {owner}/{repo} to {replicas} replicas")

    # 검증
    if replicas < 0:
        raise HTTPException(400, "레플리카 수는 0 이상이어야 합니다.")

    if replicas > 10:
        raise HTTPException(400, "레플리카 수는 최대 10개까지 가능합니다.")

    # 1. 통합 정보 조회
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        raise HTTPException(404, "프로젝트 통합 정보를 찾을 수 없습니다.")

    if not integ.sc_project_id:
        raise HTTPException(400, "SourceCommit project ID not configured")

    if not integ.deploy_project_id:
        raise HTTPException(400, "Deploy project ID not configured")

    # 2. 현재 배포 이미지 태그 확인
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).first()

    if not current_deployment:
        raise HTTPException(404, "배포 이력을 찾을 수 없습니다.")

    current_image_tag = current_deployment.github_commit_sha
    logger.info(f"Current image tag: {current_image_tag[:7]}")

    # 3. Manifest 업데이트 (replicas만 변경)
    from .ncp_pipeline import mirror_and_update_manifest, _generate_ncr_image_name
    from .github_app import github_app_auth

    github_token, _ = await github_app_auth.get_installation_token_for_repo(owner, repo, db)
    github_repo_url = f"https://github.com/{owner}/{repo}.git"

    image_name = _generate_ncr_image_name(owner, repo)
    image_repo = f"{settings.ncp_container_registry_url}/{image_name}"

    mirror_result = mirror_and_update_manifest(
        github_repo_url=github_repo_url,
        installation_or_access_token=github_token,
        sc_project_id=integ.sc_project_id,
        sc_repo_name=integ.sc_repo_name or repo,
        image_repo=image_repo,
        image_tag=current_image_tag,  # 같은 이미지 유지
        sc_endpoint=settings.ncp_sourcecommit_endpoint,
        replicas=replicas  # replicas만 업데이트
    )

    old_replicas = mirror_result.get("old_replicas", 1)
    logger.info(f"Manifest updated: {old_replicas} → {replicas} replicas")

    # 4. 트랜잭션 커밋
    db.commit()

    # 5. SourceDeploy 실행 (skip_mirror=True, manifest 이미 업데이트됨)
    from .ncp_pipeline import run_sourcedeploy

    deploy_result = await run_sourcedeploy(
        deploy_project_id=integ.deploy_project_id,
        stage_name="production",
        scenario_name="deploy-app",
        sc_project_id=integ.sc_project_id,
        db=db,
        user_id=user_id,
        owner=owner,
        repo=repo,
        tag=current_image_tag,  # 같은 이미지 사용
        is_rollback=False,
        skip_mirror=True  # manifest 이미 업데이트했으므로 건너뛰기
    )

    return {
        "status": "success",
        "action": "scale",
        "old_replicas": old_replicas,
        "new_replicas": replicas,
        "image_tag": current_image_tag[:7],
        "deploy_result": deploy_result,
        "message": f"Deployment scaled from {old_replicas} to {replicas} replicas"
    }
```

---

## 코드 레벨 상세 분석

### 주요 파일 구조

```
backend-hybrid/
├── app/
│   ├── api/v1/
│   │   └── nlp.py                    # NLP API 엔드포인트
│   ├── services/
│   │   ├── commands.py               # 명령 계획 및 실행
│   │   ├── rollback.py               # 롤백 서비스 (720줄)
│   │   ├── ncp_pipeline.py           # NCP API 통합
│   │   └── deployment_history.py     # 히스토리 기록
│   ├── llm/
│   │   ├── gemini.py                 # Gemini AI 클라이언트
│   │   └── advanced_nlp_service.py   # Advanced NLP (multi-model)
│   └── models/
│       └── deployment_history.py     # DeploymentHistory 모델
```

### Gemini AI Prompt 예시

**파일**: `app/llm/gemini.py` (함수: `interpret()`)

Gemini에게 보내는 프롬프트 구조:
```
당신은 Kubernetes 및 NCP 리소스 관리 전문가입니다.
사용자의 자연어 명령을 분석하여 다음 JSON 형식으로 응답하세요:

{
  "intent": "rollback | deploy | scale | status | logs | ...",
  "message": "사용자에게 보여줄 친절한 메시지",
  "entities": {
    "github_owner": "소유자 이름",
    "github_repo": "저장소 이름",
    "steps_back": 3,
    "replicas": 5,
    ...
  }
}

지원하는 intent:
- rollback: 이전 버전으로 롤백
- deploy: 애플리케이션 배포
- scale: Pod 개수 조정
- status: 리소스 상태 확인
- logs: 로그 조회
- restart: 재시작
- list_pods: Pod 목록
- list_rollback: 롤백 가능한 버전 목록

예시:
입력: "K-Le-PaaS/test-01을 3번 전으로 롤백해줘"
출력:
{
  "intent": "rollback",
  "message": "K-Le-PaaS/test-01 애플리케이션을 3번 전 버전으로 롤백합니다.",
  "entities": {
    "github_owner": "K-Le-PaaS",
    "github_repo": "test-01",
    "steps_back": 3
  }
}

사용자 입력: "{user_input}"
```

### 배포 히스토리 스키마

```sql
CREATE TABLE deployment_histories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR NOT NULL,
    github_owner VARCHAR NOT NULL,
    github_repo VARCHAR NOT NULL,
    github_commit_sha VARCHAR NOT NULL,
    github_commit_message VARCHAR,

    environment VARCHAR,  -- 'staging', 'production'
    status VARCHAR,       -- 'pending', 'success', 'failed'
    image_name VARCHAR,   -- 'klepaas-test.kr.ncr.ntruss.com/k-le-paas-test-01:abc1234'

    is_rollback BOOLEAN DEFAULT FALSE,
    rollback_from_id INTEGER REFERENCES deployment_histories(id),

    deployed_at DATETIME,
    created_at DATETIME DEFAULT (datetime('now', '+9 hours'))
);

-- 인덱스
CREATE INDEX idx_deployment_history_owner_repo
  ON deployment_histories(github_owner, github_repo, status, created_at DESC);
```

### 롤백 흐름 다이어그램

```
사용자: "K-Le-PaaS/test-01을 3번 전으로 롤백"
    │
    ▼
[Gemini AI]
    │ intent: "rollback"
    │ entities: {owner: "K-Le-PaaS", repo: "test-01", steps_back: 3}
    ▼
[plan_command()]
    │ CommandPlan(tool="rollback_deployment", args={...})
    ▼
[execute_command()]
    │ _execute_rollback_deployment()
    ▼
[rollback_to_previous()]
    │
    ├─> 1. 현재 배포 조회 (가장 최근 성공)
    │   → commit: "abc1234" (current)
    │
    ├─> 2. 원본 배포 목록 조회 (is_rollback=False)
    │   → [
    │       {commit: "abc1234", index: 0},  ← current
    │       {commit: "def5678", index: 1},
    │       {commit: "ghi9012", index: 2},
    │       {commit: "jkl3456", index: 3}   ← target
    │     ]
    │
    ├─> 3. target_index = 0 + 3 = 3
    │   → target_commit = "jkl3456"
    │
    ▼
[rollback_to_commit("jkl3456")]
    │
    ├─> 1. 프로젝트 통합 정보 조회
    │   → deploy_project_id, sc_project_id
    │
    ├─> 2. 배포 히스토리에서 "jkl3456" 찾기
    │   → history.image_name = "...k-le-paas-test-01:jkl3456"
    │
    ├─> 3. NCR 이미지 검증 건너뛰기 (재사용)
    │
    ├─> 4. mirror_and_update_manifest()
    │   → k8s/deployment.yaml의 image를 "...jkl3456"로 변경
    │   → SourceCommit에 Push
    │
    ▼
[run_sourcedeploy()]
    │
    ├─> 1. SourceDeploy API 호출
    │   → NKS 클러스터에 배포
    │
    ├─> 2. DeploymentHistory 기록
    │   → is_rollback=True
    │
    ▼
[NKS Cluster]
    │
    ├─> 1. k8s/deployment.yaml 적용
    │   → image: "...jkl3456"
    │
    ├─> 2. Rolling Update
    │   → 새 Pod 생성 (이미지: jkl3456)
    │   → 기존 Pod 종료
    │
    ▼
롤백 완료 ✓
```

---

## 마무리

이 문서는 NLP를 통한 배포 및 롤백 기능을 코드 레벨에서 상세하게 설명했습니다.

### 핵심 포인트
1. **Gemini AI는 자연어를 structured intent로 변환**합니다.
2. **롤백은 DeploymentHistory 테이블 기반**으로 작동합니다.
3. **rollback_to_previous는 steps_back 계산**을 통해 타겟 커밋을 찾습니다.
4. **rollback_to_commit은 실제 SourceDeploy를 실행**합니다.
5. **스케일링은 manifest의 replicas만 변경**하고 재배포합니다.
6. **모든 배포/롤백은 is_rollback 플래그로 구분**됩니다.

### 관련 문서
- [01-github-to-ncp-pipeline.md](./01-github-to-ncp-pipeline.md) - GitHub → NCP 파이프라인
- [03-troubleshooting.md](./03-troubleshooting.md) - 트러블슈팅 가이드
