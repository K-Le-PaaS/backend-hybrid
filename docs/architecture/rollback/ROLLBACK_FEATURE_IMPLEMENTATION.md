# 롤백 기능 구현 완료 보고서

## 📋 개요

자연어 처리를 통한 배포 롤백 기능이 완전히 구현되었습니다. 이제 사용자는 자연어 명령을 통해 이전 버전으로 쉽게 롤백할 수 있으며, 모든 배포에 대해 커밋 해시 기반의 이미지 태그가 자동으로 적용됩니다.

## ✅ 구현 완료 항목

### 1. 이미지 태그 동적화 (Commit SHA 기반)

#### 📝 수정 파일: `app/services/ncp_pipeline.py`

**1.1. `mirror_to_sourcecommit` 함수 업데이트**
- `commit_sha` 파라미터 추가
- 매니페스트 자동 주입 시 `latest` 대신 커밋 해시 사용
- 라인 1029-1251: 함수 시그니처 및 이미지 태그 로직 수정

```python
# 변경 전
image_full = f"{registry}/{image_name_unified}:latest"

# 변경 후
image_tag = commit_sha[:7] if commit_sha else "latest"
image_full = f"{registry}/{image_name_unified}:{image_tag}"
```

**1.2. `mirror_and_update_manifest` 호출 시 commit_sha 전달**
- 라인 1293-1304: `mirror_to_sourcecommit` 호출 시 `image_tag` 파라미터 전달

### 2. Deployment History 자동 기록

#### 📝 수정 파일: `app/services/ncp_pipeline.py`

**2.1. `run_sourcedeploy` 함수 업데이트**
- 배포 완료 후 `deployment_histories` 테이블에 자동 기록
- 커밋 SHA, 이미지 태그, 빌드/배포 프로젝트 ID 등 모든 메타데이터 저장
- 라인 2439-2476: History 기록 로직 추가

```python
history_record = DeploymentHistory(
    user_id=user_id,
    github_owner=owner,
    github_repo=repo,
    github_commit_sha=effective_tag,  # 커밋 해시 저장
    image_tag=effective_tag,  # 이미지 태그 저장
    image_url=desired_image,
    # ... 기타 메타데이터
)
```

### 3. 자연어 롤백 명령 처리

#### 📝 수정 파일: `app/services/commands.py`

**3.1. `CommandRequest` 모델 확장**
- NCP 롤백 관련 필드 추가:
  ```python
  github_owner: str = Field(default="")      # GitHub 저장소 소유자
  github_repo: str = Field(default="")       # GitHub 저장소 이름
  target_commit_sha: str = Field(default="") # 롤백할 커밋 SHA
  steps_back: int = Field(default=0, ge=0)   # 몇 번 전으로 롤백할지
  ```

**3.2. `plan_command` 함수에 ncp_rollback 명령 추가**
- 명령어: "ncp_rollback"
- Gemini가 롤백 명령을 "ncp_rollback"으로 해석하면 자동 처리
- 저장소 정보 유효성 검사 수행

**3.3. `_execute_ncp_rollback` 함수 구현**
- deployment_histories 테이블 기반 롤백 실행
- 지원 시나리오:
  - 커밋 SHA 지정: `rollback_to_commit()` 호출
  - N번 전 지정: `rollback_to_previous(steps_back=N)` 호출
  - 기본값: `rollback_to_previous(steps_back=1)` 호출

### 4. NLP 엔드포인트 통합

#### 📝 수정 파일: `app/api/v1/nlp.py`

**4.1. 자연어 처리 흐름**
1. Gemini가 자연어 명령 해석 (intent, entities 추출)
2. Gemini 결과를 `CommandRequest`로 변환
3. `plan_command()`로 실행 계획 생성
4. `execute_command()`로 실제 작업 수행

**4.2. 롤백 명령 예시**
- "owner/repo를 3번 전으로 롤백해줘"
  - Gemini → intent: "ncp_rollback", entities: {github_owner, github_repo, steps_back}
  - CommandRequest → command: "ncp_rollback", github_owner, github_repo, steps_back
  - plan_command → tool: "ncp_rollback_deployment"
  - execute_command → _execute_ncp_rollback → rollback_to_previous()

### 5. 롤백 REST API 엔드포인트

#### 📝 신규 파일: `app/api/v1/rollback.py`

