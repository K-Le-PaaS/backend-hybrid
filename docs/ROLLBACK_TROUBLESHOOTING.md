# 롤백 기능 문제 해결 가이드

## 개요

K-Le-PaaS의 롤백 기능이 제대로 작동하려면 다음 세 가지 요소가 필요합니다:

1. **프로젝트 통합(Integration) 설정**: `build_project_id`, `deploy_project_id`
2. **배포 히스토리(Deployment History)**: 성공적인 배포 기록
3. **NCR 이미지(Container Image)**: 롤백하려는 커밋의 컨테이너 이미지

## 자주 발생하는 에러

### 1. "No project integration found"

**에러 메시지:**
```
404: No project integration found for K-Le-PaaS/test01. Please set up the project first using the deployment API.
```

**원인:**
- `user_project_integrations` 테이블에 해당 저장소에 대한 통합 정보가 없음

**해결 방법:**

1. **프로젝트 통합 생성 API 호출:**
   ```bash
   POST /api/v1/projects/integrations
   {
     "owner": "K-Le-PaaS",
     "repo": "test01",
     "user_id": "your_user_id",
     "sc_project_id": "your_sc_project_id",
     "sc_repo_name": "your_sc_repo_name",
     "branch": "main"
   }
   ```

2. **직접 데이터베이스에 삽입 (개발 환경):**
   ```sql
   INSERT INTO user_project_integrations (
     user_id, github_owner, github_repo,
     sc_project_id, sc_repo_name, branch,
     created_at, updated_at
   ) VALUES (
     'nlp_user', 'K-Le-PaaS', 'test01',
     123456, 'test01', 'main',
     NOW(), NOW()
   );
   ```

### 2. "Build project ID not configured"

**에러 메시지:**
```
400: Build project ID not configured for K-Le-PaaS/test01. Please complete project setup.
```

**원인:**
- 프로젝트 통합은 있지만 `build_project_id`가 설정되지 않음

**해결 방법:**

1. **SourceBuild 프로젝트 생성 후 ID 업데이트:**
   ```bash
   POST /api/v1/deployments/ncp-pipeline
   {
     "owner": "K-Le-PaaS",
     "repo": "test01",
     "github_ref": "refs/heads/main",
     "github_sha": "latest_commit_sha"
   }
   ```

2. **직접 업데이트 (개발 환경):**
   ```sql
   UPDATE user_project_integrations
   SET build_project_id = 12345678
   WHERE github_owner = 'K-Le-PaaS' AND github_repo = 'test01';
   ```

### 3. "No deployment history found"

**에러 메시지:**
```
404: No deployment history found for K-Le-PaaS/test01. Deploy the application first before attempting rollback.
```

**원인:**
- `deployment_histories` 테이블에 성공적인 배포 기록이 없음

**해결 방법:**

1. **먼저 애플리케이션 배포:**
   ```bash
   POST /api/v1/deployments/ncp-pipeline
   {
     "owner": "K-Le-PaaS",
     "repo": "test01",
     "github_ref": "refs/heads/main",
     "github_sha": "current_commit_sha"
   }
   ```

2. **배포 기록 확인:**
   ```bash
   GET /api/v1/rollback/candidates/K-Le-PaaS/test01
   ```

### 4. "No successful deployment found for commit"

**에러 메시지:**
```
404: No successful deployment found for commit c39eb54. Cannot rollback to undeployed commit.
```

**원인:**
- 특정 커밋의 성공적인 배포 기록이 없음
- `rollback_to_previous`를 통해 자동으로 선택된 커밋이지만 실제로는 배포된 적이 없음

**해결 방법:**

1. **롤백 가능한 배포 목록 확인:**
   ```bash
   GET /api/v1/rollback/candidates/K-Le-PaaS/test01
   ```

2. **올바른 커밋 SHA로 롤백 시도:**
   ```bash
   POST /api/v1/rollback/commit
   {
     "owner": "K-Le-PaaS",
     "repo": "test01",
     "target_commit_sha": "valid_commit_sha_from_candidates"
   }
   ```

### 5. "Latest deployment image not found in NCR"

**경고 메시지:**
```
Latest deployment image not found in NCR (HTTP 404). Rollback will trigger rebuild.
```

**원인:**
- NCR(NCP Container Registry)에 해당 커밋 SHA를 태그로 가진 이미지가 없음
- 이미지가 삭제되었거나 빌드가 실패했을 수 있음

**해결 방법:**

1. **롤백은 여전히 가능** - 자동으로 이미지를 다시 빌드합니다
2. **수동으로 이미지 확인:**
   ```bash
   # NCR 이미지 목록 조회
   curl -u $NCP_ACCESS_KEY:$NCP_SECRET_KEY \
     https://contest27-klepaas-build-handle.kr.ncr.ntruss.com/v2/k-le-paas-test01/tags/list
   ```

## 진단 도구 사용

### 롤백 준비 상태 진단

롤백을 시도하기 전에 진단 API를 사용하여 준비 상태를 확인하세요:

