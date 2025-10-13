# Slack 앱 설정 가이드

> **배경 및 목적**: K-Le-PaaS Backend와 Slack을 연동하여 배포 알림, 모니터링 알림, 사용자 인터랙션을 Slack에서 처리할 수 있도록 Slack 앱을 설정하는 가이드입니다.

---

## 📋 개요

K-Le-PaaS Backend에서 Slack OAuth 2.0 통합을 설정하는 전체 과정을 다룹니다.

## 1. Slack 앱 생성

1. [Slack API 페이지](https://api.slack.com/apps)에 접속
2. "Create New App" 클릭
3. "From scratch" 선택
4. 앱 이름: `K-Le-PaaS` (또는 원하는 이름)
5. 워크스페이스 선택 후 "Create App" 클릭

## 2. OAuth & Permissions 설정

### Bot Token Scopes 추가

1. 왼쪽 메뉴에서 "OAuth & Permissions" 클릭
2. "Scopes" 섹션에서 "Bot Token Scopes"에 다음 권한 추가:
   - `chat:write` - 메시지 전송
   - `channels:read` - 채널 목록 조회
   - `users:read` - 사용자 정보 조회
   - `team:read` - 팀 정보 조회
   - `app_mentions:read` - 앱 멘션 읽기 (선택사항)
   - `commands` - 슬래시 명령어 (선택사항)

### Redirect URLs 설정

1. "OAuth Tokens & Redirect URLs" 섹션에서:
   
   **로컬 개발 시**:
   ```
   http://localhost:8000/slack/callback
   ```
   
   **프로덕션 배포 시**:
   ```
   https://your-domain.com/slack/callback
   ```

2. "Save URLs" 클릭

## 3. 환경 변수 설정

### 로컬 개발 환경 (`.env` 파일)

```bash
# ==========================================
# Slack OAuth 2.0
# ==========================================

# OAuth 2.0 Credentials (Slack 앱 페이지에서 확인)
SLACK_CLIENT_ID=your_client_id_here
SLACK_CLIENT_SECRET=your_client_secret_here

# Redirect URI (OAuth 콜백 URL)
SLACK_REDIRECT_URI=http://localhost:8000/slack/callback

# ==========================================
# 기존 Slack 설정 (선택사항 - Webhook 사용 시)
# ==========================================
SLACK_WEBHOOK_URL=your_webhook_url_here
SLACK_ALERT_CHANNEL_DEFAULT=#general
```

### Kubernetes Secret (프로덕션)

```bash
# env 파일에 추가
cat >> /home/k88s/env_file/env << 'EOF'

# Slack OAuth 2.0
SLACK_CLIENT_ID=실제_클라이언트_ID
SLACK_CLIENT_SECRET=실제_클라이언트_시크릿
SLACK_REDIRECT_URI=https://your-domain.com/slack/callback

# 선택사항
SLACK_WEBHOOK_URL=실제_웹훅_URL
SLACK_ALERT_CHANNEL_DEFAULT=#alerts
EOF

# Secret 재생성
kubectl delete secret backend-env-secret -n klepaas --ignore-not-found=true
kubectl create secret generic backend-env-secret \
  --from-env-file=/home/k88s/env_file/env \
  -n klepaas
```

## 4. 앱 설치

1. "OAuth & Permissions" 페이지에서 "Install to Workspace" 클릭
2. 권한 승인 후 "Allow" 클릭
3. Bot User OAuth Token 복사 (xoxb-로 시작)
   - 이 토큰은 테스트용으로 사용할 수 있습니다
   - 실제 운영에서는 OAuth 플로우를 통해 사용자별 토큰을 받습니다

## 5. 서버 실행 및 테스트

### 백엔드 서버 실행

```bash
# 가상환경 활성화
source venv/bin/activate

# 서버 실행
uvicorn app.main:app --reload --port 8000
```

### OAuth 플로우 테스트

#### 1. 인증 URL 생성
```bash
curl "http://localhost:8000/api/v1/slack/auth/url?redirect_uri=http://localhost:8000/slack/callback"
```

응답:
```json
{
  "auth_url": "https://slack.com/oauth/v2/authorize?client_id=...&scope=...&redirect_uri=..."
}
```

#### 2. 브라우저에서 인증
1. 위에서 받은 `auth_url`을 브라우저에서 열기
2. Slack 워크스페이스 선택
3. 권한 승인
4. 자동으로 콜백 URL로 리다이렉트됨
5. Access Token 받음

#### 3. 채널 목록 조회
```bash
curl "http://localhost:8000/api/v1/slack/channels?access_token=YOUR_BOT_TOKEN"
```

#### 4. 테스트 메시지 전송
```bash
curl "http://localhost:8000/api/v1/slack/test?access_token=YOUR_BOT_TOKEN&channel=%23general"
```

## 6. 사용 가능한 API 엔드포인트

### 인증 관련

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/slack/auth/url` | GET | OAuth 인증 URL 생성 |
| `/slack/callback` | GET | OAuth 콜백 처리 |

### Slack 작업

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/slack/channels` | GET | 채널 목록 조회 |
| `/api/v1/slack/test` | GET | 테스트 메시지 전송 |
| `/api/v1/slack/notify` | POST | 배포 알림 전송 |

## 7. 고급 기능 설정 (선택사항)

### 이벤트 구독 (Event Subscriptions)

1. Slack 앱 페이지 > "Event Subscriptions" 클릭
2. "Enable Events" 활성화
3. Request URL 입력:
   ```
   https://your-domain.com/slack/events
   ```
4. Subscribe to bot events:
   - `app_mention` - 앱 멘션 시
   - `message.channels` - 채널 메시지

### 슬래시 명령어 (Slash Commands)

1. Slack 앱 페이지 > "Slash Commands" 클릭
2. "Create New Command" 클릭
3. 명령어 설정:
   ```
   Command: /klepaas
   Request URL: https://your-domain.com/slack/commands
   Short Description: K-Le-PaaS 명령어 실행
   Usage Hint: [deploy|status|logs] [app-name]
   ```

## 8. 보안 고려사항

### Client Secret 보호
- ✅ **DO**: 환경변수로 관리
- ✅ **DO**: Kubernetes Secret 사용 (프로덕션)
- ❌ **DON'T**: 코드에 하드코딩
- ❌ **DON'T**: Git에 커밋

### Token 관리
- Bot Token은 서버에서만 사용
- User Token은 안전하게 암호화하여 저장
- Token 유효성 주기적으로 검증
- Token 만료 시 재인증 플로우 제공

### Webhook URL 보호
- Webhook URL은 민감 정보
- 환경변수로 관리
- Git에 커밋하지 않기

## 9. 문제 해결

### "invalid_client_id" 오류
```
원인: SLACK_CLIENT_ID가 잘못되었거나 설정되지 않음
해결: Slack 앱 페이지에서 Client ID 확인 후 .env 파일 업데이트
```

### "invalid_redirect_uri" 오류
```
원인: Redirect URI가 Slack 앱 설정과 일치하지 않음
해결: Slack 앱 페이지의 "OAuth & Permissions"에서 Redirect URI 확인
```

### "not_authed" 또는 "invalid_auth" 오류
```
원인: Access Token이 유효하지 않거나 만료됨
해결: OAuth 플로우를 다시 진행하여 새 토큰 발급
```

### Webhook 메시지 전송 실패
```
원인: Webhook URL이 잘못되었거나 채널이 존재하지 않음
해결: Slack 워크스페이스에서 Incoming Webhook 재설정
```

## 10. 배포 알림 예시

### 배포 성공 알림
```python
# app/services/slack_notification_service.py 사용
await slack_service.send_deployment_notification(
    app_name="my-app",
    status="success",
    version="v1.2.3",
    environment="production"
)
```

Slack 메시지:
```
🚀 배포 성공!
앱: my-app
버전: v1.2.3
환경: production
시간: 2025-01-04 15:30:00 KST
```

### 배포 실패 알림
```python
await slack_service.send_deployment_notification(
    app_name="my-app",
    status="failed",
    error="Image pull error",
    environment="staging"
)
```

Slack 메시지:
```
❌ 배포 실패
앱: my-app
환경: staging
에러: Image pull error
시간: 2025-01-04 15:30:00 KST
```

## 11. 체크리스트

### 초기 설정
- [ ] Slack 앱 생성
- [ ] Bot Token Scopes 추가
- [ ] Redirect URLs 설정
- [ ] Client ID 및 Secret 환경변수 설정
- [ ] 앱을 워크스페이스에 설치

### 테스트
- [ ] 인증 URL 생성 확인
- [ ] OAuth 콜백 동작 확인
- [ ] 채널 목록 조회 확인
- [ ] 테스트 메시지 전송 확인

### 프로덕션 배포
- [ ] 프로덕션 Redirect URI 추가
- [ ] Kubernetes Secret에 설정 추가
- [ ] HTTPS 엔드포인트 설정
- [ ] 이벤트 구독 설정 (선택사항)
- [ ] 슬래시 명령어 설정 (선택사항)

---

**관련 파일**:
- `app/services/slack_oauth.py` - OAuth 2.0 구현
- `app/services/slack_notification_service.py` - 알림 서비스
- `app/api/v1/slack.py` - Slack API 엔드포인트
- `app/core/config.py` - 환경 설정

**관련 문서**:
- [환경 설정 가이드](../ENVIRONMENT_AND_CONFIG.md)
- [Slack API 공식 문서](https://api.slack.com/docs)

