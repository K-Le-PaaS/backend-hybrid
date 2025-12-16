## K-Le-PaaS Backend Hybrid

FastAPI 기반의 **클라우드 운영 자동화 백엔드**입니다. `/api/v1` 아래에 REST API를 제공하고, Kubernetes·GitHub·Slack·NCP와 연동하여 **배포·롤백·모니터링·자연어 명령 실행**을 하나의 시스템으로 묶어줍니다.

---

## 이 프로젝트가 해결하려는 문제

- **문제 1 – 파편화된 운영 도구**
  - GitHub Actions, NCP 콘솔, kubectl, Slack 알림이 제각각이라 한 번의 배포/롤백 작업에 여러 툴을 오가야 합니다.
- **문제 2 – 사람이 직접 기억하는 배포/롤백 절차**
  - “어느 브랜치에서 어떤 이미지를 빌드해서, 어느 클러스터에 몇 개로 배포했는지”를 사람이 기억하고 수동으로 조작해야 합니다.
- **문제 3 – 운영 진입 장벽**
  - kubectl·YAML·CI 파이프라인을 모두 이해해야 배포/롤백을 할 수 있어, 신규 팀원이나 비(非)플랫폼 엔지니어에게 진입장벽이 높습니다.

K-Le-PaaS Backend Hybrid는 이 문제들을 다음 방식으로 풀고자 합니다.

- **하나의 백엔드로 운영 흐름 통합**: GitHub Webhook, Kubernetes API, NCP, Slack을 단일 FastAPI 백엔드로 묶어, “HTTP API + 자연어 명령”만 알면 운영이 가능하게 만듭니다.
- **자연어 기반 안전 실행**: 사용자는 한국어로 “staging에 3개로 스케일링해줘”, “이전 버전으로 롤백해줘”와 같이 말하고, 백엔드는 Gemini 기반 NLP + 명령 플래너를 통해 실제 K8s/NCP 작업을 안전하게 실행합니다.
- **이력·헬스·알림 일원화**: 배포/롤백·명령·헬스 상태와 Slack 알림을 한 곳에서 관리해, “언제 무엇이 어떻게 배포되었는지”를 추적 가능하게 합니다.

---

## 프로젝트의 의도와 지향점

- **운영 팀을 위한 “하나의 관문(Gateway)”**
  - 운영자가 이 백엔드만 바라보고 **배포 → 모니터링 → 롤백 → 알림**까지 한 흐름으로 볼 수 있게 만드는 것이 1차 목표입니다.
- **“명령어 중심”이 아닌 “문맥 중심” 운영**
  - 단순 명령어 매핑이 아니라, NLP·대화형 인터랙션을 통해 사용자의 문맥(현재 보고 있는 GitHub 리포지토리, 직전 명령 등)을 이해하고 안전장치(확인, 비용 추정)를 둡니다.
- **플랫폼·DevOps 팀의 반복 작업을 줄이는 도구**
  - 새로운 서비스/리포지토리가 늘어나도, 동일한 API와 자연어 인터페이스만 제공하면 운영 패턴을 재사용할 수 있도록 설계되어 있습니다.

이 백엔드는 **“클라우드 운영 자동화 레이어”** 로서, 프론트엔드·AI 에이전트·챗봇이 위에 올라타 사용할 수 있는 안정적인 기반을 제공합니다.

---

## 시스템 아키텍처 개요

> 아래 다이어그램은 전체 플랫폼 관점의 아키텍처입니다.
> 'screenshots/architecture-overview.png'

```text
사용자 / 개발자
   ↓
웹 프론트엔드 (TypeScript) · Slack · GitHub
   ↓
Cloudflare → Nginx → WireGuard
   ↓
FastAPI 백엔드 (K-Le-PaaS Backend Hybrid)
   ├─ PostgreSQL (상태·이력 데이터)
   ├─ Redis (세션·대화 상태)
   ├─ Gemini (자연어 해석)
   ├─ Prometheus (메트릭 수집)
   └─ Kubernetes / NCP SourcePipeline (배포·롤백)
```

아키텍처는 크게 세 레이어로 나뉩니다.

- **사용자·프론트 레이어**
  - 사용자는 브라우저(React/TypeScript 프론트엔드), Slack, GitHub UI를 통해 시스템과 상호작용합니다.
  - 인증은 Google/GitHub OAuth를 활용하고, Slack 앱을 통해 배포/알림 채널과 연결합니다.