```bash
GET /api/v1/rollback/diagnose/K-Le-PaaS/test01?user_id=nlp_user
```

**응답 예시 (준비 완료):**
```json
{
  "ready": true,
  "owner": "K-Le-PaaS",
  "repo": "test01",
  "issues": [],
  "warnings": [
    "Latest deployment image not found in NCR (HTTP 404). Rollback will trigger rebuild."
  ],
  "deployment_count": 5,
  "latest_deployment": {
    "commit_sha": "abc1234567890",
    "deployed_at": "2025-10-19T12:00:00Z"
  }
}
```

**응답 예시 (준비 안됨):**
```json
{
  "ready": false,
  "owner": "K-Le-PaaS",
  "repo": "test01",
  "issues": [
    "No project integration found. Set up the project first.",
    "No deployment history found. Deploy the application first."
  ],
  "warnings": [],
  "deployment_count": null,
  "latest_deployment": null
}
```

## 완전한 롤백 설정 체크리스트

### 1단계: 프로젝트 통합 확인

```sql
SELECT * FROM user_project_integrations
WHERE github_owner = 'K-Le-PaaS' AND github_repo = 'test01';
```

**필수 필드:**
- `build_project_id` (NOT NULL)
- `deploy_project_id` (NOT NULL)
- `sc_project_id` (NOT NULL)
- `sc_repo_name` (NOT NULL)

### 2단계: 배포 히스토리 확인

```sql
SELECT github_commit_sha, deployed_at, status, is_rollback
FROM deployment_histories
WHERE github_owner = 'K-Le-PaaS' AND github_repo = 'test01'
  AND status = 'success'
  AND is_rollback = false
ORDER BY created_at DESC
LIMIT 10;
```

**필수 조건:**
- 최소 1개 이상의 성공적인 배포 기록
- 롤백하려는 커밋의 배포 기록이 있어야 함

### 3단계: NCR 이미지 확인

```bash
# 이미지 태그 목록 확인
curl -u $NCP_ACCESS_KEY:$NCP_SECRET_KEY \
  https://contest27-klepaas-build-handle.kr.ncr.ntruss.com/v2/k-le-paas-test01/tags/list

# 특정 이미지 매니페스트 확인
curl -u $NCP_ACCESS_KEY:$NCP_SECRET_KEY \
  https://contest27-klepaas-build-handle.kr.ncr.ntruss.com/v2/k-le-paas-test01/manifests/COMMIT_SHA
```

## 자연어 롤백 명령어 사용 예시

### 성공 케이스

**명령어:**
```
K-Le-PaaS/test01 롤백 해줘
```

**로그 출력:**
```
INFO - Starting rollback to previous deployment: K-Le-PaaS/test01, steps_back=1
INFO - Found 5 successful deployment(s) for K-Le-PaaS/test01
INFO - Target deployment: commit=abc1234, deployed_at=2025-10-19T10:00:00Z
INFO - Starting rollback for K-Le-PaaS/test01 to commit abc1234
INFO - Project integration found: build_project_id=12345, deploy_project_id=67890
INFO - Found deployment history: deployed_at=2025-10-19T10:00:00Z, image=...
INFO - NCR image verification result: exists=True, code=200
INFO - Rollback completed successfully
```

### 실패 케이스 (통합 없음)

**명령어:**
```
K-Le-PaaS/new-project 롤백 해줘
```

**로그 출력:**
```
INFO - Starting rollback to previous deployment: K-Le-PaaS/new-project, steps_back=1
ERROR - No deployment history found for K-Le-PaaS/new-project
```

**에러 응답:**
```json
{
  "status": "error",
  "action": "ncp_rollback",
  "message": "NCP 롤백 실패: 404: No deployment history found for K-Le-PaaS/new-project. Deploy the application first before attempting rollback.",
  "owner": "K-Le-PaaS",
  "repo": "new-project"
}
```

## 추가 디버깅 팁

### 로그 레벨 증가

```python
# app/main.py 또는 환경 변수
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 데이터베이스 직접 조회

```sql
-- 프로젝트 통합 상태
SELECT * FROM user_project_integrations;

-- 배포 히스토리
SELECT * FROM deployment_histories
ORDER BY created_at DESC LIMIT 20;

-- 최근 롤백 시도
SELECT * FROM deployment_histories
WHERE is_rollback = true
ORDER BY created_at DESC LIMIT 10;
```

### NCP API 직접 호출

```python
import httpx

async def test_ncr_image():
    url = "https://contest27-klepaas-build-handle.kr.ncr.ntruss.com/v2/k-le-paas-test01/manifests/COMMIT_SHA"
    headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Headers: {resp.headers}")
```

## 문의 및 지원

롤백 기능 관련 문제가 계속되면:

1. **진단 API 결과 첨부**: `/api/v1/rollback/diagnose/OWNER/REPO`
2. **로그 파일 제공**: 전체 서버 로그 (특히 ERROR/WARNING 레벨)
3. **데이터베이스 상태**: 위 SQL 쿼리 결과
4. **에러 메시지**: 정확한 에러 메시지와 HTTP 상태 코드
