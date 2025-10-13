# K-Le-PaaS 인터랙티브 튜토리얼 구현 문서

> **배경 및 목적**: K-Le-PaaS의 1분 플로우(배포→상태 확인→롤백)를 사용자가 쉽게 경험할 수 있는 인터랙티브 튜토리얼 시스템을 구현하여 AI-First PaaS의 가치를 직접 체험할 수 있도록 합니다.

---

## 📋 개요

K-Le-PaaS의 핵심 기능을 1분 만에 체험할 수 있는 인터랙티브 튜토리얼 시스템 구현 문서입니다.

## 구현된 기능

### 1. 튜토리얼 스크립트 시스템 (`tutorial_script.py`)

#### 핵심 클래스
- **TutorialScript**: 튜토리얼 단계별 메시지와 내용을 관리
- **TutorialStateManager**: 튜토리얼 세션 상태를 관리하는 상태 머신
- **TutorialStep**: 튜토리얼 단계 열거형 (WELCOME, DEPLOY_APP, CHECK_STATUS, ROLLBACK, COMPLETE)
- **TutorialState**: 튜토리얼 상태 열거형 (IDLE, IN_PROGRESS, WAITING_USER, COMPLETED, ERROR)

#### 주요 기능
- 5단계 튜토리얼 플로우 (환영 → 배포 → 상태 확인 → 롤백 → 완료)
- 각 단계별 자연어 명령 예시 제공
- 사용자 입력 및 에러 히스토리 관리
- 세션 기반 상태 관리

### 2. REST API 엔드포인트 (`tutorial.py`)

#### API 엔드포인트
- `POST /api/v1/tutorial/start` - 튜토리얼 시작
- `GET /api/v1/tutorial/current` - 현재 튜토리얼 상태 조회
- `POST /api/v1/tutorial/next` - 다음 단계로 진행
- `POST /api/v1/tutorial/complete` - 튜토리얼 완료
- `POST /api/v1/tutorial/input` - 사용자 입력 추가
- `POST /api/v1/tutorial/error` - 에러 추가
- `DELETE /api/v1/tutorial/reset` - 튜토리얼 리셋

#### 요청/응답 형식
```json
// 튜토리얼 시작 요청
{
  "session_id": "tutorial_123"
}

// 튜토리얼 상태 응답
{
  "session_id": "tutorial_123",
  "step": "deploy_app",
  "step_index": 1,
  "total_steps": 5,
  "title": "📦 1단계: 애플리케이션 배포",
  "content": "이제 자연어로 애플리케이션을 배포해보겠습니다!",
  "action_text": "배포 실행",
  "natural_language_examples": [
    "hello-world 앱을 스테이징에 배포해줘",
    "nginx 이미지로 웹서버를 만들어줘"
  ],
  "state": "waiting_user",
  "completed_steps": ["welcome"],
  "user_inputs": [...],
  "errors": [...]
}
```

### 3. React 프론트엔드 컴포넌트

#### 주요 컴포넌트
- **TutorialInterface**: 메인 튜토리얼 인터페이스
- **TutorialStep**: 개별 튜토리얼 단계 표시
- **TutorialProgress**: 진행률 표시
- **NaturalLanguageInput**: 자연어 입력 인터페이스

#### 기술 스택
- React 18 + TypeScript
- TailwindCSS (스타일링)
- React Tour (가이드 기능)
- Axios (API 통신)
- Lucide React (아이콘)

### 4. MCP 도구 통합 (`tutorial.py`)

#### MCP 도구
- `start_tutorial` - 튜토리얼 시작
- `get_tutorial_status` - 튜토리얼 상태 조회
- `next_tutorial_step` - 다음 단계 진행
- `add_tutorial_input` - 사용자 입력 처리
- `complete_tutorial` - 튜토리얼 완료
- `reset_tutorial` - 튜토리얼 리셋
- `get_tutorial_script` - 튜토리얼 스크립트 조회

## 튜토리얼 플로우

### 1단계: 환영 (WELCOME)
- K-Le-PaaS 소개
- 1분 플로우 개요 설명
- 자연어 명령 예시 제공

### 2단계: 애플리케이션 배포 (DEPLOY_APP)
- 자연어로 애플리케이션 배포 명령
- 다양한 배포 예시 제공
- 성공/실패 피드백