**5.1. API 엔드포인트**

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/rollback/commit` | POST | 특정 커밋 SHA로 롤백 |
| `/api/v1/rollback/previous` | POST | N번 전 배포로 롤백 |
| `/api/v1/rollback/candidates` | POST | 롤백 가능한 배포 목록 조회 |
| `/api/v1/rollback/candidates/{owner}/{repo}` | GET | 롤백 후보 조회 (GET 버전) |

**5.2. 요청/응답 모델**
- `RollbackToCommitRequest`: 커밋 SHA 롤백 요청
- `RollbackToPreviousRequest`: N번 전 롤백 요청
- `RollbackCandidatesRequest`: 후보 목록 조회 요청
- `RollbackResponse`: 롤백 결과 응답
- `RollbackCandidatesResponse`: 후보 목록 응답

### 6. 라우터 등록

#### 📝 수정 파일: `app/main.py`

**6.1. 롤백 라우터 import 및 등록**
```python
from .api.v1.rollback import router as rollback_router
app.include_router(rollback_router, prefix="/api/v1", tags=["rollback"])
```

## 🎯 사용 예시

### 1. 자연어 명령 (NLP)

```bash
# 이전 버전으로 롤백
POST /api/v1/nlp/process
{
  "command": "myorg/myapp를 이전 버전으로 롤백해줘",
  "timestamp": "2024-01-01T00:00:00Z"
}

# 3번 전 배포로 롤백
POST /api/v1/nlp/process
{
  "command": "myorg/myapp를 3번 전으로 롤백",
  "timestamp": "2024-01-01T00:00:00Z"
}

# 특정 커밋으로 롤백
POST /api/v1/nlp/process
{
  "command": "myorg/myapp를 커밋 abc1234로 롤백",
  "timestamp": "2024-01-01T00:00:00Z"
}

# Context로 저장소 정보 전달
POST /api/v1/nlp/process
{
  "command": "이전 버전으로 롤백해줘",
  "timestamp": "2024-01-01T00:00:00Z",
  "context": {
    "github_owner": "myorg",
    "github_repo": "myapp"
  }
}
```

**처리 흐름**:
1. Gemini가 명령어를 해석하여 intent="ncp_rollback" 추출
2. 명령어 또는 context에서 owner/repo 정보 추출
3. CommandRequest 생성 (command="ncp_rollback", github_owner, github_repo, steps_back/target_commit_sha)
4. commands.py의 plan_command → execute_command 경로로 실행
5. `_execute_ncp_rollback` 이 `rollback.py` 함수 호출

### 2. REST API 직접 호출

```bash
# 특정 커밋으로 롤백
POST /api/v1/rollback/commit
{
  "owner": "myorg",
  "repo": "myapp",
  "target_commit_sha": "abc1234567890abcdef1234567890abcdef1234",
  "user_id": "user123"
}

# 3번 전 배포로 롤백
POST /api/v1/rollback/previous
{
  "owner": "myorg",
  "repo": "myapp",
  "steps_back": 3,
  "user_id": "user123"
}

# 롤백 가능한 버전 목록 조회
GET /api/v1/rollback/candidates/myorg/myapp?limit=10

# 또는 POST
POST /api/v1/rollback/candidates
{
  "owner": "myorg",
  "repo": "myapp",
  "limit": 10
}
```

### 3. 응답 예시

```json
{
  "status": "success",
  "action": "rollback_to_commit",
  "message": "커밋 abc1234로 롤백했습니다.",
  "result": {
    "target_commit": "abc1234567890abcdef",
    "target_commit_short": "abc1234",
    "image": "kr.ncr.ntruss.com/myorg_myapp:abc1234",
    "rebuilt": false,
    "deploy_result": {
      "status": "started",
      "deploy_project_id": "12345",
      "manifest_updated": true
    }
  }
}
```

## 📊 데이터 흐름

### 배포 시 (Commit SHA → Image Tag)

```
GitHub Push (commit: abc1234)
  ↓
handle_push_event (cicd.py)
  ↓
run_sourcedeploy (tag=abc1234)
  ↓
mirror_and_update_manifest (image_tag=abc1234)
  ↓
mirror_to_sourcecommit (commit_sha=abc1234)
  ↓
k8s/deployment.yaml (image: registry/app:abc1234)
  ↓
DeploymentHistory 기록
  - github_commit_sha: abc1234
  - image_tag: abc1234
  - image_url: registry/app:abc1234
```

### 롤백 시 (History → Rollback)

```
자연어 명령: "3번 전으로 롤백"
  ↓
RollbackCommandParser.parse_rollback_command()
  → type: "steps_back", value: 3
  ↓
process_rollback_command()
  ↓
rollback_to_previous(steps_back=3)
  ↓
DeploymentHistory 조회 (3번째 이전 배포)
  → commit_sha: xyz5678
  ↓
rollback_to_commit(target_commit_sha=xyz5678)
  ↓
run_sourcedeploy(tag=xyz5678)
  ↓
mirror_and_update_manifest (image_tag=xyz5678)
  ↓
k8s/deployment.yaml (image: registry/app:xyz5678)
  ↓