- **애플리케이션 백엔드 레이어 (이 리포지토리)**
  - FastAPI 앱이 모든 REST API와 WebSocket 엔드포인트를 제공합니다.
  - Redis는 대화형 NLP 세션과 단기 상태를, PostgreSQL은 배포·명령·감사 로그 등 영속 데이터를 저장합니다.
  - Gemini는 자연어 명령을 구조화된 의도/엔티티로 해석하고, `services.*` 계층이 이를 실제 Kubernetes/NCP 작업으로 변환합니다.
  - Prometheus는 FastAPI 및 인프라 헬스 정보를 수집하고, Grafana(별도 구성)에서 시각화합니다.
- **인프라·배포 레이어**
  - Kubernetes 클러스터와 NCP SourcePipeline(SourceCommit → SourceBuild → Container Registry → SourceDeploy → Ncloud Kubernetes Service)이 애플리케이션 이미지를 빌드·배포합니다.
  - GitHub push/relase 이벤트는 `/api/v1/cicd/webhook` 으로 전달되어, 이미지 태그 관리·배포 히스토리 기록·Slack 알림을 트리거합니다.

이 아키텍처 위에서 K-Le-PaaS Backend Hybrid는 **“프론트/Slack/CI ↔ 인프라(K8s·NCP)”** 사이를 중개하는 중심 허브 역할을 합니다.

### 주요 시나리오별 흐름

- **1) 개발자 → GitHub → NCP/Kubernetes 배포**
  - 개발자가 GitHub에 코드를 푸시하면 CI(예: GitHub Actions)가 이미지를 빌드해 컨테이너 레지스트리에 푸시합니다.
  - 동시에 서명된 Webhook 이 `/api/v1/cicd/webhook` 으로 전달됩니다.
  - FastAPI 백엔드는 이벤트 타입(push/release)을 해석해:
    - NCP SourcePipeline(SourceCommit → SourceBuild → SourceDeploy → Ncloud Kubernetes Service)을 호출하거나,
    - Helm 값/매니페스트를 업데이트하여 Kubernetes 클러스터로 배포를 트리거합니다.
  - 배포 결과는 PostgreSQL `deployment_history` 에 기록되고, Slack 알림으로 요약이 전달됩니다.

- **2) 사용자/운영자 → 웹 UI·Slack → 자연어 명령 기반 운영**
  - 사용자는 웹 대시보드(프론트엔드 TypeScript) 또는 Slack 에서 한국어 명령을 보냅니다.
  - 요청은 FastAPI의 `/api/v1/nlp/*` 엔드포인트로 들어오고, Redis에 세션/대화 상태를 저장합니다.
  - `GeminiClient` 가 명령을 intent·entities 로 해석하고 → `services.commands` 가 이를
    - Kubernetes 리소스 조회/스케일/롤백,
    - NCP 롤백/배포
    로 변환하여 실제 클러스터에 적용합니다.
  - 결과와 대화 내역은 PostgreSQL `command_history` 및 Redis에 저장되고, 요약 메시지는 다시 웹 UI/Slack 으로 반환됩니다.

- **3) 모니터링 & 헬스체크**
  - FastAPI는 `/api/v1/health`, `/api/v1/healthz`, `/metrics` 를 통해 상태와 메트릭을 노출합니다.
  - Prometheus가 이 엔드포인트와 Kubernetes/인프라 메트릭을 스크랩하고, Grafana(별도 구성)에서 시각화합니다.
  - `app/api/v1/monitoring.py` 와 `services.alerting` 이 장애 징후를 감지하면 Slack 채널로 경고를 전송합니다.

> 정리하면, 이 백엔드는  
> - **GitHub·NCP·Kubernetes·Slack·모니터링 인프라** 사이를 이어 주는 중앙 허브이자,  
> - **자연어 명령으로 인프라를 제어하는 인터페이스** 역할을 합니다.

---

## 프로젝트 디렉토리 구조 (요약)

> 실제 코드 기준, 이 백엔드에서 핵심이 되는 디렉토리만 정리했습니다.

