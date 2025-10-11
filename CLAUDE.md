# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

K-Le-PaaS Backend Hybrid is a FastAPI-based PaaS backend that integrates:
- **REST API**: Standard API endpoints under `/api/v1`
- **MCP Server**: Model Context Protocol server at `/mcp` using FastMCP
- **Advanced NLP**: Multi-model AI system (Claude, GPT-4, Gemini) for natural language command interpretation
- **Kubernetes Operations**: K8s deployment, monitoring, and management
- **CI/CD Integration**: GitHub webhook handlers for automated deployments
- **External MCP Connectors**: Standardized interfaces for GitHub, Slack, and other external MCP services

## Build and Development Commands

### Local Development
```bash
# Setup virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --port 8080

# Run tests
python -m pytest tests/ -v

# Run Advanced NLP integration tests
python -m pytest tests/test_advanced_nlp_integration.py -v

# Run Advanced NLP development test script
python scripts/test_advanced_nlp.py
```

### Docker
```bash
# Build image
docker build -t klepaas-backend:dev .

# Run container
docker run --rm -p 8080:8080 klepaas-backend:dev
```

## Architecture

### Core Application Structure

**app/main.py**: Application entry point that creates the FastAPI app, registers all routers, initializes database, and mounts the MCP server at `/mcp/stream` (or falls back to stub mode if FastMCP unavailable).

**app/core/config.py**: Centralized configuration using Pydantic Settings with `KLEPAAS_` prefix for environment variables. Contains settings for:
- AI models (Claude, OpenAI, Gemini)
- Cloud providers (GCP, NCP)
- GitHub/Slack OAuth
- Advanced NLP configuration
- Database and Redis URLs

**app/database.py**: Database initialization and session management. Uses SQLAlchemy with SQLite (default) or PostgreSQL. Creates all tables on startup and initializes services (audit logger, deployment history, kubernetes watcher).

### API Layers

