# GitHub App 설정 가이드

## 문제 해결 방법

현재 GitHub 저장소 연결 시 500 에러가 발생하는 이유는 **GitHub App이 설정되지 않았기 때문**입니다.

## 해결 단계

### 1. GitHub App 생성
1. https://github.com/settings/apps/new 에서 새 GitHub App 생성
2. App 이름: "K-Le-PaaS" (또는 원하는 이름)
3. Homepage URL: `http://localhost:3000` (프론트엔드 URL)
4. **Webhook URL**: `http://localhost:8000/api/v1/github/webhook` ⭐ **중요**
5. Permissions 설정:
   - Repository permissions: Contents (Read), Metadata (Read), Pull requests (Read)
   - Subscribe to events: Push, Pull request, Release
6. "Create GitHub App" 클릭

### 2. 환경 변수 설정
`.env` 파일에 다음 설정 추가:

```bash
# GitHub App 설정 (필수)
KLEPAAS_GITHUB_APP_ID=your_app_id_here
KLEPAAS_GITHUB_APP_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_CONTENT_HERE\n-----END PRIVATE KEY-----"
KLEPAAS_GITHUB_APP_WEBHOOK_SECRET=your_webhook_secret_here

# 백엔드 URL 설정 (웹훅 자동 설정용)
KLEPAAS_BACKEND_URL=http://localhost:8000

# 기존 설정 (호환성)
KLEPAAS_GITHUB_WEBHOOK_SECRET=your_legacy_webhook_secret_here
```

### 3. GitHub App 설치
1. 생성된 GitHub App 페이지에서 "Install App" 클릭
2. 원하는 조직/계정에 설치
3. 저장소 접근 권한 부여

### 4. 서버 재시작
환경 변수 설정 후 백엔드 서버를 재시작하세요.

## 웹훅 자동 설정

이제 GitHub 저장소를 연결하면 **웹훅이 자동으로 설정**됩니다:

1. 저장소 연결 시 자동으로 웹훅 생성
2. 웹훅 URL: `{BACKEND_URL}/api/v1/github/webhook`
3. 이벤트: `push`, `pull_request`, `release`
4. 연결 성공 시 `webhook_configured: true` 응답

## 웹훅 상태 확인

저장소의 웹훅 설정 상태를 확인할 수 있습니다:

```bash
GET /api/v1/projects/github/webhook-status/{owner}/{repo}
```

응답 예시:
```json
{
  "status": "success",
  "repository": "owner/repo",
  "webhook_url": "http://localhost:8000/api/v1/github/webhook",
  "webhooks": [
    {
      "id": 123456,
      "url": "http://localhost:8000/api/v1/github/webhook",
      "events": ["push", "pull_request", "release"],
      "active": true,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    }
  ],
  "webhook_configured": true
}
```

## 임시 해결책

GitHub App 설정이 완료될 때까지는 다음 방법을 사용할 수 있습니다:

1. **Personal Access Token 사용**: GitHub에서 Personal Access Token을 생성하여 `KLEPAAS_GITHUB_TOKEN`에 설정
2. **수동 저장소 등록**: DB에 직접 저장소 정보 입력

## 확인 방법

설정 완료 후 다음 엔드포인트로 확인:
- `GET /api/v1/github/app/installations` - 설치된 App 목록
- `GET /api/v1/github/app/install-url` - App 설치 URL
- `GET /api/v1/projects/github/webhook-status/{owner}/{repo}` - 웹훅 상태 확인

## 문제 해결

### 웹훅이 설정되지 않는 경우
1. `KLEPAAS_BACKEND_URL` 환경 변수가 올바르게 설정되었는지 확인
2. 백엔드 서버가 실행 중인지 확인
3. GitHub App 권한에 "Webhooks" 권한이 있는지 확인

### 웹훅은 설정되었지만 이벤트가 오지 않는 경우
1. GitHub 저장소 설정에서 웹훅이 활성화되어 있는지 확인
2. 웹훅 이벤트 로그 확인: GitHub 저장소 → Settings → Webhooks → Recent Deliveries
3. 백엔드 로그에서 웹훅 수신 여부 확인
