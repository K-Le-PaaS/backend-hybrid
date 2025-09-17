# K-Le-PaaS Backend Hybrid

FastAPI + MCP hybrid backend service. This app exposes REST endpoints under `/api/v1` and mounts an MCP server or a stub at `/mcp`.

### External MCP Connectors (Architecture)

외부 MCP 서버(GitHub, Claude, OpenAI) 연동을 위한 공통 추상화를 추가했습니다.

- 공통 인터페이스: `app/mcp/external/interfaces.py`
  - `ExternalMCPClient`: `connect()`, `list_tools()`, `call_tool()`, `health()`, `close()`
- 표준 에러 스키마: `app/mcp/external/errors.py`
  - `MCPExternalError(code, message, retry_after_seconds, details)`
  - 코드: `unauthorized|forbidden|not_found|rate_limited|timeout|unavailable|bad_request|conflict|internal`
- 재시도 정책: `app/mcp/external/retry.py`
  - 지수 백오프 + 지터, 서버 `retry_after` 존중
- 메트릭: `app/mcp/external/metrics.py`
  - `mcp_external_requests_total{provider,operation,result}`
  - `mcp_external_request_latency_seconds{provider,operation}` (buckets: p95 관측 용)

다음 단계로 GitHub/Claude/OpenAI 커넥터를 이 추상화에 맞춰 추가합니다.

### GitHub MCP 커넥터 사용 예제

```python
from app.mcp.external.providers.github import GitHubMCPClient

# GitHub App 인증으로 초기화
client = GitHubMCPClient(
    base_url="https://github-mcp.example.com",
    app_id="123456",
    private_key="-----BEGIN PRIVATE KEY-----\n...",
    installation_id="789012"
)

# 또는 토큰 제공자로 초기화
client = GitHubMCPClient(
    base_url="https://github-mcp.example.com",
    token_provider=lambda: "your_access_token"
)

# 사용
await client.connect()
tools = await client.list_tools()
result = await client.call_tool("gh.clone", {"repo": "owner/repo"})
health = await client.health()
await client.close()
```

### MCP 메시지 변환 및 핸들러

외부 MCP 서버와의 통신을 위한 메시지 변환 및 핸들러 시스템을 구현했습니다.

```python
from app.mcp.external.registry import mcp_registry, MCPProviderConfig

# GitHub MCP 프로바이더 설정
config = MCPProviderConfig(
    name="github",
    provider_type="github",
    base_url="https://github-mcp.example.com",
    config={
        "app_id": "123456",
        "private_key": "-----BEGIN PRIVATE KEY-----\n...",
        "installation_id": "789012"
    }
)

# 프로바이더 등록 및 초기화
mcp_registry.add_provider_config(config)
await mcp_registry.initialize_provider("github")

# 도구 호출
result = await mcp_registry.call_tool("github", "gh.clone", {"repo": "owner/repo"})

# 도구 목록 조회
tools = await mcp_registry.list_tools("github")

# 헬스 체크
health = await mcp_registry.health_check("github")
```

**API 엔드포인트:**
- `POST /mcp/external/providers` - 프로바이더 설정 추가
- `GET /mcp/external/providers` - 프로바이더 목록 조회
- `POST /mcp/external/tools/call` - 도구 호출
- `GET /mcp/external/tools/{provider}` - 도구 목록 조회
- `GET /mcp/external/health/{provider}` - 헬스 체크

## Local Run

```bash
# from backend-hybrid/
python -m venv .venv && . .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

- Health: `GET http://localhost:8080/api/v1/health`
- Version: `GET http://localhost:8080/api/v1/version`
- MCP stub: `GET http://localhost:8080/mcp/info`

## Docker

```bash
# from backend-hybrid/
docker build -t klepaas-backend:dev .
docker run --rm -p 8080:8080 klepaas-backend:dev
```

## Notes
- MCP mount falls back to a stub if `fastapi_mcp` is not available.
- Tighten CORS in production.

## Branch protection & required checks (Guide)
- Protect `main`: require PR reviews (>=1), block direct pushes, require status checks to pass
- Required checks: `PR CI` (ruff + build), optional `Dependency Review`
- Releases/production: use GitHub Environments with Required reviewers for `production`

## CI/CD Secrets & Variables
- Required Secrets (Repo → Settings → Secrets and variables → Actions)
  - `KLEPAAS_WEBHOOK_URL`: Backend CICD webhook endpoint (`/api/v1/cicd/webhook`)
  - `KLEPAAS_WEBHOOK_SECRET`: HMAC secret for `X-Hub-Signature-256`
  - (Optional) `SLACK_WEBHOOK_URL`: Slack 알림용 Webhook URL
- GitHub App Secrets (Recommended for enhanced security)
  - `KLEPAAS_GITHUB_APP_ID`: GitHub App ID
  - `KLEPAAS_GITHUB_APP_PRIVATE_KEY`: GitHub App private key (PEM format)
  - `KLEPAAS_GITHUB_APP_WEBHOOK_SECRET`: GitHub App webhook secret
- Recommended Permissions in workflows
  - `permissions: { contents: read, packages: write, id-token: write }` (GHCR 및 OIDC 대응)
- Image naming
  - Staging: `ghcr.io/<owner>/<repo>-backend:latest-staging` + `sha`
  - Production: `ghcr.io/<owner>/<repo>-backend:latest-prod` + SemVer tags (`vX.Y.Z`, `vX.Y`, `vX`)

## Image Tagging Policy
- PR: ephemeral build only (no push) or `pr-<number>` when needed
- Main: `latest-staging`, branch ref tag (e.g., `main`), and commit `sha`
- Release: `latest-prod`, plus SemVer fan-out: `vX.Y.Z`, `vX.Y`, `vX`

## E2E (workflow_dispatch)
- Workflow: `E2E CI/CD Webhook Verification`
- 전제: `KLEPAAS_WEBHOOK_SECRET` 시크릿 설정 필요
- 수행: GitHub Actions에서 수동 실행 → 백엔드 기동 → `/health`·`/version` 체크 → 서명된 `push`/`release` 웹훅을 `/api/v1/cicd/webhook`에 전송하여 파이프라인 엔드포인트 동작 검증
