# K-Le-PaaS Backend Hybrid - 전체 아키텍처 문서

> **목적**: K-Le-PaaS Backend Hybrid 시스템의 전체 아키텍처, 디렉토리 구조, 핵심 컴포넌트, 데이터 흐름을 포괄적으로 설명하는 문서

---

## 📋 목차

1. [시스템 개요](#시스템-개요)
2. [기술 스택](#기술-스택)
3. [전체 아키텍처](#전체-아키텍처)
4. [디렉토리 구조](#디렉토리-구조)
5. [핵심 컴포넌트](#핵심-컴포넌트)
6. [데이터 흐름](#데이터-흐름)
7. [보안 및 인증](#보안-및-인증)
8. [모니터링 및 로깅](#모니터링-및-로깅)
9. [확장성 및 성능](#확장성-및-성능)

---

## 🎯 시스템 개요

### 프로젝트 설명
K-Le-PaaS Backend Hybrid는 **AI 기반 Kubernetes PaaS 플랫폼**의 백엔드 시스템입니다.

### 핵심 특징
- **FastAPI 기반**: 고성능 비동기 REST API
- **MCP(Model Context Protocol) 서버**: AI 에이전트와의 통합을 위한 표준 프로토콜
- **Multi-LLM NLP 시스템**: Claude, GPT-4, Gemini를 활용한 자연어 명령 처리
- **Kubernetes 네이티브**: K8s 클러스터 완전 제어 및 관리
- **Multi-Cloud 지원**: GCP, NCP(Naver Cloud Platform) 통합
- **CI/CD 자동화**: GitHub Webhook 기반 자동 배포

### 주요 기능
1. **자연어 명령 처리**: "nginx 재시작해줘" → Kubernetes API 실행
2. **배포 자동화**: Git Push → 자동 빌드 → 자동 배포
3. **실시간 모니터링**: Prometheus + WebSocket 기반 실시간 대시보드
4. **통합 인증**: GitHub, Google, Slack OAuth2
5. **외부 MCP 연동**: GitHub, Slack 등 외부 MCP 서버와의 표준화된 통신

---

## 🛠 기술 스택

### 백엔드 프레임워크
- **FastAPI**: Python 비동기 웹 프레임워크
- **Pydantic**: 데이터 검증 및 설정 관리
- **SQLAlchemy**: ORM 및 데이터베이스 관리
- **structlog**: 구조화된 로깅

### AI/ML
- **Google Gemini**: 자연어 처리 (주요)
- **Claude API**: 고급 추론 및 컨텍스트 이해
- **OpenAI GPT-4**: 멀티모델 처리 및 검증
- **Redis**: 컨텍스트 캐싱 및 세션 관리

### Kubernetes
- **kubernetes-python-client**: K8s API 클라이언트
- **Apps V1 API**: Deployment, ReplicaSet 관리
- **Core V1 API**: Pod, Service, ConfigMap 관리
- **Networking V1 API**: Ingress, NetworkPolicy 관리

### 데이터베이스
- **SQLite**: 로컬 개발
- **PostgreSQL**: 프로덕션 환경

### 모니터링
- **Prometheus**: 메트릭 수집 및 쿼리
- **Alertmanager**: 알림 라우팅 및 관리
- **WebSocket**: 실시간 이벤트 스트리밍

### 외부 통합
- **GitHub API**: OAuth, Webhook, Workflow 트리거
- **Slack API**: OAuth, Notification, MCP 연동
- **NCP SourceDeploy**: NCP 전용 CI/CD 파이프라인
- **FastMCP**: MCP 서버 구현 및 툴 등록

---

## 🏗 전체 아키텍처

### 레이어 구조
```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
│  (Frontend, Claude Desktop, External MCP Clients)            │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTP/WebSocket/MCP
┌────────────────▼────────────────────────────────────────────┐
│                    API Gateway Layer                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ REST API │  │ WebSocket│  │   MCP    │  │  OAuth2  │   │
│  │ /api/v1  │  │   /ws    │  │  /mcp    │  │  /oauth  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                   Service Layer                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ NLP Service  │  │ Deployment   │  │   GitHub     │      │
│  │   (Gemini)   │  │   Service    │  │   Service    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ K8s Service  │  │   Monitoring │  │    Slack     │      │
│  │              │  │   Service    │  │   Service    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────────┐
│                 Integration Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Kubernetes   │  │  Prometheus  │  │    Redis     │      │
│  │   Cluster    │  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  PostgreSQL  │  │  GitHub API  │  │  Slack API   │      │
│  │              │  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 요청 처리 흐름

#### 1. REST API 요청 흐름
```
사용자 → FastAPI Router → Service Layer → K8s/DB/External API → Response
```

#### 2. NLP 명령 처리 흐름
```
자연어 입력 → Gemini API (파싱) → CommandPlan (계획) → K8s API (실행) → 결과 반환
```

#### 3. CI/CD 자동 배포 흐름
```
Git Push → GitHub Webhook → CICD Service → K8s Deployment → Slack Notification
```

#### 4. MCP 통신 흐름
```
MCP Client → FastMCP Server → Tool Handler → K8s/Service Layer → MCP Response
```

---

## 📂 디렉토리 구조

### 전체 구조 (95개 Python 파일)
```
backend-hybrid/
├── app/                          # 메인 애플리케이션
│   ├── main.py                   # FastAPI 앱 엔트리포인트
│   ├── database.py               # DB 초기화 및 세션 관리
│   │
│   ├── api/                      # API 엔드포인트 (18개 라우터)
│   │   └── v1/
│   │       ├── system.py         # Health, Version, Metrics
│   │       ├── deployments.py    # 배포 관리
│   │       ├── nlp.py            # NLP 명령 처리
│   │       ├── cicd.py           # GitHub Webhook
│   │       ├── k8s.py            # K8s 리소스 관리
│   │       ├── monitoring.py     # Prometheus 쿼리
│   │       ├── github_workflows.py  # GitHub Workflow 트리거
│   │       ├── github_oauth.py   # GitHub OAuth
│   │       ├── slack_auth.py     # Slack OAuth
│   │       ├── oauth2.py         # Google OAuth
│   │       ├── projects.py       # 프로젝트 통합
│   │       ├── tutorial.py       # 인터랙티브 튜토리얼
│   │       ├── websocket.py      # WebSocket 엔드포인트
│   │       ├── dashboard.py      # 대시보드 데이터
│   │       ├── metrics.py        # 메트릭 조회
│   │       ├── deployment_histories.py  # 배포 이력
│   │       └── auth_verify.py    # 인증 검증
│   │
│   ├── services/                 # 비즈니스 로직 (30+ 서비스)
│   │   ├── deployments.py        # 배포 로직
│   │   ├── deployments_enhanced.py  # 고급 배포 기능
│   │   ├── k8s_client.py         # K8s API 클라이언트
│   │   ├── commands.py           # NLP 명령 실행
│   │   ├── github_app.py         # GitHub App 통합
│   │   ├── github_workflow.py    # Workflow 관리
│   │   ├── slack_notification.py # Slack 알림
│   │   ├── slack_oauth.py        # Slack OAuth 처리
│   │   ├── cicd.py               # CI/CD 파이프라인
│   │   ├── ncp_pipeline.py       # NCP SourceDeploy
│   │   ├── monitoring.py         # Prometheus 쿼리
│   │   ├── alerting.py           # Alertmanager 통합
│   │   ├── kubernetes_watcher.py # K8s 이벤트 감시
│   │   ├── audit.py              # 감사 로깅
│   │   ├── audit_logger.py       # 감사 로거 구현
│   │   ├── command_history.py    # 명령 이력 관리
│   │   ├── deployment_history.py # 배포 이력 관리
│   │   ├── rollback.py           # 롤백 처리
│   │   └── ...
│   │
│   ├── llm/                      # AI/LLM 통합
│   │   ├── gemini.py             # Gemini API 클라이언트
│   │   └── interfaces.py         # LLM 인터페이스 정의
│   │
│   ├── mcp/                      # MCP 서버 및 툴
│   │   ├── tools/                # MCP 툴 구현
│   │   │   ├── deploy_app.py     # 배포 툴
│   │   │   ├── k8s_resources.py  # K8s 리소스 관리
│   │   │   ├── rollback.py       # 롤백 툴
│   │   │   ├── monitor.py        # 모니터링 툴
│   │   │   ├── health_monitor_tools.py  # 헬스체크 툴
│   │   │   ├── git_deployment_tools.py  # Git 배포 자동화
│   │   │   └── tutorial.py       # 튜토리얼 툴
│   │   │
│   │   └── external/             # 외부 MCP 연동
│   │       ├── api.py            # 외부 MCP API 라우터
│   │       ├── interfaces.py     # 표준 인터페이스
│   │       ├── errors.py         # 에러 스키마
│   │       ├── retry.py          # 재시도 로직
│   │       ├── metrics.py        # 메트릭 수집
│   │       ├── handlers.py       # Circuit Breaker
│   │       ├── registry.py       # MCP Provider 레지스트리
│   │       ├── message_converter.py  # 메시지 변환
│   │       └── providers/
│   │           ├── github.py     # GitHub MCP 클라이언트
│   │           └── slack.py      # Slack MCP 클라이언트
│   │
│   ├── models/                   # SQLAlchemy ORM 모델
│   │   ├── base.py               # Base 모델
│   │   ├── user_repository.py    # 사용자 저장소
│   │   ├── command_history.py    # 명령 이력
│   │   ├── deployment_history.py # 배포 이력
│   │   ├── audit_log.py          # 감사 로그
│   │   ├── oauth_token.py        # OAuth 토큰
│   │   ├── user_project_integration.py  # 프로젝트 통합
│   │   └── slack_events.py       # Slack 이벤트
│   │
│   ├── core/                     # 핵심 설정 및 유틸
│   │   ├── config.py             # Pydantic Settings
│   │   ├── error_handler.py      # 전역 에러 핸들러
│   │   └── logging_config.py     # 로깅 설정
│   │
│   ├── auth/                     # 인증/인가
│   │   ├── oauth.py              # OAuth2 플로우
│   │   ├── github.py             # GitHub 인증
│   │   └── ...
│   │
│   ├── security/                 # 보안 관련
│   │   └── ...                   # Scopes, JWT 검증
│   │
│   ├── websocket/                # WebSocket 핸들러
│   │   └── deployment_monitor.py # 배포 모니터링 WS
│   │
│   ├── monitoring/               # 모니터링 유틸
│   │   └── ...
│   │
│   └── templates/                # 템플릿 (Slack 메시지 등)
│       └── slack/
│
├── docs/                         # 문서
│   ├── README.md                 # 문서 인덱스
│   ├── ENVIRONMENT_AND_CONFIG.md # 환경 설정 가이드
│   ├── architecture/             # 아키텍처 문서
│   │   ├── BACKEND_ARCHITECTURE.md  # 이 문서
│   │   ├── nlp/
│   │   │   ├── implementation.md # NLP 구현 가이드
│   │   │   ├── execution.md      # NLP 실행 아키텍처
│   │   │   └── quick_start.md    # NLP 퀵스타트
│   │   └── tutorial/
│   │       └── implementation.md # 튜토리얼 구현
│   ├── integrations/             # 외부 통합 문서
│   │   └── SLACK_SETUP.md        # Slack 설정 가이드
│   └── ncp/                      # NCP 관련 문서
│
├── tests/                        # 테스트 코드
├── requirements.txt              # Python 의존성
├── Dockerfile                    # Docker 이미지 빌드
├── .env                          # 환경 변수 (로컬)
└── README.md                     # 프로젝트 README
```

---

## 🔧 핵심 컴포넌트

### 1. **FastAPI 애플리케이션 (`app/main.py`)**

**역할**: 전체 애플리케이션의 진입점

**주요 기능**:
- 모든 라우터 등록 (18개 API 라우터)
- CORS 설정 (현재 `allow_origins=["*"]` - 프로덕션에서는 제한 필요)
- MCP 서버 마운트 (`/mcp/stream`)
- 데이터베이스 초기화
- 에러 핸들러 설정
- Prometheus 메트릭 노출 (`/metrics`)

**코드 위치**: `backend-hybrid/app/main.py`

**핵심 코드 패턴**:
```python
app = FastAPI(title="K-Le-PaaS Backend Hybrid", version="0.1.0")

# 라우터 등록
app.include_router(system_router, prefix="/api/v1", tags=["system"])
app.include_router(deployments_router, prefix="/api/v1", tags=["deployments"])
# ... 18개 라우터

# MCP 서버 마운트
app.mount("/mcp", mcp_app)
```

---

### 2. **NLP 시스템 (`app/llm/` + `app/services/commands.py`)**

**역할**: 자연어를 Kubernetes 명령으로 변환하고 실행

**아키텍처**:
```
자연어 입력 "nginx 재시작해줘"
    ↓
Gemini API (app/llm/gemini.py)
    → 시스템 프롬프트로 명령어 14가지 정의
    → JSON 파싱: {"command": "restart", "parameters": {"appName": "nginx"}}
    ↓
CommandPlan 생성 (app/services/commands.py - plan_command)
    → tool: "k8s_restart"
    → args: {"name": "nginx", "namespace": "default"}
    ↓
실행 (app/services/commands.py - execute_command)
    → _execute_restart() 호출
    → Kubernetes API: apps_v1.patch_namespaced_deployment()
    → kubectl rollout restart 방식
    ↓
결과 반환
    → {"status": "success", "message": "재시작 완료"}
```

**지원 명령어 (14개)**:
1. `status` - 상태 확인
2. `logs` - 로그 조회
3. `endpoint` - 접속 주소
4. `restart` - 재시작
5. `scale` - 스케일링
6. `rollback` - 롤백
7. `deploy` - 배포
8. `overview` - 통합 대시보드
9. `list_pods` - 파드 목록
10. `list_deployments` - Deployment 목록
11. `list_services` - Service 목록
12. `list_ingresses` - Ingress 목록
13. `list_namespaces` - 네임스페이스 목록
14. `list_apps` - 특정 네임스페이스 앱 목록

**문서**: `docs/architecture/nlp/implementation.md`

---

### 3. **Kubernetes 클라이언트 (`app/services/k8s_client.py`)**

**역할**: Kubernetes API와의 모든 통신 관리

**주요 API 클라이언트**:
- `get_core_v1_api()`: Pod, Service, ConfigMap, Secret
- `get_apps_v1_api()`: Deployment, ReplicaSet, StatefulSet
- `get_networking_v1_api()`: Ingress, NetworkPolicy

**설정 방식**:
1. **InCluster**: Pod 내부에서 실행 시 자동 감지
2. **KubeConfig**: `~/.kube/config` 또는 `KUBECONFIG` 환경변수

**코드 위치**: `backend-hybrid/app/services/k8s_client.py`

**사용 예시**:
```python
from app.services.k8s_client import get_apps_v1_api, get_core_v1_api

# Deployment 조회
apps_v1 = get_apps_v1_api()
deployment = apps_v1.read_namespaced_deployment(name="nginx", namespace="default")

# Pod 목록 조회
core_v1 = get_core_v1_api()
pods = core_v1.list_namespaced_pod(namespace="default", label_selector="app=nginx")
```

---

### 4. **MCP 서버 (`app/main.py` + `app/mcp/tools/`)**

**역할**: Claude Desktop 및 기타 MCP 클라이언트와의 통합

**마운트 위치**: `/mcp/stream`

**등록된 툴 (9개)**:
1. `deploy_app` - 애플리케이션 배포
2. `get_k8s_resource` - K8s 리소스 조회
3. `create_k8s_resource` - K8s 리소스 생성
4. `apply_k8s_manifest` - 매니페스트 적용
5. `delete_k8s_resource` - K8s 리소스 삭제
6. `rollback_deployment` - 롤백 실행
7. `query_prometheus` - Prometheus 쿼리
8. `check_health` - 헬스체크
9. `trigger_git_deployment` - Git 기반 배포

**툴 등록 패턴**:
```python
from app.main import mcp_server

@mcp_server.tool()
async def deploy_app(
    app_name: str,
    image: str,
    namespace: str = "default",
    replicas: int = 1
) -> dict:
    """애플리케이션을 K8s에 배포합니다."""
    # 배포 로직
    return {"status": "success", "message": "배포 완료"}
```

**MCP 클라이언트 접속**:
```json
{
  "mcpServers": {
    "klepaas": {
      "url": "http://localhost:8080/mcp/stream"
    }
  }
}
```

---

### 5. **CI/CD 자동화 (`app/api/v1/cicd.py` + `app/services/cicd.py`)**

**역할**: GitHub Webhook을 통한 자동 배포

**워크플로우**:
```
GitHub Push (main 브랜치)
    ↓
GitHub Actions 실행 (.github/workflows/ci.yml)
    → Docker 이미지 빌드
    → Docker Hub 푸시 (태그: <sha>, latest)
    → deployment-config 레포지토리 업데이트
    → values/backend-hybrid-values.yaml 수정
    ↓
GitHub Webhook → K-Le-PaaS Backend (/api/v1/cicd/webhook)
    → HMAC 서명 검증
    → 이벤트 타입 확인 (push/release)
    → CICD Service 실행
    ↓
Kubernetes Deployment (ENABLE_K8S_DEPLOY=true 시)
    → staging/production 네임스페이스
    → 새 이미지로 Deployment 업데이트
    ↓
Slack 알림
    → 배포 성공/실패 메시지
    → 롤백 버튼 제공
```

**보안**:
- **HMAC 서명 검증**: `GITHUB_WEBHOOK_SECRET`으로 요청 진위 확인
- **IP 화이트리스트**: (선택사항) GitHub IP 범위만 허용

**코드 위치**:
- `backend-hybrid/app/api/v1/cicd.py` - Webhook 엔드포인트
- `backend-hybrid/app/services/cicd.py` - 배포 로직

---

### 6. **외부 MCP 연동 (`app/mcp/external/`)**

**역할**: GitHub, Slack 등 외부 MCP 서버와의 표준화된 통신

**아키텍처**:
```
┌─────────────────────────────────────────────────┐
│         External MCP Client Interface           │
│  (app/mcp/external/interfaces.py)               │
│  - connect()                                    │
│  - list_tools()                                 │
│  - call_tool(tool_name, arguments)              │
│  - health()                                     │
│  - close()                                      │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Circuit Breaker                    │
│  (app/mcp/external/handlers.py)                 │
│  - Closed → Open → Half-Open → Closed          │
│  - 실패 임계값 초과 시 자동 차단                │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│            Retry with Backoff                   │
│  (app/mcp/external/retry.py)                    │
│  - 지수 백오프 + Jitter                         │
│  - Retry-After 헤더 존중                        │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│         Provider Implementations                │
│  ┌──────────────┐      ┌──────────────┐        │
│  │ GitHub MCP   │      │  Slack MCP   │        │
│  │ (providers/  │      │ (providers/  │        │
│  │  github.py)  │      │  slack.py)   │        │
│  └──────────────┘      └──────────────┘        │
└─────────────────────────────────────────────────┘
```

**표준 에러 코드**:
- `unauthorized` (401)
- `forbidden` (403)
- `not_found` (404)
- `rate_limited` (429)
- `timeout` (504)
- `unavailable` (503)
- `bad_request` (400)
- `conflict` (409)
- `internal` (500)

**메트릭 수집**:
- `mcp_external_requests_total` - 요청 횟수
- `mcp_external_request_latency_seconds` - 요청 지연시간

---

### 7. **데이터베이스 모델 (`app/models/`)**

**ORM**: SQLAlchemy

**모델 목록**:

| 모델 | 파일 | 설명 |
|------|------|------|
| `UserRepository` | `user_repository.py` | GitHub/GitLab 저장소 연결 |
| `CommandHistory` | `command_history.py` | NLP 명령 이력 |
| `DeploymentHistory` | `deployment_history.py` | 배포 이력 및 감사 추적 |
| `AuditLogModel` | `audit_log.py` | 감사 로그 (JSON 구조화) |
| `OAuthToken` | `oauth_token.py` | OAuth2 토큰 저장 |
| `UserProjectIntegration` | `user_project_integration.py` | 사용자-프로젝트-프로바이더 통합 |
| `SlackEvent` | `slack_events.py` | Slack 이벤트 저장 |

**초기화**:
```python
# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# 모든 테이블 생성
Base.metadata.create_all(bind=engine)
```

**세션 관리**:
```python
from app.database import get_db

@router.get("/")
def read_items(db: Session = Depends(get_db)):
    items = db.query(Item).all()
    return items
```

---

### 8. **설정 관리 (`app/core/config.py`)**

**방식**: Pydantic Settings

**환경변수 우선순위**:
1. Kubernetes Secret (프로덕션)
2. 시스템 환경변수
3. `.env` 파일 (로컬)
4. 기본값

**주요 설정 그룹**:

#### AI 모델
```python
CLAUDE_API_KEY: str
OPENAI_API_KEY: str
GEMINI_API_KEY: str
GEMINI_MODEL: str = "gemini-2.0-flash-exp"
```

#### 클라우드 프로바이더
```python
# GCP
GCP_PROJECT: str
GCP_LOCATION: str

# NCP
NCP_ACCESS_KEY: str
NCP_SECRET_KEY: str
NCP_API_GW: str
NCP_SOURCECOMMIT_ENDPOINT: str
NCP_SOURCEDEPLOY_ENDPOINT: str
NCP_NKS_CLUSTER_ID: str
```

#### GitHub
```python
GITHUB_WEBHOOK_SECRET: str
GITHUB_APP_ID: str
GITHUB_APP_PRIVATE_KEY: str
GITHUB_CLIENT_ID: str
GITHUB_CLIENT_SECRET: str
DEPLOYMENT_CONFIG_REPO: str
DEPLOYMENT_CONFIG_TOKEN: str
```

#### Slack
```python
SLACK_WEBHOOK_URL: str
SLACK_CLIENT_ID: str
SLACK_CLIENT_SECRET: str
SLACK_REDIRECT_URI: str
SLACK_ALERT_CHANNEL_DEFAULT: str
SLACK_ALERT_TEMPLATE_ERROR: str
```

#### 모니터링
```python
PROMETHEUS_BASE_URL: str
ALERTMANAGER_URL: str
DATABASE_URL: str = "sqlite:///./klepaas.db"
REDIS_URL: str = "redis://localhost:6379"
```

#### Kubernetes
```python
ENABLE_K8S_DEPLOY: bool = False
K8S_STAGING_NAMESPACE: str = "staging"
K8S_IMAGE_PULL_SECRET: str = "ncp-cr"
```

**사용 예시**:
```python
from app.core.config import get_settings

settings = get_settings()
gemini_api_key = settings.GEMINI_API_KEY
```

---

## 🔄 데이터 흐름

### 1. **NLP 명령 처리 전체 흐름**

```
사용자 입력 (Frontend/MCP Client)
    → POST /api/v1/nlp/process
    ↓
API 엔드포인트 (app/api/v1/nlp.py)
    → 요청 검증 (NLPRequest 스키마)
    → GeminiClient.parse_command() 호출
    ↓
Gemini API (app/llm/gemini.py)
    → 시스템 프롬프트 주입 (14개 명령어 정의)
    → 자연어 → JSON 변환
    → CommandRequest 객체 생성
    ↓
명령 계획 (app/services/commands.py - plan_command)
    → CommandRequest → CommandPlan
    → tool 선택 (예: "k8s_restart")
    → args 준비 (예: {"name": "nginx", "namespace": "default"})
    ↓
명령 실행 (app/services/commands.py - execute_command)
    → CommandPlan.tool에 따라 분기
    → _execute_restart() 호출
    ↓
Kubernetes API (app/services/k8s_client.py)
    → get_apps_v1_api() 획득
    → apps_v1.patch_namespaced_deployment()
    → kubectl rollout restart 방식
    ↓
결과 반환
    → K8s API 응답 가공
    → {"status": "success", "message": "재시작 완료"}
    ↓
감사 로깅 (app/services/audit.py)
    → AuditLogModel 생성
    → 타임스탬프, 사용자, IP, 명령, 결과 저장
    ↓
명령 이력 저장 (app/models/command_history.py)
    → CommandHistory 레코드 생성
    → 나중에 사용자 피드백 학습에 활용
    ↓
응답 (JSON)
    → 사용자에게 결과 전달
```

---

### 2. **CI/CD 자동 배포 전체 흐름**

```
개발자 Git Push (main 브랜치)
    ↓
GitHub Actions 트리거 (.github/workflows/ci.yml)
    → Checkout 코드
    → Docker 이미지 빌드
    → Docker Hub 푸시 (TAG: <git-sha>)
    ↓
deployment-config 레포지토리 업데이트
    → values/backend-hybrid-values.yaml 수정
    → image.tag: <git-sha>
    → Commit & Push
    ↓
GitHub Webhook 발송
    → POST /api/v1/cicd/webhook
    → Event: push / release
    ↓
Webhook 검증 (app/api/v1/cicd.py)
    → HMAC 서명 검증 (GITHUB_WEBHOOK_SECRET)
    → 유효하지 않으면 401 Unauthorized
    ↓
CICD Service 실행 (app/services/cicd.py)
    → 이벤트 타입 확인 (push → staging, release → production)
    → 배포 대상 네임스페이스 결정
    ↓
Kubernetes 배포 (ENABLE_K8S_DEPLOY=true)
    → get_apps_v1_api() 획득
    → Deployment 조회
    → 새 이미지로 업데이트
    → apps_v1.patch_namespaced_deployment()
    ↓
배포 이력 저장 (app/models/deployment_history.py)
    → DeploymentHistory 레코드 생성
    → 타임스탬프, 사용자, 이미지, 상태, 네임스페이스
    ↓
Slack 알림 (app/services/slack_notification.py)
    → 배포 성공/실패 메시지
    → 롤백 버튼 포함
    → Jinja2 템플릿 렌더링
    ↓
Kubernetes 리소스 감시 (app/services/kubernetes_watcher.py)
    → Deployment 이벤트 Watch
    → Pod 상태 변화 감지
    → WebSocket으로 실시간 브로드캐스트
    ↓
WebSocket 클라이언트 (Frontend)
    → 실시간 배포 진행 상황 표시
    → Pod Ready 상태 확인
    → 배포 완료 알림
```

---

### 3. **실시간 모니터링 데이터 흐름**

```
Prometheus Metrics
    → K8s 클러스터에서 메트릭 수집
    → 노드, 파드, 컨테이너 리소스 사용률
    ↓
Backend Prometheus 쿼리 (app/services/monitoring.py)
    → POST /api/v1/monitoring/query
    → Prometheus API 호출
    → PromQL 실행
    ↓
메트릭 데이터 가공
    → CPU, 메모리, 네트워크 사용률 계산
    → 시계열 데이터 정규화
    ↓
WebSocket 브로드캐스트 (app/websocket/deployment_monitor.py)
    → /ws/deployments/<deployment-id>
    → 실시간 메트릭 푸시
    ↓
Frontend Dashboard (React)
    → Recharts로 실시간 그래프 렌더링
    → CPU/메모리 사용률 표시
    → 알림 임계값 초과 시 경고
```

---

## 🔒 보안 및 인증

### 1. **OAuth2 인증 플로우**

#### GitHub OAuth
```
사용자 → "Login with GitHub" 클릭
    ↓
Redirect to GitHub OAuth
    → https://github.com/login/oauth/authorize
    → client_id, redirect_uri, scope
    ↓
사용자 GitHub 로그인 및 승인
    ↓
Redirect to K-Le-PaaS Callback
    → /api/v1/github/callback?code=<auth-code>
    ↓
Authorization Code 교환 (app/api/v1/github_oauth.py)
    → POST https://github.com/login/oauth/access_token
    → client_id, client_secret, code
    → 응답: access_token
    ↓
사용자 정보 조회
    → GET https://api.github.com/user
    → Authorization: Bearer <access_token>
    ↓
세션 생성 및 토큰 저장
    → OAuthToken 모델에 저장
    → JWT 토큰 발급 (선택사항)
    ↓
Frontend Redirect
    → /dashboard?token=<jwt>
```

#### Slack OAuth (유사)
- 엔드포인트: `/api/v1/slack/oauth`
- Scope: `channels:read`, `chat:write`, `incoming-webhook`

#### Google OAuth (유사)
- 엔드포인트: `/api/v1/oauth2/google`
- Scope: `openid`, `email`, `profile`

---

### 2. **Scopes 시스템 (`app/services/security.py`)**

**목적**: 엔드포인트별 권한 제어

**Scope 정의**:
- `mcp:execute` - MCP 툴 실행
- `admin:read` - 관리자 읽기
- `admin:write` - 관리자 쓰기
- `deploy:execute` - 배포 실행
- `k8s:read` - K8s 읽기
- `k8s:write` - K8s 쓰기

**사용 방법**:
```python
from app.services.security import require_scopes

@router.post("/deploy", dependencies=[Depends(require_scopes(["deploy:execute"]))])
async def deploy_app():
    # 배포 로직
    pass
```

**테스트 환경**:
```bash
# X-Scopes 헤더로 스코프 전달
curl -X POST http://localhost:8080/api/v1/deploy \
  -H "X-Scopes: deploy:execute,k8s:write"
```

**프로덕션 환경**:
- JWT 토큰에서 스코프 파싱
- OAuth2 스코프 매핑

---

### 3. **감사 로깅 (`app/services/audit.py`)**

**형식**: JSON 구조화 로그

**필드**:
- `timestamp`: ISO 8601 타임스탬프
- `user`: 사용자 ID 또는 이메일
- `ip`: 요청 IP 주소
- `action`: 수행한 작업 (예: "deploy", "restart")
- `resource`: 대상 리소스 (예: "nginx", "deployment/nginx")
- `status`: 성공/실패 (예: "success", "error")
- `details`: 추가 상세 정보 (JSON)

**예시**:
```json
{
  "timestamp": "2025-10-20T10:30:00Z",
  "user": "user@example.com",
  "ip": "192.168.1.100",
  "action": "restart",
  "resource": "deployment/nginx",
  "status": "success",
  "details": {
    "namespace": "default",
    "method": "kubectl rollout restart"
  }
}
```

**저장**:
- **로컬**: SQLite (`AuditLogModel`)
- **프로덕션**: PostgreSQL + 외부 로그 수집 (Splunk, ELK, Sentry)

---

## 📊 모니터링 및 로깅

### 1. **Prometheus 통합**

**메트릭 엔드포인트**: `/metrics`

**수집 메트릭**:
- `http_requests_total` - 총 HTTP 요청 수
- `http_request_duration_seconds` - 요청 지연시간
- `mcp_external_requests_total` - 외부 MCP 요청 수
- `mcp_external_request_latency_seconds` - 외부 MCP 지연시간
- `deployment_count` - 배포 횟수
- `nlp_command_count` - NLP 명령 처리 횟수

**쿼리 API**: `/api/v1/monitoring/query`

**사용 예시**:
```python
# CPU 사용률 조회
query = "rate(container_cpu_usage_seconds_total[5m])"
response = await monitoring_service.query_prometheus(query)
```

---

### 2. **Alertmanager 통합**

**역할**: 알림 라우팅 및 관리

**알림 채널**:
- Slack (주요)
- Email (선택사항)
- PagerDuty (선택사항)

**알림 유형**:
- 배포 성공/실패
- Pod CrashLoopBackOff
- 리소스 임계값 초과 (CPU/메모리)
- 외부 MCP 연결 실패 (Circuit Breaker Open)

**Slack 알림 템플릿**:
```jinja2
🚀 **배포 성공**
- 앱: {{ app_name }}
- 네임스페이스: {{ namespace }}
- 이미지: {{ image }}
- 시간: {{ timestamp }}

[롤백 실행] | [로그 확인]
```

---

### 3. **구조화된 로깅 (`structlog`)**

**설정**: `app/core/logging_config.py`

**로그 레벨**:
- `DEBUG`: 상세한 디버그 정보
- `INFO`: 일반 정보 (기본)
- `WARNING`: 경고
- `ERROR`: 에러
- `CRITICAL`: 치명적 에러

**사용 예시**:
```python
import structlog

logger = structlog.get_logger(__name__)

logger.info("deployment_started",
            app_name="nginx",
            namespace="default",
            image="nginx:1.21")
```

**출력**:
```json
{
  "event": "deployment_started",
  "app_name": "nginx",
  "namespace": "default",
  "image": "nginx:1.21",
  "timestamp": "2025-10-20T10:30:00Z",
  "level": "info"
}
```

---

### 4. **Kubernetes 이벤트 감시 (`app/services/kubernetes_watcher.py`)**

**역할**: K8s 리소스 이벤트 실시간 감지

**감시 대상**:
- Deployment
- Pod
- Service
- Ingress

**이벤트 타입**:
- `ADDED` - 리소스 생성
- `MODIFIED` - 리소스 수정
- `DELETED` - 리소스 삭제

**WebSocket 브로드캐스트**:
```python
# 이벤트 감지 시
watcher = watch.Watch()
for event in watcher.stream(apps_v1.list_namespaced_deployment, namespace="default"):
    event_type = event['type']  # ADDED, MODIFIED, DELETED
    deployment = event['object']

    # WebSocket으로 브로드캐스트
    await websocket_manager.broadcast({
        "type": event_type,
        "resource": "deployment",
        "name": deployment.metadata.name,
        "status": deployment.status.conditions
    })
```

---

## ⚡ 확장성 및 성능

### 1. **비동기 처리 (async/await)**

**FastAPI**: 기본적으로 비동기 처리 지원

**사용 예시**:
```python
@router.post("/deploy")
async def deploy_app(request: DeployRequest):
    # 비동기 K8s API 호출
    result = await k8s_service.deploy_async(request)

    # 비동기 Slack 알림
    await slack_service.send_notification_async(result)

    return result
```

**장점**:
- 높은 동시성 처리
- I/O 바운드 작업 효율화
- 리소스 사용 최소화

---

### 2. **캐싱 전략**

#### Redis 캐싱
- **사용처**: NLP 컨텍스트, 세션 관리
- **TTL**: 컨텍스트 30분, 세션 24시간

```python
# 컨텍스트 캐싱
redis_client.setex(f"context:{user_id}", 1800, json.dumps(context))
```

#### In-Memory 캐싱
- **사용처**: K8s API 클라이언트 싱글톤
- **라이브러리**: `functools.lru_cache`

```python
@lru_cache(maxsize=1)
def get_apps_v1_api():
    return kubernetes.client.AppsV1Api()
```

---

### 3. **Connection Pooling**

#### 데이터베이스
```python
# SQLAlchemy 엔진
engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # 커넥션 풀 크기
    max_overflow=10,     # 최대 오버플로우
    pool_pre_ping=True   # 커넥션 유효성 검사
)
```

#### HTTP 클라이언트
```python
# httpx 또는 aiohttp
async with httpx.AsyncClient() as client:
    response = await client.get(url)
```

---

### 4. **Rate Limiting**

**외부 MCP 연동**:
- **Retry-After 헤더 존중**: API 제공자가 지정한 대기 시간
- **지수 백오프**: 실패 시 대기 시간 exponential 증가
- **Jitter 추가**: 동시 요청 충돌 방지

```python
# app/mcp/external/retry.py
backoff = (2 ** attempt) + random.uniform(0, 1)  # Jitter
await asyncio.sleep(backoff)
```

---

### 5. **Circuit Breaker**

**목적**: 외부 서비스 장애 격리

**상태 전환**:
```
Closed (정상)
    → 실패 5회 이상
    ↓
Open (차단)
    → 60초 대기
    ↓
Half-Open (테스트)
    → 성공 시 Closed
    → 실패 시 다시 Open
```

**코드 위치**: `app/mcp/external/handlers.py`

**메트릭**:
- `circuit_breaker_state` - 현재 상태 (0: Closed, 1: Open, 2: Half-Open)
- `circuit_breaker_transitions_total` - 상태 전환 횟수

---

## 📚 관련 문서

### 아키텍처
- [NLP 실행 아키텍처](./nlp/execution.md) - NLP 시스템 상세
- [NLP 구현 가이드](./nlp/implementation.md) - 명령어 추가 방법
- [튜토리얼 구현](./tutorial/implementation.md) - 인터랙티브 튜토리얼

### 설정 및 배포
- [환경 설정 가이드](./ENVIRONMENT_AND_CONFIG.md) - 환경변수 및 K8s 배포

### 외부 통합
- [Slack 설정 가이드](./integrations/SLACK_SETUP.md) - Slack OAuth 및 알림
- [GitHub App 설정 가이드](./integrations/GITHUB_APP_SETUP.md) - GitHub App 및 웹훅 설정
- [NCP 시나리오 가이드](../troubleshooting/ncp/NCP_SCENARIO_MANUAL_CREATION.md) - NCP SourceDeploy

### 프로젝트 문서
- [프로젝트 README](../../README.md) - 프로젝트 소개
- [CLAUDE.md](../../CLAUDE.md) - Claude Code 전용 가이드

---

## 🔄 업데이트 이력

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| 1.0.0 | 2025-10-20 | 초기 백엔드 아키텍처 문서 작성 |

---

**작성자**: Backend Team
**최종 수정**: 2025-10-20
**다음 리뷰**: 2025-11-20

> **💡 참고**: 이 문서는 시스템 변경사항이 있을 때마다 업데이트됩니다. 새로운 컴포넌트나 아키텍처 변경 시 반드시 문서를 업데이트해주세요!