```text
backend-hybrid/
├── app/
│   ├── main.py                # FastAPI 엔트리포인트
│   ├── api/
│   │   └── v1/                # REST API 라우터 (system, nlp, cicd, k8s, monitoring 등)
│   ├── services/              # 비즈니스 로직, 외부 연동(K8s, NCP, Slack, GitHub, CI/CD 등)
│   ├── models/                # SQLAlchemy ORM 모델 (배포 이력, 명령 이력, 사용자/리포지토리 등)
│   ├── core/                  # 설정(config), 로깅, 에러 핸들러
│   ├── llm/                   # Gemini 기반 NLP 클라이언트 및 인터페이스
│   ├── auth/, security/       # 인증/인가, JWT/OAuth, 권한/스코프
│   └── monitoring/, websocket # 모니터링 API, WebSocket 엔드포인트
├── tests/                     # pytest 기반 테스트 (NLP, K8s, CI/CD, Slack, 시스템 테스트 등)
├── docs/                      # 아키텍처/환경설정/NCP/Slack 연동 문서
├── screenshots/               # 아키텍처 다이어그램 등 이미지 (예: architecture-overview.png)
├── requirements.txt           # Python 의존성 정의
├── Dockerfile                 # 컨테이너 이미지 빌드 정의
└── README.md                  # 현재 문서
```

상세한 아키텍처/환경 설정은 `docs/` 디렉토리(특히 `docs/ENVIRONMENT_AND_CONFIG.md`, `docs/architecture/*`)를 함께 참고하면 됩니다.

---

## 구조 개요

- **엔트리포인트**: `app/main.py`
  - `create_app()` 에서 FastAPI 인스턴스 생성
  - 모든 v1 라우터(`app/api/v1/*.py`) 등록
  - 데이터베이스 초기화(`init_database()`), 서비스 초기화(`init_services()`)
  - Prometheus 메트릭 엔드포인트 `/metrics` 제공
- **REST API 계층**: `app/api/v1/`
  - `system.py`: `/api/v1/health`, `/api/v1/healthz`, `/api/v1/version` 등 시스템 상태 및 헬스체크
  - `cicd.py`: `/api/v1/cicd/webhook`, `/api/v1/cicd/staging-webhook`, GitHub App 설치/토큰 조회
  - `nlp.py`: 자연어 명령 처리, 대화형 NLP, 명령/대화 히스토리 관리
  - `deployments.py`, `deployment_histories.py`, `rollback.py`: 배포 및 롤백 관련 API
  - `k8s.py`: Kubernetes 리소스 조회/조작 API
  - `projects.py`, `user_url.py`, `admin_db.py`: 프로젝트/URL/관리자 DB 관련 API
  - `oauth2.py`, `github_oauth.py`, `slack_auth.py`, `auth_verify.py`: OAuth2, GitHub/Slack 인증, 토큰 검증
  - `tutorial.py`, `websocket.py`, `monitoring.py`, `ncp_pipeline_api.py`, `dashboard.py`, `metrics.py`: 튜토리얼·웹소켓·모니터링·NCP 파이프라인 등 도메인별 API
- **서비스 계층**: `app/services/`
  - 실제 비즈니스 로직, 외부 시스템 연동, 이력 관리, 감시(watcher), 보안/알림을 담당하는 모듈들
- **LLM/NLP 계층**: `app/llm/`
  - `gemini.py`: Google Gemini 기반 자연어 해석 클라이언트
  - `interfaces.py`: LLM 관련 공통 인터페이스/타입 정의
- **데이터베이스/모델**:
  - `app/database.py`: SQLAlchemy 세션 및 초기화, 서비스 초기화
  - `app/models/*.py`: 배포 이력, 커맨드 히스토리, 사용자/리포지토리/알림 관련 ORM 모델

---

## 동작 원리 (실제 흐름 기준)

### 1. FastAPI 앱 생성과 라우터 등록 (`app/main.py`)

1. `create_app()` 호출 시:
   - 로깅 설정: `app.core.logging_config.setup_logging()`
   - OpenAPI 스펙 버전(3.1.0)을 명시적으로 설정하고, JWT Bearer 인증 스키마를 전역에 추가
   - `app.state.started_at`에 기동 시각 저장 (헬스/메트릭에서 활용)
   - 에러 핸들러 등록: `app.core.error_handler.setup_error_handlers(app)`
   - CORS: 개발 편의를 위해 `allow_origins=["*"]` 로 설정 (운영에서는 축소 필요)
2. REST 라우터 등록:
   - `system`, `dashboard`, `deployments`, `nlp`, `cicd`, `k8s`, `monitoring`, `tutorial`, `websocket`, `slack_auth`, `oauth2`, `github_oauth`, `projects`, `deployment_histories`, `rollback`, `auth_verify`, `github_workflows`, `ncp_pipeline_api`, `admin_db`, `user_url` 등 모든 v1 라우터를 `/api/v1` 혹은 세부 prefix로 등록