새로운 DeploymentHistory 기록 (롤백)
```

## 🔧 설정

### 환경 변수

롤백 기능은 기존 NCP Pipeline 환경 변수를 사용합니다:

```bash
# NCP Container Registry
KLEPAAS_NCP_CONTAINER_REGISTRY_URL=kr.ncr.ntruss.com

# SourceCommit/SourceDeploy
KLEPAAS_NCP_SOURCECOMMIT_ENDPOINT=https://sourcecommit.apigw.ntruss.com
KLEPAAS_NCP_SOURCEDEPLOY_ENDPOINT=https://vpcsourcedeploy.apigw.ntruss.com

# GitHub Integration
KLEPAAS_GITHUB_WEBHOOK_SECRET=your_webhook_secret
KLEPAAS_GITHUB_APP_ID=your_app_id
KLEPAAS_GITHUB_APP_PRIVATE_KEY=your_private_key

# Database
KLEPAAS_DATABASE_URL=sqlite:///./klepaas.db  # 또는 PostgreSQL URL
```

### 데이터베이스 마이그레이션

`deployment_histories` 테이블은 이미 다음 필드를 포함하고 있습니다:
- `github_commit_sha`: 커밋 해시
- `image_tag`: 이미지 태그
- `image_url`: 전체 이미지 URL

추가 마이그레이션 불필요.

## 🧪 테스트 방법

### 1. 배포 테스트

```bash
# GitHub에 커밋 푸시
git commit -m "Test feature"
git push origin main

# deployment_histories 확인
# image_tag가 커밋 SHA로 저장되었는지 확인
```

### 2. 롤백 테스트

```bash
# 자연어 명령 테스트
curl -X POST http://localhost:8080/api/v1/nlp/process \
  -H "Content-Type: application/json" \
  -d '{
    "command": "이전 버전으로 롤백해줘",
    "context": {
      "owner": "myorg",
      "repo": "myapp",
      "user_id": "test_user"
    }
  }'

# REST API 직접 테스트
curl -X POST http://localhost:8080/api/v1/rollback/previous \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "myorg",
    "repo": "myapp",
    "steps_back": 1,
    "user_id": "test_user"
  }'

# 롤백 후보 조회
curl -X GET "http://localhost:8080/api/v1/rollback/candidates/myorg/myapp?limit=5"
```

### 3. 통합 테스트

```python
# tests/test_rollback_integration.py
import pytest
from app.services.nlp_rollback import RollbackCommandParser, process_rollback_command

def test_rollback_command_parser():
    # N번 전 패턴
    result = RollbackCommandParser.parse_rollback_command("3번 전으로 롤백")
    assert result["type"] == "steps_back"
    assert result["value"] == 3

    # 커밋 해시 패턴
    result = RollbackCommandParser.parse_rollback_command("커밋 abc1234로 롤백")
    assert result["type"] == "commit_sha"
    assert result["value"] == "abc1234"

    # 이전 버전
    result = RollbackCommandParser.parse_rollback_command("이전 버전으로 롤백")
    assert result["type"] == "previous"

# 실행
pytest tests/test_rollback_integration.py -v
```

## 📚 API 문서

Swagger UI에서 롤백 API 문서 확인:
- http://localhost:8080/docs#/rollback

## 🎉 완료된 기능

✅ **커밋 해시 기반 이미지 태그**
- 모든 배포에 자동으로 커밋 SHA가 이미지 태그로 사용됨
- `latest` 태그 대신 실제 커밋 해시 사용

✅ **자동 History 기록**
- 배포 시 자동으로 `deployment_histories` 테이블에 기록
- 커밋 SHA, 이미지 정보, 빌드/배포 ID 모두 저장

✅ **자연어 롤백 명령**
- "이전 버전으로 롤백", "3번 전으로 롤백", "커밋 abc1234로 롤백" 등 지원
- 명령어에서 저장소 정보 추출 가능

✅ **롤백 REST API**
- 특정 커밋으로 롤백
- N번 전 배포로 롤백
- 롤백 가능한 버전 목록 조회

✅ **NLP 통합**
- `/api/v1/nlp/process` 엔드포인트에서 롤백 명령 자동 감지
- 컨텍스트 기반 저장소 정보 추출

## 🔜 향후 개선 사항

1. **UI 통합**: 프론트엔드에서 롤백 버튼 및 히스토리 표시  
2. **알림**: 롤백 성공/실패 시 Slack 알림  
3. **권한 관리**: 롤백 권한 체크 (특정 사용자만 롤백 가능)  
4. **롤백 승인**: 프로덕션 롤백 시 승인 워크플로우  
5. **자동 롤백**: 배포 실패 시 자동 롤백 옵션  
6. **롤백 통계**: 롤백 빈도, 성공률 등 대시보드  

## 📞 문의

구현 관련 질문이나 버그 리포트는 GitHub Issues를 통해 제출해주세요.


