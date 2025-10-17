# 롤백 기능 아키텍처

## 개요

자연어 처리를 통한 NCP 파이프라인 롤백 기능의 아키텍처 설계 문서입니다.

## 아키텍처 설계 원칙

### 기존 패턴 준수

K-Le-PaaS의 자연어 처리 아키텍처는 다음과 같은 계층 구조를 따릅니다:

```
사용자 자연어 명령
    ↓
app/api/v1/nlp.py (엔드포인트)
    ↓
Gemini API (자연어 해석)
    ↓ (intent, entities 추출)
app/services/commands.py (명령 계획 및 실행)
    ↓
실제 비즈니스 로직 (K8s API, NCP API, etc.)
```

롤백 기능도 이 패턴을 정확히 따르도록 설계되었습니다.

## 구성 요소

### 1. API 계층 (`app/api/v1/nlp.py`)

**역할**: 자연어 명령을 수신하고 Gemini를 통해 해석

```python
@router.post("/nlp/process")
async def process_command(command_data: NaturalLanguageCommand, db: Session = Depends(get_db)):
    # 1. 명령 유효성 검사
    # 2. Gemini API 호출하여 자연어 해석
    # 3. Gemini 결과를 CommandRequest로 변환
    # 4. commands.py의 plan_command, execute_command 호출
```

**중요**: 이 계층에서는 비즈니스 로직을 직접 처리하지 않습니다.

### 2. 명령 처리 계층 (`app/services/commands.py`)

#### 2.1 CommandRequest 모델

```python
class CommandRequest(BaseModel):
    command: str                    # 명령 타입 (예: "ncp_rollback")
    # K8s 관련 필드
    pod_name: str
    deployment_name: str
    service_name: str
    # NCP 롤백 관련 필드
    github_owner: str               # 저장소 소유자
    github_repo: str                # 저장소 이름
    target_commit_sha: str          # 롤백할 커밋 SHA
    steps_back: int                 # N번 전 롤백
```

#### 2.2 plan_command 함수

명령을 실행 계획(CommandPlan)으로 변환:

```python
def plan_command(req: CommandRequest) -> CommandPlan:
    if req.command == "ncp_rollback":
        # 저장소 정보 유효성 검사
        if not req.github_owner or not req.github_repo:
            raise ValueError("GitHub 저장소 정보가 필요합니다")

        return CommandPlan(
            tool="ncp_rollback_deployment",
            args={
                "owner": req.github_owner,
                "repo": req.github_repo,
                "target_commit_sha": req.target_commit_sha,
                "steps_back": req.steps_back
            }
        )
```

#### 2.3 execute_command 함수

실행 계획을 실제 작업으로 변환:

```python
async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    if plan.tool == "ncp_rollback_deployment":
        return await _execute_ncp_rollback(plan.args)
```

#### 2.4 _execute_ncp_rollback 함수

NCP 파이프라인 롤백 실행:

```python
async def _execute_ncp_rollback(args: Dict[str, Any]) -> Dict[str, Any]:
    from .rollback import rollback_to_commit, rollback_to_previous

    # 커밋 SHA 지정된 경우
    if args.get("target_commit_sha"):
        result = await rollback_to_commit(
            owner=args["owner"],
            repo=args["repo"],
            target_commit_sha=args["target_commit_sha"],
            db=db,
            user_id="nlp_user"
        )
    # N번 전 지정된 경우
    elif args.get("steps_back") > 0:
        result = await rollback_to_previous(
            owner=args["owner"],
            repo=args["repo"],
            steps_back=args["steps_back"],
            db=db,
            user_id="nlp_user"
        )
    # 기본값: 1번 전
    else:
        result = await rollback_to_previous(
            owner=args["owner"],
            repo=args["repo"],
            steps_back=1,
            db=db,
            user_id="nlp_user"
        )

    return {"status": "success", "result": result}
```

### 3. 비즈니스 로직 계층 (`app/services/rollback.py`)

실제 롤백 로직 구현:

- `rollback_to_commit()`: 특정 커밋 SHA로 롤백
- `rollback_to_previous()`: N번 전 배포로 롤백
- `get_rollback_candidates()`: 롤백 가능한 배포 목록 조회

### 4. REST API 계층 (`app/api/v1/rollback.py`)

직접 REST API 호출을 위한 엔드포인트:

- `POST /api/v1/rollback/commit`: 특정 커밋으로 롤백
- `POST /api/v1/rollback/previous`: N번 전 배포로 롤백
- `POST /api/v1/rollback/candidates`: 롤백 후보 목록 조회

## 데이터 흐름

### 자연어 명령 처리 흐름

```
사용자: "myorg/myapp를 3번 전으로 롤백해줘"
    ↓
nlp.py: POST /api/v1/nlp/process
    ↓
Gemini API 호출
    ↓
Gemini 응답:
{
  "intent": "ncp_rollback",
  "entities": {
    "github_owner": "myorg",
    "github_repo": "myapp",
    "steps_back": 3
  }
}
    ↓
CommandRequest 생성:
{
  "command": "ncp_rollback",
  "github_owner": "myorg",
  "github_repo": "myapp",
  "steps_back": 3
}
    ↓
plan_command() 호출
    ↓
CommandPlan 생성:
{
  "tool": "ncp_rollback_deployment",
  "args": {
    "owner": "myorg",
    "repo": "myapp",
    "steps_back": 3
  }
}
    ↓
execute_command() 호출
    ↓
_execute_ncp_rollback() 실행
    ↓
rollback_to_previous(owner="myorg", repo="myapp", steps_back=3) 호출
    ↓
deployment_histories 테이블에서 3번째 이전 배포 조회
    ↓
해당 커밋 SHA로 ncp_pipeline.run_sourcedeploy() 호출
    ↓
매니페스트 업데이트 및 배포
    ↓
응답 반환
```