3. 데이터베이스 및 서비스 초기화:
   - `init_database()` 호출 후, `get_db()`로 세션을 받아 `init_services(db_session)` 호출
4. 종료 시 처리:
   - `@app.on_event("shutdown")` 에서 `services.kubernetes_watcher.get_kubernetes_watcher()`를 통해 모든 K8s watch를 정리 (`stop_all_watches()` 호출)

### 2. 시스템 헬스 및 메트릭 (`app/api/v1/system.py`)

- `/api/v1/health`  
  - 단순 liveness/readiness 용 엔드포인트  
  - `app.state.started_at` 기준으로 `uptime_seconds` 계산
- `/api/v1/healthz`  
  - Prometheus 메트릭 및 외부 컴포넌트 헬스까지 포함한 **종합 헬스체크**  
  - 설정값(`get_settings()`) 기반으로 다음 컴포넌트들을 비동기 체크:
    - RabbitMQ Bridge Agent (`settings.rabbitmq_bridge_url`)
    - Prometheus (`settings.prometheus_base_url`)
    - Database (`/api/v1/health/db`)
  - 결과를 바탕으로 Prometheus `Counter`, `Gauge`, `Histogram`, `Enum` 에 메트릭 기록
  - `services.alerting.send_health_alert()` 를 통해 컴포넌트 상태 변화 시 Slack 등으로 알림
  - 전체 상태가 degraded일 경우 HTTP 503 반환
- `/api/v1/health/db`  
  - DB 연결 상태 확인용 (현재는 단순 OK 응답, 실제 환경에서는 DB 핸드셰이크 구현 예상)
- `/api/v1/version`  
  - 앱 이름 및 버전 정보 반환 (`APP_NAME`, `APP_VERSION`)

### 3. 자연어 명령 및 대화형 NLP (`app/api/v1/nlp.py`)

#### 3.1 단일 자연어 명령 처리 (`POST /api/v1/nlp/process`)

- 입력: `NaturalLanguageCommand`  
  - `command`: 한국어 자연어 명령 문자열  
  - `timestamp`, `context`: 선택적 메타데이터 (예: `project_name`)
- 흐름:
  1. JWT 토큰이 있으면 `services.security.get_current_user_id` 를 통해 사용자 식별, 없으면 `"api_user"` 사용
  2. 명령 유효성 검증 (길이, 위험한 키워드, 로그 라인 수 제한 등)
  3. `app.llm.gemini.GeminiClient` 의 `interpret()` 호출로 intent·entities 해석
  4. `services.command_history.save_command_history()` 로 명령 히스토리 DB 저장
  5. `services.commands.CommandRequest` 생성 후 `plan_command()` → `execute_command()` 호출
  6. Kubernetes/NCP 작업 결과를 Gemini 해석 결과와 조합하여 응답 (`CommandResponse`)
  7. 성공/실패 결과를 `services.command_history.update_command_status()` 로 DB에 반영

#### 3.2 대화형 인터랙션 (`POST /api/v1/nlp/conversation` 등)

- Redis를 사용한 세션 기반 멀티턴 대화:
  - `services.conversation_manager.ConversationManager`
  - `ConversationState` (INTERPRETING, ESTIMATING, WAITING_CONFIRMATION, EXECUTING, COMPLETED 등)
- 주요 컴포넌트:
  - `services.action_classifier.ActionClassifier`: intent별 위험도 분류 및 확인 여부 판단
  - `services.cost_estimator.CostEstimator`: NCP 기반 배포 비용 추정
  - `services.response_formatter.ResponseFormatter`: 스케일링/재시작/롤백 결과 메시지 포맷
  - `services.nlp_rollback.RollbackCommandParser`: 롤백 명령어 폴백 파서
- 엔드포인트:
  - `POST /api/v1/nlp/conversation`  
    - 사용자 메시지 수신 → Gemini 기반 해석 → 위험도/비용 산정 → 필요 시 사용자 확인 요청  
    - 확인이 필요 없는 작업은 즉시 `plan_command`/`execute_command` 실행
  - `POST /api/v1/nlp/confirm`  
    - 대기 중인 고위험 작업(배포/스케일링/롤백/재시작 등)에 대한 사용자 승인/거부 처리
  - `GET /api/v1/nlp/history`, `/api/v1/nlp/conversation-history`, `/api/v1/nlp/conversations`  
    - DB 및 Redis에 저장된 명령/대화 히스토리 조회
  - `DELETE /api/v1/nlp/conversation/{session_id}`  
    - 특정 대화 세션 삭제
  - `GET /api/v1/nlp/suggestions`  
    - 자주 사용하는 Kubernetes/NCP 명령 예시를 반환

