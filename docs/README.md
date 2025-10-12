# K-Le-PaaS Backend Hybrid 문서

> K-Le-PaaS Backend Hybrid 프로젝트의 모든 기술 문서를 체계적으로 정리한 디렉토리입니다.

---

## 📂 문서 구조

```
docs/
├── README.md                          # 이 파일
├── ENVIRONMENT_AND_CONFIG.md          # 환경 설정 통합 가이드 ⭐
├── architecture/                      # 아키텍처 및 설계 문서
│   ├── NLP_ARCHITECTURE_REFACTOR.md  # NLP 아키텍처 리팩토링
│   └── TUTORIAL_IMPLEMENTATION.md     # 인터랙티브 튜토리얼 구현
├── ncp/                               # NCP(Naver Cloud Platform) 관련
│   ├── NCP_IMAGE_NAME_FIX.md         # 이미지 이름 고유성 수정
│   ├── NCP_SCENARIO_DEBUG.md         # 시나리오 생성 디버깅
│   └── NCP_SCENARIO_MANUAL_CREATION.md # 시나리오 수동 생성 가이드
├── integrations/                      # 외부 서비스 연동
│   └── SLACK_SETUP.md                # Slack 앱 설정 가이드
└── troubleshooting/                   # 문제 해결 (추후 추가)
```

---

## 🚀 빠른 시작

### 처음 시작하는 경우

1. **환경 설정**: [ENVIRONMENT_AND_CONFIG.md](./ENVIRONMENT_AND_CONFIG.md) ⭐ 필독
   - 로컬 개발 환경 설정
   - Kubernetes 프로덕션 배포
   - 환경변수 우선순위 및 설정 방법

2. **NLP 시스템 이해**: 
   - [NLP 실행 아키텍처](architecture/NLP_EXECUTION_ARCHITECTURE.md) ⭐ 상세 아키텍처
   - [NLP 퀵 스타트 가이드](architecture/NLP_QUICK_START_GUIDE.md) ⭐ 팀원 가이드
   - [NLP 명령어 구현 가이드](architecture/NLP_COMMAND_IMPLEMENTATION_GUIDE.md) ⭐ 개발자 가이드

3. **Slack 연동**: [integrations/SLACK_SETUP.md](./integrations/SLACK_SETUP.md)
   - Slack 앱 생성 및 OAuth 설정
   - 배포 알림 설정

---

## 📖 주요 문서 설명

### 🌟 ENVIRONMENT_AND_CONFIG.md
**모든 환경 설정을 통합한 필독 문서**

다음 내용을 포함합니다:
- 환경변수 우선순위 (Kubernetes Secret → 시스템 환경변수 → .env → 기본값)
- 로컬 개발 환경 설정 (`.env` 파일)
- Kubernetes 프로덕션 환경 (Secret, Deployment, RBAC)
- Kubernetes Config 설정 (kubeconfig 관리)
- 보안 및 주의사항
- 테스트 및 검증 방법

**이전 문서 통합**:
- `ENVIRONMENT_SETUP.md`
- `ENV_CONFIG_SUMMARY.md`
- `KUBERNETES_CONFIG.md`

---

### 🏗️ Architecture (아키텍처)

#### NLP_ARCHITECTURE_REFACTOR.md
**NLP 시스템의 단순화 과정**

- 복잡한 다중 모델 처리 시스템 제거
- Gemini API 직접 호출로 전환
- 성능 개선 및 유지보수성 향상

#### TUTORIAL_IMPLEMENTATION.md
**1분 플로우 인터랙티브 튜토리얼**

- 배포 → 상태 확인 → 롤백 플로우
- React 프론트엔드 컴포넌트
- REST API 및 MCP 도구 통합

---

### ☁️ NCP (Naver Cloud Platform)

#### NCP_IMAGE_NAME_FIX.md
**이미지 이름 충돌 방지**

- 타임스탬프 기반 고유 이미지 이름 생성
- NCR 규격 준수 (-, _ 제거)
- 프로젝트-빌드-배포 전체 일관성 유지

#### NCP_SCENARIO_DEBUG.md
**시나리오 생성 디버깅**

- API 에러 330900 "unknown" 문제
- 시도한 페이로드 및 해결 방법
- NCP 지원팀 문의 가이드

#### NCP_SCENARIO_MANUAL_CREATION.md
**시나리오 수동 생성 가이드**

- NCP Console에서 수동 생성 단계
- API 페이로드 캡처 방법
- 자동화 실패 시 대안

---

### 🔗 Integrations (외부 서비스 연동)

#### SLACK_SETUP.md
**Slack 앱 설정 완벽 가이드**

- Slack 앱 생성 및 권한 설정
- OAuth 2.0 플로우 구현
- 배포 알림 및 이벤트 구독
- 슬래시 명령어 설정

---

## 🎯 문서 작성 원칙

모든 문서는 다음 원칙을 따릅니다:

1. **배경·의도·목적 명시**: 각 문서의 첫 부분에 배경과 목적을 명확히 설명
2. **파일 경로 포함**: 관련 파일의 정확한 경로 명시
3. **상세한 주석**: 비즈니스 로직, 예외 처리 목적까지 설명
4. **실행 가능한 예제**: 복사-붙여넣기로 바로 실행 가능한 코드/명령어
5. **체계적 구조**: 목차, 섹션, 체크리스트로 명확한 구조

---

## 🔍 문서 찾기

### 환경 설정 관련
→ [ENVIRONMENT_AND_CONFIG.md](./ENVIRONMENT_AND_CONFIG.md)

### NLP/AI 관련
→ [architecture/NLP_ARCHITECTURE_REFACTOR.md](./architecture/NLP_ARCHITECTURE_REFACTOR.md)

### NCP 관련 문제
→ [ncp/](./ncp/) 폴더

### Slack 연동
→ [integrations/SLACK_SETUP.md](./integrations/SLACK_SETUP.md)

### 튜토리얼 구현
→ [architecture/TUTORIAL_IMPLEMENTATION.md](./architecture/TUTORIAL_IMPLEMENTATION.md)

---

## 📝 문서 업데이트

문서를 업데이트할 때:

1. **배경 및 목적** 섹션에 변경 이유 추가
2. **관련 파일** 경로 확인 및 업데이트
3. **체크리스트** 항목 검토 및 업데이트
4. **예제 코드** 실제 동작 검증

---

## 🤝 기여 가이드

1. 새로운 기능 구현 시 관련 문서 업데이트
2. 복잡한 설정이나 문제 해결은 별도 문서로 작성
3. 문서는 한글로 작성 (코드/명령어는 영문)
4. 실행 가능한 예제 코드 포함

---

## 📚 참고 자료

- **프로젝트 README**: [../README.md](../README.md)
- **기여 가이드**: [../CONTRIBUTING.md](../CONTRIBUTING.md)
- **코드 소유권**: [../CODEOWNERS](../CODEOWNERS)

---

**문서 정리 날짜**: 2025-01-11
**담당자**: Backend Team

