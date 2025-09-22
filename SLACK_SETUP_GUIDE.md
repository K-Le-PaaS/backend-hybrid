# Slack 앱 설정 가이드 (테스트용)

## 1. Slack 앱 생성

1. [Slack API 페이지](https://api.slack.com/apps)에 접속
2. "Create New App" 클릭
3. "From scratch" 선택
4. 앱 이름: `K-Le-PaaS Test`
5. 워크스페이스 선택 후 "Create App" 클릭

## 2. OAuth & Permissions 설정

1. 왼쪽 메뉴에서 "OAuth & Permissions" 클릭
2. "Scopes" 섹션에서 "Bot Token Scopes"에 다음 권한 추가:
   - `chat:write` - 메시지 전송
   - `channels:read` - 채널 목록 조회
   - `users:read` - 사용자 정보 조회
   - `team:read` - 팀 정보 조회

3. "OAuth Tokens & Redirect URLs" 섹션에서:
   - Redirect URLs에 `http://localhost:8000/slack/callback` 추가
   - "Save URLs" 클릭

## 3. 환경 변수 설정

`.env` 파일에 다음 추가:

```bash
# Slack OAuth 2.0
SLACK_CLIENT_ID=your_client_id_here
SLACK_CLIENT_SECRET=your_client_secret_here
SLACK_REDIRECT_URI=http://localhost:8000/slack/callback

# 기존 Slack 설정 (선택사항)
SLACK_WEBHOOK_URL=your_webhook_url_here
SLACK_ALERT_CHANNEL_DEFAULT=#general
```

## 4. 앱 설치

1. "OAuth & Permissions" 페이지에서 "Install to Workspace" 클릭
2. 권한 승인 후 "Allow" 클릭
3. Bot User OAuth Token 복사 (xoxb-로 시작)

## 5. 테스트 실행

```bash
# 서버 실행
python -m uvicorn app.main:app --reload --port 8000

# 브라우저에서 접속
http://localhost:8000/slack/auth/url?redirect_uri=http://localhost:8000/slack/callback
```

## 6. API 테스트

### 인증 URL 생성
```bash
curl "http://localhost:8000/api/v1/slack/auth/url?redirect_uri=http://localhost:8000/slack/callback"
```

### 채널 목록 조회 (토큰 필요)
```bash
curl "http://localhost:8000/api/v1/slack/channels?access_token=YOUR_BOT_TOKEN"
```

### 테스트 메시지 전송
```bash
curl "http://localhost:8000/api/v1/slack/test?access_token=YOUR_BOT_TOKEN&channel=%23general"
```
