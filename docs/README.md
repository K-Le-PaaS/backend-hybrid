# K-Le-PaaS Backend Hybrid 문서

> K-Le-PaaS Backend Hybrid 백엔드는 **GitHub·NCP·Kubernetes·Slack·NLP를 하나로 묶어 배포·롤백·모니터링·자연어 명령 실행을 자동화하는 운영 레이어**입니다.  
> 이 `docs/` 디렉터리는 그 백엔드 코드가 **어떻게 동작하는지(아키텍처)** 와 **어떤 문제를 어떻게 해결했는지(트러블슈팅)** 를 분리해서 설명합니다.

---

## 📂 문서 구조

```
docs/
├── README.md                          # 이 파일
├── architecture/                      # 아키텍처 및 설계 문서 (코드가 하는 일 중심)
│   ├── BACKEND_ARCHITECTURE.md       # 전체 백엔드 아키텍처 ⭐
│   ├── ENVIRONMENT_AND_CONFIG.md     # 환경 설정 통합 가이드 ⭐
│   ├── nlp/                          # NLP 아키텍처/구현/퀵스타트
│   │   ├── execution.md              # NLP 실행 아키텍처
│   │   ├── implementation.md         # NLP 명령어 구현 가이드
│   │   ├── quick_start.md            # NLP 퀵 스타트
│   │   └── DEPLOY_ROLLBACK.md        # NLP 배포 및 롤백 기능 상세 분석
│   ├── tutorial/                     # 튜토리얼 구현 아키텍처
│   ├── rollback/                     # 롤백 아키텍처 및 구현 정리
│   ├── ncp/                          # NCP 파이프라인/이미지 설계 및 구현
│   │   ├── GITHUB_TO_NCP_PIPELINE.md # GitHub → NCP 파이프라인 전체 흐름
│   │   └── MANIFEST_AUTO_GENERATION.md # Manifest 자동 생성 기능
│   └── integrations/                 # 외부 서비스 연동 아키텍처
│       └── SLACK_SETUP.md            # Slack 앱 설정 가이드
└── troubleshooting/                   # 문제 해결 및 장애 대응 정리
    ├── ROLLBACK_ERROR_ANALYSIS.md    # 롤백 에러 분석
    ├── ROLLBACK_TROUBLESHOOTING.md   # 롤백 장애 처리 및 해결
    ├── ALERTING_AND_REPORTS.md       # 알림/모니터링 경로 점검 및 개선
    └── ncp/                          # NCP 트러블슈팅 상세 문서
        ├── NCP_IMAGE_NAME_FIX.md    # 이미지 이름 고유성 수정
        ├── NCP_SCENARIO_DEBUG.md     # 시나리오 생성 디버깅
        └── NCP_SCENARIO_MANUAL_CREATION.md # 시나리오 수동 생성 가이드
```

---

## 🚀 이 백엔드 코드가 하는 일 (한눈에 요약)

- **클라우드 운영 자동화 허브**  
  - GitHub Webhook, NCP SourcePipeline, Kubernetes API, Slack, Prometheus 를 FastAPI 백엔드 한 곳으로 모읍니다.
- **자연어 기반 운영 계층**  
  - Gemini 기반 NLP 로 “staging 3개로 스케일링”, “지난 배포로 롤백” 같은 한국어 명령을 구조화해 실제 K8s/NCP 작업으로 변환합니다.
- **배포/롤백·이력·알림 일원화**  
  - 배포 히스토리, 롤백 기록, 인프라 헬스, Slack 알림을 모두 DB/모니터링과 연결해 “언제 무엇이 어떻게 배포됐는지”를 추적 가능하게 합니다.