**app/api/v1/**: REST API endpoints organized by domain:
- `system.py`: Health, version, metrics endpoints
- `deployments.py`: Deployment management
- `nlp.py`: Natural language processing endpoints
- `commands.py`: Command history
- `cicd.py`: CI/CD webhook handlers (GitHub push/release events)
- `github_workflows.py`: GitHub workflow management
- `github_oauth.py`: GitHub OAuth flow
- `projects.py`: User project integrations
- `oauth2.py`: OAuth2 providers (Google, GitHub)
- `slack_auth.py`: Slack OAuth
- `k8s.py`: Kubernetes operations
- `monitoring.py`: Monitoring and metrics
- `websocket.py`: WebSocket for real-time updates

### Services Layer

**app/services/**: Business logic and external integrations:
- `deployment.py`, `deployments.py`, `deployments_enhanced.py`: Kubernetes deployment logic
- `k8s_client.py`: Kubernetes API client wrapper
- `nlp.py`, `nlp_command_processor.py`: Natural language processing
- `github_workflow.py`, `github_app.py`: GitHub integration
- `slack_*.py`: Slack integration (OAuth, notifications)
- `cicd.py`: CI/CD pipeline logic
- `audit_logger.py`, `audit.py`: Audit logging (JSON format with time/user/IP/action/resource/status)
- `alerting.py`: Alertmanager integration
- `monitoring.py`: Prometheus metrics queries
- `kubernetes_watcher.py`: K8s resource event watching
- `ncp_pipeline.py`: NCP SourceDeploy integration
- `command_history.py`, `deployment_history.py`: History tracking
- `user_repository.py`, `user_project_integration.py`: User data management

### Advanced NLP System

The Advanced NLP system is a core feature integrating multiple AI models for intelligent command interpretation.

**app/llm/**: AI model integration:
- `gemini.py`: Primary entry point using Gemini, delegates to AdvancedNLPService
- `advanced_nlp_service.py`: Orchestrates multi-model processing, context management, command interpretation, and learning
- `multi_model_processor.py`: Parallel processing across Claude, GPT-4, Gemini
- `context_manager.py`: Redis-based context and conversation history management
- `smart_command_interpreter.py`: Ambiguity detection, auto-correction suggestions
- `learning_processor.py`: User feedback learning and pattern recognition
- `interfaces.py`: Shared interfaces and types

**Key capabilities**:
- Multi-model processing with confidence-based selection
- Context-aware interpretation using conversation history
- Ambiguity detection and correction suggestions
- User feedback learning for personalized responses
- Model performance tracking

**Configuration**: See `app/core/config.py` for Advanced NLP settings (Redis, model API keys, thresholds, learning rates). Default enabled with `KLEPAAS_ADVANCED_NLP_ENABLED=true`.

**Documentation**: See `docs/ADVANCED_NLP.md` for detailed usage, API reference, and troubleshooting.

### MCP Integration

**FastMCP Server**: Mounted at `/mcp/stream` in `app/main.py`. All MCP tools are registered using the `@mcp_server.tool` decorator pattern. REST endpoints at `/mcp/info` and `/mcp/tools` provide metadata.

**app/mcp/tools/**: MCP tool implementations:
- `deploy_app.py`: Application deployment
- `k8s_resources.py`: K8s CRUD operations (create, get, apply, delete)
- `rollback.py`: Deployment rollback
- `monitor.py`: Prometheus metrics queries
- `health_monitor_tools.py`: Health checks and circuit breaker alerts
- `git_deployment_tools.py`: Git-based deployment automation (MCP native Git agents for GCP/NCP)
- `advanced_nlp.py`: NLP command processing

**app/mcp/external/**: External MCP server connectors with standardized interfaces:
- `interfaces.py`: Common `ExternalMCPClient` interface (connect, list_tools, call_tool, health, close)
- `errors.py`: Standardized error schema (`MCPExternalError` with codes: unauthorized, forbidden, not_found, rate_limited, timeout, unavailable, bad_request, conflict, internal)
- `retry.py`: Exponential backoff with jitter, respects server `retry_after`
- `metrics.py`: Prometheus metrics (`mcp_external_requests_total`, `mcp_external_request_latency_seconds`)
- `handlers.py`: Circuit breaker pattern for external MCP calls
- `registry.py`: MCP provider registry for managing multiple external MCP servers
- `message_converter.py`: Message format conversion between internal and external MCP protocols
- `api.py`: REST API router for external MCP operations (`POST /mcp/external/providers`, `POST /mcp/external/tools/call`, etc.)
- `providers/github.py`: GitHub MCP client with App or token authentication
- `providers/slack.py`: Slack MCP client

### Models and Database

**app/models/**: SQLAlchemy ORM models:
- `base.py`: Declarative base
- `user_repository.py`: User repository connections
- `command_history.py`: NLP command history
- `deployment_history.py`: Deployment audit trail
- `audit_log.py`: General audit logs
- `oauth_token.py`: OAuth token storage
- `user_project_integration.py`: User-project-provider integrations

## Environment Variables

Critical environment variables (prefix `KLEPAAS_`):

### AI Models
- `CLAUDE_API_KEY`: Anthropic Claude API key
- `OPENAI_API_KEY`: OpenAI API key
- `GEMINI_API_KEY`: Google Gemini API key
- `ADVANCED_NLP_ENABLED`: Enable advanced NLP (default: true)
- `REDIS_URL`: Redis connection for NLP context (default: redis://localhost:6379)

### Cloud Providers
- `GCP_PROJECT`, `GCP_LOCATION`, `GEMINI_MODEL`: GCP/Gemini configuration
- `NCP_ACCESS_KEY`, `NCP_SECRET_KEY`, `NCP_API_GW`: NCP authentication
- `NCP_SOURCECOMMIT_ENDPOINT`, `NCP_SOURCEDEPLOY_ENDPOINT`: NCP service endpoints
- `NCP_NKS_CLUSTER_ID`: NKS cluster ID for deployments

### GitHub
- `GITHUB_WEBHOOK_SECRET`: HMAC secret for webhook validation
- `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`: GitHub App credentials
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`: GitHub OAuth
- `DEPLOYMENT_CONFIG_REPO`, `DEPLOYMENT_CONFIG_TOKEN`: Deployment config repo access

### Slack
- `SLACK_WEBHOOK_URL`: Slack webhook for notifications
- `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_REDIRECT_URI`: Slack OAuth
- `SLACK_ALERT_CHANNEL_DEFAULT`, `SLACK_ALERT_CHANNEL_RATE_LIMITED`, `SLACK_ALERT_CHANNEL_UNAUTHORIZED`: Alert routing
- `SLACK_ALERT_TEMPLATE_ERROR`, `SLACK_ALERT_TEMPLATE_HEALTH_DOWN`: Jinja2 templates for alerts

### Monitoring
- `PROMETHEUS_BASE_URL`: Prometheus server
- `ALERTMANAGER_URL`, `ALERTMANAGER_WEBHOOK_URL`: Alertmanager integration
- `DATABASE_URL`: PostgreSQL or SQLite connection string

### Kubernetes
- `ENABLE_K8S_DEPLOY`: Enable K8s deployments (default: false)
- `K8S_STAGING_NAMESPACE`: Namespace for staging (default: staging)
- `K8S_IMAGE_PULL_SECRET`: Image pull secret name (default: ncp-cr)

## CI/CD Flow

**GitHub Workflow** (`.github/workflows/ci.yml`):
1. Triggered on push to `main` or `workflow_dispatch`
2. Builds Docker image and pushes to Docker Hub with tags: `<sha>` and `latest`
3. Checks out `K-Le-PaaS/deployment-config` repository
4. Updates `charts/common-chart/values/backend-hybrid-values.yaml` with new image tag
5. Commits and pushes changes to deployment-config repo

**Backend Webhook Handler** (`app/api/v1/cicd.py`):
- Receives GitHub webhooks at `/api/v1/cicd/webhook`
- Validates HMAC signature using `GITHUB_WEBHOOK_SECRET`
- Handles `push` (staging) and `release` (production) events
- Optionally triggers K8s deployments if `ENABLE_K8S_DEPLOY=true`
- Records deployment history and sends Slack notifications

## Security

**Scopes System** (`app/services/security.py`):
- Endpoints require scopes like `mcp:execute`, `admin:read`, etc.
- Test environment: Use `X-Scopes` header
- Production: Parse scopes from JWT/OAuth tokens

**Audit Logging** (`app/services/audit.py`):
- JSON structured logs (timestamp, user, IP, action, resource, status, details)
- Centralization recommended (Splunk/Sentry/ELK)

**Circuit Breaker** (`app/mcp/external/handlers.py`):
- Protects external MCP calls with configurable failure threshold and reset timeout
- States: closed → open (on failures) → half-open (after timeout) → closed (on success)

## Common Patterns

### Adding a New API Endpoint
1. Create or edit router in `app/api/v1/`
2. Use dependency injection for services (e.g., `db: Session = Depends(get_db)`)
3. Apply security scopes if needed: `@router.get("/endpoint", dependencies=[Depends(require_scopes(["scope:name"]))])`
4. Register router in `app/main.py`: `app.include_router(router, prefix="/api/v1", tags=["tag"])`

### Adding a New MCP Tool
1. Implement tool function in `app/mcp/tools/`
2. Register in `app/main.py` using `@mcp_server.tool` decorator
3. Tool signature must have type hints and docstring for auto-documentation

### Adding a New Service
1. Create service module in `app/services/`
2. Use dependency injection for database, config, external clients
3. Initialize in `app/database.py` `init_services()` if singleton required
4. Import in relevant API routers

### Working with Advanced NLP
1. Import `GeminiClient` from `app.llm.gemini` for standard usage
2. Use `AdvancedNLPService` directly from `app.llm.advanced_nlp_service` for advanced features
3. Ensure Redis is running and configured via `KLEPAAS_REDIS_URL`
4. Record user feedback using `service.record_feedback()` for continuous learning
5. Query user insights with `service.get_user_insights(user_id)`

## Testing

- Use `pytest` for all tests: `python -m pytest tests/ -v`
- Advanced NLP has dedicated test suite: `tests/test_advanced_nlp_integration.py`
- Development test script for interactive NLP testing: `scripts/test_advanced_nlp.py`
- Mock external services (Redis, K8s, GitHub) in tests
- Integration tests should verify end-to-end flows (webhook → service → K8s)

## Troubleshooting

**Slack alerts not received**: Check `SLACK_WEBHOOK_URL`, channel permissions, and template rendering errors in logs.

**403 insufficient_scope errors**: Verify request token scopes match endpoint requirements (check `X-Scopes` header or JWT claims).

**MCP connection failures**: Check circuit breaker state (may be open due to repeated failures), verify external MCP server health.

**Advanced NLP not working**: Ensure `KLEPAAS_ADVANCED_NLP_ENABLED=true`, verify Redis connection, check AI model API keys are valid.

**Database errors on startup**: Check `DATABASE_URL` format, ensure file permissions for SQLite, or verify PostgreSQL connection.

## Notes

- MCP mount gracefully falls back to stub mode if FastMCP is unavailable
- CORS is wide open (`allow_origins=["*"]`) - tighten in production
- SQLite is default database - use PostgreSQL for production
- Advanced NLP system requires Redis for full functionality
- External MCP connectors use standardized error handling and retry logic
- Circuit breaker protects against cascading failures in external integrations