> 이 NLP 계층은 실제 코드 상에서 **Gemini 단일 모델**을 사용하며, README에서는 존재하지 않는 `AdvancedNLPService` 나 별도 파일을 가정하지 않습니다.

### 4. CI/CD 및 GitHub 연동 (`app/api/v1/cicd.py`, `app/services/cicd.py`, `app/services/github_app.py`)

- `/api/v1/cicd/webhook`  
  - GitHub Webhook 엔드포인트  
  - `X-Hub-Signature-256` 검증 (`services.cicd.verify_github_signature`)  
  - `push` 이벤트 → `handle_push_event()`  
  - `release` 이벤트 → `handle_release_event()`  
  - 배포 히스토리 기록 및 (환경에 따라) K8s 배포, Slack 알림 등 수행
- `/api/v1/cicd/staging-webhook`  
  - 별도 HMAC 서명(`X-Signature`, `X-Signature-Timestamp`) 기반의 스테이징용 웹훅
- GitHub App 연동:
  - `/api/v1/cicd/github/app/installations`  
    - `services.github_app.github_app_auth.get_app_installations()` 를 호출하여 설치 목록 조회
  - `/api/v1/cicd/github/app/installations/{installation_id}/token`  
    - 지정 installation에 대한 설치 토큰 발급

### 5. 배포/이력/감사 로깅 및 기타 서비스 (`app/services/*`, `app/models/*`)

코드 상에서 실제로 import·사용되는 주요 서비스/모델들:

- 배포/이력:
  - `services.deployment.py`, `services.deployments.py`, `services.deployment_history.py`, `services.deployment_config.py`
  - `models.deployment_history.DeploymentHistory`
  - `models.deployment_url.DeploymentUrl`
- 명령/대화 이력:
  - `services.command_history` (NLP 및 대화형 인터랙션에서 사용)
  - `models.command_history.CommandHistory`
- 알림 및 Slack 연동:
  - `services.notification_service`, `services.slack_notification_service`, `services.slack_template_builder`, `services.slack_oauth`, `services.slack_client`, `services.alerting`
  - `models.notification.Notification`, `NotificationReport`
- GitHub 및 CI/CD:
  - `services.cicd`, `services.github_workflow`, `services.github_app`
  - `models.user_project_integration`, `models.user_repository`
- Kubernetes/NCP 연동:
  - `services.k8s_client`, `services.k8s_logs`, `services.kubernetes_watcher`, `services.cluster`
  - `services.ncp_pipeline`, `services.ncp_deployment_status_poller`, `services.nlp_rollback`
- 보안/감사/모니터링:
  - `services.security` (스코프, 인증 관련)
  - `services.audit_logger`, `services.audit`
  - `services.monitoring`
- 기타:
  - `services.history`, `services.tutorial`, `services.tutorial_script`, `services.domain_changer`, `services.pipeline_user_url`, `services.user_slack_config_service`
  - `models.audit_log.AuditLogModel`, `models.oauth_token.OAuthToken`, `models.user_slack_config`, `models.slack_events.SlackEventModel`

> 위 목록은 실제 import·테스트에서 사용되는 모듈만 포함하며, 코드에 존재하지 않는 파일명 또는 더 이상 사용되지 않는 레거시 파일은 나열하지 않습니다.

---

## 로컬 실행

이 프로젝트는 Python 가상환경(venv)을 전제로 합니다.

```bash
cd backend-hybrid

# venv 생성
python -m venv venv

# (macOS / Linux)
source venv/bin/activate

# (Windows PowerShell)
# .\venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt

# 개발 서버 실행
uvicorn app.main:app --reload --port 8080
```

- Health: `GET http://localhost:8080/api/v1/health`
- Version: `GET http://localhost:8080/api/v1/version`

---

## Docker 실행

```bash
cd backend-hybrid

docker build -t klepaas-backend:dev .
docker run --rm -p 8080:8080 klepaas-backend:dev
```

---

## 환경 변수 (실제 코드에서 사용되는 주요 항목)

대부분 `app/core/config.py` 및 서비스 레이어에서 `KLEPAAS_` 접두사 또는 관련 키로 사용됩니다. 아래는 코드·테스트에서 실제로 참조되는 범주입니다.