아래 문서들은 이 역할을 **아키텍처(architecture/**)와 트러블슈팅(troubleshooting/**)** 관점으로 나눠 설명합니다.

---

## 🚀 빠른 시작

### 처음 시작하는 경우

1. **시스템 아키텍처 이해**: [architecture/BACKEND_ARCHITECTURE.md](./architecture/BACKEND_ARCHITECTURE.md) ⭐ 필독
   - 전체 시스템 구조 및 컴포넌트
   - 디렉토리 구조 및 데이터 흐름
   - 핵심 기술 스택 및 설계 패턴

2. **환경 설정**: [architecture/ENVIRONMENT_AND_CONFIG.md](./architecture/ENVIRONMENT_AND_CONFIG.md) ⭐ 필독
   - 로컬 개발 환경 설정
   - Kubernetes 프로덕션 배포
   - 환경변수 우선순위 및 설정 방법

3. **NLP 시스템 이해**:
   - [NLP 실행 아키텍처](architecture/nlp/execution.md) ⭐ 상세 아키텍처
   - [NLP 퀵 스타트 가이드](architecture/nlp/quick_start.md) ⭐ 팀원 가이드
   - [NLP 명령어 구현 가이드](architecture/nlp/implementation.md) ⭐ 개발자 가이드
   - [NLP 배포 및 롤백 기능](architecture/nlp/DEPLOY_ROLLBACK.md) ⭐ NLP 배포/롤백 상세 분석

4. **Slack 연동**: [architecture/integrations/SLACK_SETUP.md](./architecture/integrations/SLACK_SETUP.md)
   - Slack 앱 생성 및 OAuth 설정
   - 배포 알림 설정

---

## 📖 주요 문서 설명

### 🌟 ENVIRONMENT_AND_CONFIG.md
**모든 환경 설정을 통합한 필독 문서**

- 위치: [architecture/ENVIRONMENT_AND_CONFIG.md](./architecture/ENVIRONMENT_AND_CONFIG.md)

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

### 🏗️ 아키텍처

#### BACKEND_ARCHITECTURE.md ⭐
**전체 백엔드 시스템 아키텍처 문서**

- 시스템 개요 및 기술 스택
- 디렉토리 구조 (95개 Python 파일)
- 핵심 컴포넌트 (FastAPI, NLP, K8s, MCP, CI/CD)
- 데이터 흐름 및 요청 처리
- 보안, 모니터링, 확장성

#### NLP 시스템
**자연어 명령 처리 아키텍처**

- [NLP 실행 아키텍처](architecture/nlp/execution.md) - 전체 시스템 흐름
- [NLP 구현 가이드](architecture/nlp/implementation.md) - 명령어 추가 방법 (14개 명령어)
- [NLP 퀵 스타트](architecture/nlp/quick_start.md) - 빠른 시작 가이드
- [NLP 배포 및 롤백 기능](architecture/nlp/DEPLOY_ROLLBACK.md) - NLP를 통한 배포/롤백/스케일링 상세 분석

#### 튜토리얼
**1분 플로우 인터랙티브 튜토리얼**

- [architecture/tutorial/implementation.md](architecture/tutorial/implementation.md)
- 배포 → 상태 확인 → 롤백 플로우
- React 프론트엔드 컴포넌트
- REST API 및 백엔드 연동

#### 롤백 아키텍처
**롤백 기능 설계 및 구현**

- [architecture/rollback/ROLLBACK_ARCHITECTURE.md](architecture/rollback/ROLLBACK_ARCHITECTURE.md) - 롤백 기능 전체 구조와 컴포넌트 역할
- [architecture/rollback/ROLLBACK_FEATURE_IMPLEMENTATION.md](architecture/rollback/ROLLBACK_FEATURE_IMPLEMENTATION.md) - 롤백 기능 코드 구현 상세

---

### ☁️ NCP (Naver Cloud Platform)

#### NCP 아키텍처/설계
- [architecture/ncp/GITHUB_TO_NCP_PIPELINE.md](./architecture/ncp/GITHUB_TO_NCP_PIPELINE.md)  
  - GitHub 레포지터리 등록부터 NCP 빌드/배포 파이프라인 전체 흐름을 코드 레벨에서 상세하게 설명
  - SourceCommit/SourceBuild/Container Registry/SourceDeploy/NKS 와 백엔드 코드가 어떻게 연결되는지 설명
- [architecture/ncp/MANIFEST_AUTO_GENERATION.md](./architecture/ncp/MANIFEST_AUTO_GENERATION.md)  
  - Kubernetes Deployment/Service/Ingress Manifest 자동 생성 기능 설계 및 구현

#### NCP 트러블슈팅
- [troubleshooting/ncp/NCP_IMAGE_NAME_FIX.md](./troubleshooting/ncp/NCP_IMAGE_NAME_FIX.md)  
  - 타임스탬프 기반 고유 이미지 이름 생성, NCR 규격(-, _ 제거) 준수, 실제 구현 흐름 정리
- [troubleshooting/ncp/NCP_SCENARIO_DEBUG.md](./troubleshooting/ncp/NCP_SCENARIO_DEBUG.md)  
  - SourceDeploy 시나리오 자동 생성 시 에러 330900 "unknown" 분석, 시도한 페이로드, 우회 전략
- [troubleshooting/ncp/NCP_SCENARIO_MANUAL_CREATION.md](./troubleshooting/ncp/NCP_SCENARIO_MANUAL_CREATION.md)  
  - NCP Console에서 시나리오를 수동으로 만들고, 브라우저 Network 탭으로 실제 API 페이로드를 캡처하는 절차

---

### 🔗 외부 서비스 연동

#### SLACK_SETUP.md
**Slack 앱 설정 완벽 가이드**

- 위치: [architecture/integrations/SLACK_SETUP.md](./architecture/integrations/SLACK_SETUP.md)
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

### 시스템 아키텍처
→ [architecture/BACKEND_ARCHITECTURE.md](./architecture/BACKEND_ARCHITECTURE.md) ⭐ 전체 시스템

### 환경 설정 관련
→ [architecture/ENVIRONMENT_AND_CONFIG.md](./architecture/ENVIRONMENT_AND_CONFIG.md)

### NLP/AI 관련
→ [architecture/nlp/implementation.md](./architecture/nlp/implementation.md) - 명령어 구현
→ [architecture/nlp/execution.md](./architecture/nlp/execution.md) - 실행 아키텍처
→ [architecture/nlp/quick_start.md](./architecture/nlp/quick_start.md) - 빠른 시작
→ [architecture/nlp/DEPLOY_ROLLBACK.md](./architecture/nlp/DEPLOY_ROLLBACK.md) - NLP 배포/롤백 상세 분석

### NCP 관련
→ [architecture/ncp/GITHUB_TO_NCP_PIPELINE.md](./architecture/ncp/GITHUB_TO_NCP_PIPELINE.md) - 파이프라인 전체 흐름
→ [architecture/ncp/MANIFEST_AUTO_GENERATION.md](./architecture/ncp/MANIFEST_AUTO_GENERATION.md) - Manifest 자동 생성
→ [troubleshooting/ncp/](./troubleshooting/ncp/) 폴더 - NCP 트러블슈팅 문서

### 장애/트러블슈팅 관련

#### 롤백 관련 트러블슈팅
- [troubleshooting/ROLLBACK_ERROR_ANALYSIS.md](./troubleshooting/ROLLBACK_ERROR_ANALYSIS.md) - 롤백 기능에서 발생한 주요 에러 유형, 원인 분석, 재현 조건, 수정 방향
- [troubleshooting/ROLLBACK_TROUBLESHOOTING.md](./troubleshooting/ROLLBACK_TROUBLESHOOTING.md) - 실제 장애 상황에서 어떤 순서로 진단하고, 어떤 패치를 적용해 문제를 해결했는지 단계별 설명

#### 알림·모니터링 관련 트러블슈팅
- [troubleshooting/ALERTING_AND_REPORTS.md](./troubleshooting/ALERTING_AND_REPORTS.md) - Prometheus/Alertmanager/Slack 알림 경로와 관련된 문제 정리 및 대시보드/알림 구성 개선

#### NCP 관련 트러블슈팅
- [troubleshooting/ncp/NCP_IMAGE_NAME_FIX.md](./troubleshooting/ncp/NCP_IMAGE_NAME_FIX.md) - 타임스탬프 기반 고유 이미지 이름 생성, NCR 규격 준수
- [troubleshooting/ncp/NCP_SCENARIO_DEBUG.md](./troubleshooting/ncp/NCP_SCENARIO_DEBUG.md) - SourceDeploy 시나리오 자동 생성 시 에러 330900 "unknown" 분석
- [troubleshooting/ncp/NCP_SCENARIO_MANUAL_CREATION.md](./troubleshooting/ncp/NCP_SCENARIO_MANUAL_CREATION.md) - NCP Console에서 수동으로 시나리오 생성 및 API 페이로드 캡처 절차

### Slack 연동
→ [architecture/integrations/SLACK_SETUP.md](./architecture/integrations/SLACK_SETUP.md)

### 튜토리얼 구현
→ [architecture/tutorial/implementation.md](./architecture/tutorial/implementation.md)

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