### 3단계: 상태 확인 (CHECK_STATUS)
- 배포 상태 모니터링
- Pod, Service, 리소스 상태 확인
- 실시간 로그 및 이벤트 조회

### 4단계: 롤백 (ROLLBACK)
- 문제 발생 시 이전 버전으로 복구
- 원-클릭 롤백 기능 시연
- 안전한 롤백 프로세스 설명

### 5단계: 완료 (COMPLETE)
- 튜토리얼 완료 축하
- 다음 단계 안내
- 핵심 기능 요약

## 상태 관리

### 상태 머신
```
IDLE → IN_PROGRESS → WAITING_USER → COMPLETED
  ↓         ↓            ↓
ERROR ←─────┴────────────┘
```

### 상태 전환 규칙
- **IDLE**: 초기 상태
- **IN_PROGRESS**: 튜토리얼 진행 중
- **WAITING_USER**: 사용자 입력 대기
- **COMPLETED**: 튜토리얼 완료
- **ERROR**: 에러 발생

## 테스트

### 단위 테스트
- `test_tutorial_script.py`: 튜토리얼 스크립트 로직 테스트
- `test_tutorial_api.py`: API 엔드포인트 테스트

### 테스트 커버리지
- 스크립트 생성 및 메시지 조회
- 상태 관리자 기능
- API 엔드포인트 동작
- 에러 처리
- 전체 플로우 통합 테스트

## 사용법

### 백엔드 실행
```bash
cd backend-hybrid
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 프론트엔드 실행
```bash
cd frontend
npm install
npm run dev
```

### 튜토리얼 시작
1. 브라우저에서 `http://localhost:3000` 접속
2. "시작하기" 버튼 클릭
3. 자연어 명령 입력하여 단계별 진행

## API 사용 예시

### 튜토리얼 시작
```bash
curl -X POST "http://localhost:8000/api/v1/tutorial/start" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "my_tutorial"}'
```

### 사용자 입력 추가
```bash
curl -X POST "http://localhost:8000/api/v1/tutorial/input" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "my_tutorial", "user_input": "hello-world 앱을 배포해줘"}'
```

### 다음 단계 진행
```bash
curl -X POST "http://localhost:8000/api/v1/tutorial/next?session_id=my_tutorial"
```

## 확장 가능성

### 추가 가능한 기능
1. **다국어 지원**: 튜토리얼 메시지 다국어화
2. **진행률 저장**: 사용자별 튜토리얼 진행률 영구 저장
3. **커스터마이징**: 사용자별 튜토리얼 경로 커스터마이징
4. **분석**: 튜토리얼 완료율 및 사용자 행동 분석
5. **A/B 테스트**: 다양한 튜토리얼 버전 테스트

### 기술적 개선
1. **WebSocket**: 실시간 상태 업데이트
2. **Redis**: 세션 상태 영구 저장
3. **캐싱**: 튜토리얼 스크립트 캐싱
4. **로깅**: 상세한 사용자 행동 로깅

## 보안 고려사항

1. **세션 관리**: 세션 ID 검증 및 만료 처리
2. **입력 검증**: 사용자 입력 XSS 방지
3. **에러 처리**: 민감한 정보 노출 방지
4. **Rate Limiting**: API 호출 빈도 제한

## 결론

이 구현을 통해 사용자는 K-Le-PaaS의 핵심 기능을 1분 만에 체험할 수 있으며, 자연어 명령의 편리함과 AI-First PaaS의 가치를 직접 경험할 수 있습니다. 

튜토리얼은 단순한 가이드가 아닌 실제 배포, 모니터링, 롤백 과정을 포함한 완전한 워크플로우를 제공하여 사용자가 실제 운영 환경에서의 경험을 미리 체험할 수 있도록 설계되었습니다.

---

**관련 파일**:
- `app/services/tutorial_script.py` - 튜토리얼 스크립트 로직
- `app/services/tutorial.py` - REST API 엔드포인트
- `app/mcp/tools/tutorial.py` - MCP 도구 통합
- `tests/test_tutorial_script.py` - 단위 테스트
- `tests/test_tutorial_api.py` - API 테스트