## Gemini 통합

### Gemini의 역할

Gemini는 자연어 명령을 구조화된 데이터로 변환:

**입력**:
```
"myorg/myapp를 3번 전으로 롤백해줘"
```

**출력**:
```json
{
  "intent": "ncp_rollback",
  "entities": {
    "github_owner": "myorg",
    "github_repo": "myapp",
    "steps_back": 3
  },
  "message": "myorg/myapp 저장소를 3번 전 배포로 롤백합니다."
}
```

### 지원되는 자연어 패턴

1. **저장소 정보 추출**:
   - "owner/repo를 롤백" → github_owner="owner", github_repo="repo"
   - Context에서 제공: `{"github_owner": "owner", "github_repo": "repo"}`

2. **N번 전 패턴**:
   - "3번 전으로 롤백" → steps_back=3
   - "2 deployments ago" → steps_back=2

3. **커밋 해시 패턴**:
   - "커밋 abc1234로 롤백" → target_commit_sha="abc1234"
   - "rollback to abc1234567890abcdef" → target_commit_sha="abc1234567890abcdef"

4. **이전 버전**:
   - "이전 버전으로 롤백" → steps_back=1
   - "previous deployment" → steps_back=1

## 확장성

### 새로운 롤백 타입 추가

1. `CommandRequest`에 필드 추가
2. `plan_command()`에 새로운 command 케이스 추가
3. `execute_command()`에 새로운 tool 핸들러 추가
4. 새로운 `_execute_*` 함수 구현

### 다른 클라우드 프로바이더 지원

동일한 패턴으로 GCP, AWS 롤백 지원 가능:

```python
elif command == "gcp_rollback":
    return CommandPlan(
        tool="gcp_rollback_deployment",
        args={"project": req.gcp_project, "region": req.gcp_region, ...}
    )
```

## 에러 처리

### 유효성 검사

1. **nlp.py**: 명령어 길이, 위험한 키워드 체크
2. **plan_command()**: 필수 필드 존재 여부 검사
3. **_execute_ncp_rollback()**: 비즈니스 로직 오류 처리

### 에러 응답 형식

```json
{
  "status": "error",
  "action": "ncp_rollback",
  "message": "롤백 실패: deployment_histories에서 배포를 찾을 수 없습니다",
  "owner": "myorg",
  "repo": "myapp"
}
```

## 보안

### 권한 관리

- REST API는 OAuth2/JWT 토큰으로 인증
- NLP 엔드포인트는 `db: Session = Depends(get_db)` 통해 세션 관리
- 롤백 작업은 audit_log에 기록

### 입력 검증

- 커밋 SHA 형식 검증 (7-40자 hex)
- steps_back 범위 제한 (0-10)
- 저장소 이름 패턴 검증

## 테스트 전략

### 단위 테스트

```python
# commands.py 테스트
def test_plan_ncp_rollback():
    req = CommandRequest(
        command="ncp_rollback",
        github_owner="myorg",
        github_repo="myapp",
        steps_back=3
    )
    plan = plan_command(req)
    assert plan.tool == "ncp_rollback_deployment"
    assert plan.args["steps_back"] == 3
```

### 통합 테스트

```python
# nlp.py 엔드포인트 테스트
async def test_nlp_rollback_command():
    response = await client.post("/api/v1/nlp/process", json={
        "command": "myorg/myapp를 3번 전으로 롤백",
        "timestamp": "2024-01-01T00:00:00Z"
    })
    assert response.status_code == 200
    assert response.json()["success"] == True
```

## 성능 고려사항

### 데이터베이스 쿼리 최적화

- `deployment_histories` 테이블에 인덱스 추가:
  - `(github_owner, github_repo, created_at DESC)`

### 캐싱

- 롤백 후보 목록은 Redis에 캐싱 가능
- TTL: 5분

## 모니터링

### 메트릭

- `ncp_rollback_total`: 롤백 요청 총 횟수
- `ncp_rollback_success`: 성공한 롤백 횟수
- `ncp_rollback_duration_seconds`: 롤백 소요 시간

### 로깅

```python
logger.info(
    "ncp_rollback_start",
    owner=owner,
    repo=repo,
    steps_back=steps_back,
    user_id=user_id
)
```

## 참고 자료

- [ROLLBACK_FEATURE_IMPLEMENTATION.md](./ROLLBACK_FEATURE_IMPLEMENTATION.md): 구현 상세 내역
- [app/services/commands.py](../app/services/commands.py): 명령 처리 로직
- [app/services/rollback.py](../app/services/rollback.py): 롤백 비즈니스 로직
- [app/api/v1/nlp.py](../app/api/v1/nlp.py): NLP 엔드포인트