- **Slack/알림 관련**
  - `KLEPAAS_SLACK_WEBHOOK_URL`
  - `KLEPAAS_SLACK_ALERT_CHANNEL_DEFAULT`
  - `KLEPAAS_SLACK_ALERT_CHANNEL_RATE_LIMITED`
  - `KLEPAAS_SLACK_ALERT_CHANNEL_UNAUTHORIZED`
  - `KLEPAAS_SLACK_ALERT_TEMPLATE_ERROR`
  - `KLEPAAS_SLACK_ALERT_TEMPLATE_HEALTH_DOWN`
- **CI/CD 및 GitHub**
  - `KLEPAAS_WEBHOOK_URL`, `KLEPAAS_WEBHOOK_SECRET`
  - GitHub App/OAuth 관련 키 (`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` 등)
- **데이터베이스/캐시/모니터링**
  - `DATABASE_URL`
  - `REDIS_URL` (또는 설정 객체 내 `redis_url`)
  - `PROMETHEUS_BASE_URL`, `ALERTMANAGER_URL`, `ALERTMANAGER_WEBHOOK_URL`
- **Kubernetes/NCP**
  - `ENABLE_K8S_DEPLOY`
  - `K8S_STAGING_NAMESPACE`
  - `K8S_IMAGE_PULL_SECRET`
  - NCP 관련 키 (NKS 클러스터, SourceDeploy/SourceCommit 엔드포인트 등)
- **LLM/Gemini**
  - `GEMINI_API_KEY` 및 GCP/Gemini 설정 (프로젝트/리전/모델 이름 등)

> 실제 사용되는 환경 변수 세부 목록은 `app/core/config.py` 와 관련 서비스 모듈을 기준으로 확인하는 것을 권장합니다.

---

## 보안 · 감사 (요약)

- **보안/스코프**:  
  - `app/services/security.py` 에서 스코프 기반 접근 제어를 구현  
  - 테스트 환경에서는 `X-Scopes` 헤더를 사용, 운영 환경에서는 JWT/OAuth 토큰 클레임으로 스코프 파싱
- **감사 로깅**:  
  - `app/services/audit_logger.py`, `app/services/audit.py`  
  - 시간/사용자/IP/액션/리소스/상태/상세 를 JSON 구조로 기록 (중앙 로그 시스템 연계 전제)

---

## 테스트

```bash
source venv/bin/activate  # venv 활성화

python -m pytest tests/ -v
```

- 주요 테스트 파일 (실제 존재 및 사용 기준):
  - `tests/test_advanced_nlp_integration.py`, `tests/test_nlp_system.py` : NLP/명령 흐름 검증
  - `tests/test_k8s_api.py`, `tests/test_ncp_manifest_update.py` : Kubernetes/NCP 관련 기능
  - `tests/test_cicd_mcp_trigger.py`, `tests/test_system.py`, `tests/test_healthz.py` 등 시스템/헬스/보안 테스트
  - Slack/알림/템플릿 관련: `tests/test_slack_*`, `tests/test_slack_notification_service.py`, `tests/test_slack_templates.py`

테스트는 실제 코드 경로와 일치하는 모듈만을 대상으로 하며, 존재하지 않는 서비스/파일에 대한 언급은 포함하지 않습니다.

---

## 운영 가이드 (요약)

- MCP:
  - FastMCP 설치 여부에 따라 실제 MCP 서버 또는 stub 모드로 동작
  - `/mcp/info`, `/mcp/tools`, `/mcp/stream` 경로를 통해 상태 및 도구 목록 확인
- CORS:
  - 개발 편의상 `allow_origins=["*"]` 로 설정되어 있으므로, 운영 환경에서는 도메인 화이트리스트를 반드시 적용해야 합니다.
- 데이터베이스:
  - 기본 SQLite를 사용하지만, `DATABASE_URL` 설정을 통해 PostgreSQL 등으로 전환 가능
- 헬스·알림:
  - `/api/v1/healthz` 결과를 기준으로 Prometheus/Alertmanager/Slack 연동을 구성

이 README는 **현재 코드와 테스트에 실제로 존재하고 사용되는 파일·폴더** 만을 기준으로 작성되었습니다. 코드 구조 변경 시에는 `app/main.py`, `app/api/v1/*`, `app/services/*`, `app/mcp/*`, `app/models/*`, `tests/*` 를 기준으로 이 문서를 함께 업데이트하는 것을 권장합니다.
