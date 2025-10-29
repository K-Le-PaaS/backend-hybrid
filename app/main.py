from datetime import datetime, timezone
import os
from typing import Any, Dict
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi import Response

from .api.v1.system import router as system_router
from .api.v1.dashboard import router as dashboard_router
from .api.v1.deployments import router as deployments_router
from .api.v1.nlp import router as nlp_router
from .api.v1.cicd import router as cicd_router
from .api.v1.k8s import router as k8s_router
from .api.v1.monitoring import router as monitoring_router
from .api.v1.tutorial import router as tutorial_router
from .api.v1.websocket import router as websocket_router
from .websocket.deployment_monitor import handle_deployment_websocket, handle_user_websocket
from .api.v1.slack_auth import router as slack_auth_router
from .api.v1.oauth2 import router as oauth2_router
from .api.v1.auth_verify import router as auth_verify_router
from .api.v1.github_workflows import router as github_workflows_router
from .api.v1.github_oauth import router as github_oauth_router
from .api.v1.projects import router as projects_router
from .api.v1.deployment_histories import router as deployment_histories_router
from .api.v1.rollback import router as rollback_router
from .api.v1.ncp_pipeline_api import router as ncp_pipeline_router
from .mcp.external.api import router as mcp_external_router
from .api.v1.admin_db import router as admin_db_router
from .api.v1.user_url import router as user_url_router
from .core.error_handler import setup_error_handlers
from .core.logging_config import setup_logging
from .database import init_database, init_services, get_db

# 모든 모델을 import하여 테이블이 생성되도록 함
from .models.user_repository import UserRepository
from .models.command_history import CommandHistory
from .models.deployment_history import DeploymentHistory
from .models.audit_log import AuditLogModel
from .models.deployment_url import DeploymentUrl
import structlog


APP_NAME = "K-Le-PaaS Backend Hybrid"
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
ROOT_PATH = os.getenv("KLEPAAS_ROOT_PATH", "")  # e.g., "/api" when served behind reverse proxy

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    # 로깅 설정
    setup_logging(level="INFO", enable_colors=True)
    
    # Explicitly set OpenAPI version so Swagger UI can render without errors
    # Note: FastAPI defaults to OpenAPI 3.1.0, but we set it explicitly to avoid
    # any tooling that requires a concrete version field in the schema output.
    # Also, allow serving under a sub-path (e.g., "/api") when behind an Nginx reverse proxy.
    # When serving behind a reverse proxy at a sub-path (e.g., /api), do NOT set
    # FastAPI root_path here (which is primarily for ASGI upstreams). Instead,
    # expose docs/openapi under the prefixed paths so Swagger UI references stay
    # on the same sub-path and Nginx can route consistently.
    docs_url = f"{ROOT_PATH}/docs" if ROOT_PATH else "/docs"
    openapi_url = f"{ROOT_PATH}/openapi.json" if ROOT_PATH else "/openapi.json"
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        openapi_version="3.1.0",
        root_path=None,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )

    # Harden schema generation: always include a valid OpenAPI version header
    def custom_openapi() -> Dict[str, Any]:
        if app.openapi_schema:
            # Ensure version field remains present and correct
            app.openapi_schema["openapi"] = "3.1.0"
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=f"API documentation for {app.title}",
            routes=app.routes,
        )
        # Explicitly set the spec version key
        openapi_schema["openapi"] = "3.1.0"

        # Add JWT Bearer security scheme for Swagger UI
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Enter your JWT token (obtained from /api/v1/oauth2/google or /api/v1/oauth2/github)"
            }
        }

        # Apply BearerAuth to all paths (optional for each endpoint)
        for path_data in openapi_schema.get("paths", {}).values():
            for operation in path_data.values():
                if isinstance(operation, dict) and "operationId" in operation:
                    # Add optional security to all endpoints
                    operation["security"] = [{"BearerAuth": []}]

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    # App state
    app.state.started_at = datetime.now(timezone.utc)
    
    # 에러 핸들러 설정
    setup_error_handlers(app)

    # CORS (safe default; tighten in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(system_router, prefix="/api/v1", tags=["system"])
    app.include_router(dashboard_router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(deployments_router, prefix="/api/v1", tags=["deployments"])
    app.include_router(nlp_router, prefix="/api/v1", tags=["nlp"])
    app.include_router(cicd_router, prefix="/api/v1", tags=["cicd"])
    app.include_router(k8s_router, prefix="/api/v1", tags=["k8s"])
    app.include_router(monitoring_router, prefix="/api/v1", tags=["monitoring"])
    app.include_router(tutorial_router, prefix="/api/v1", tags=["tutorial"])
    app.include_router(websocket_router, prefix="/api/v1", tags=["websocket"])
    app.include_router(slack_auth_router, prefix="/api/v1", tags=["slack-auth"])
    app.include_router(oauth2_router, prefix="/api/v1", tags=["oauth2"])
    app.include_router(github_oauth_router, prefix="/api/v1", tags=["auth", "github"])
    app.include_router(projects_router, prefix="/api/v1", tags=["projects"])
    app.include_router(deployment_histories_router, prefix="/api/v1", tags=["deployment-histories"])
    app.include_router(rollback_router, prefix="/api/v1", tags=["rollback"])
    app.include_router(auth_verify_router, prefix="/api/v1", tags=["auth"])
    app.include_router(github_workflows_router, prefix="/api/v1", tags=["github"])
    app.include_router(ncp_pipeline_router, prefix="/api/v1/ncp/pipeline", tags=["ncp-pipeline"])
    app.include_router(mcp_external_router, tags=["mcp-external"])
    app.include_router(admin_db_router, prefix="/api/v1", tags=["admin-db"])
    app.include_router(user_url_router, prefix="/api/v1", tags=["user-url"])
    @app.get("/")
    async def root() -> Dict[str, Any]:
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "status": "running",
            "started_at": app.state.started_at.isoformat(),
            "mcp_endpoint": "/mcp/info"
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


    # MCP mount (stub or real based on availability)
    _mount_mcp(app)

    # Initialize database and services
    try:
        # 데이터베이스 초기화
        init_database()
        logger.info("Database initialized successfully")

        # 서비스 초기화
        db_session = next(get_db())
        init_services(db_session)
        logger.info("All services initialized successfully")

    except Exception as e:
        logger.warning("Failed to initialize database or services", error=str(e))

    # Shutdown 이벤트 핸들러 추가
    @app.on_event("shutdown")
    async def shutdown_event():
        """애플리케이션 종료 시 정리 작업"""
        logger.info("Shutting down application...")
        
        # Kubernetes Watcher 중지
        try:
            from .services.kubernetes_watcher import get_kubernetes_watcher
            watcher = get_kubernetes_watcher()
            await watcher.stop_all_watches()
            logger.info("Kubernetes Watcher stopped successfully")
        except Exception as e:
            logger.warning(f"Failed to stop Kubernetes Watcher: {e}")
        
        logger.info("Application shutdown complete")

    return app


def _mount_mcp(app: FastAPI) -> None:
    """Mount MCP server at /mcp using fastmcp."""
    try:
        from fastmcp import FastMCP
        from .mcp.tools.deploy_app import deploy_application_tool
        from .mcp.tools.k8s_resources import (
            k8s_create,
            k8s_get,
            k8s_apply,
            k8s_delete,
        )
        from .mcp.tools.rollback import rollback_deployment
        from .mcp.tools.monitor import query_metrics
        from .mcp.tools.health_monitor_tools import (
            check_system_health,
            check_component_health,
            get_health_metrics,
            send_health_alert,
            send_circuit_breaker_alert,
        )
        from .mcp.tools.git_deployment_tools import (
            deploy_application_mcp,
            rollback_deployment_mcp,
            get_deployment_status_mcp,
            git_workflow_automation,
            create_release_tag,
            list_git_agents,
        )

        # Create FastMCP server instance
        mcp_server = FastMCP(
            name="K-Le-PaaS",
            version="0.1.0"
        )
        
        # Register tools using the @mcp_server.tool decorator
        @mcp_server.tool
        def deploy_application_tool_mcp(app_name: str, environment: str, image: str, replicas: int = 2) -> str:
            return deploy_application_tool(app_name, environment, image, replicas)
        
        @mcp_server.tool
        def k8s_create_mcp(kind: str, name: str, namespace: str = "default", manifest: dict = None) -> str:
            return k8s_create(kind, name, namespace, manifest)
        
        @mcp_server.tool
        def k8s_get_mcp(kind: str, name: str = None, namespace: str = "default") -> str:
            return k8s_get(kind, name, namespace)
        
        @mcp_server.tool
        def k8s_apply_mcp(kind: str, name: str, namespace: str = "default", manifest: dict = None) -> str:
            return k8s_apply(kind, name, namespace, manifest)
        
        @mcp_server.tool
        def k8s_delete_mcp(kind: str, name: str, namespace: str = "default") -> str:
            return k8s_delete(kind, name, namespace)
        
        @mcp_server.tool
        def rollback_deployment_mcp(deployment_name: str, namespace: str = "default") -> str:
            return rollback_deployment(deployment_name, namespace)
        
        @mcp_server.tool
        def query_metrics_mcp(query: str) -> str:
            return query_metrics(query)
        
        @mcp_server.tool
        def check_system_health_mcp() -> str:
            return check_system_health()
        
        @mcp_server.tool
        def check_component_health_mcp(component: str) -> str:
            return check_component_health(component)
        
        @mcp_server.tool
        def get_health_metrics_mcp() -> str:
            return get_health_metrics()
        
        @mcp_server.tool
        def send_health_alert_mcp(alert_type: str, message: str) -> str:
            return send_health_alert(alert_type, message)
        
        @mcp_server.tool
        def send_circuit_breaker_alert_mcp(component: str, status: str) -> str:
            return send_circuit_breaker_alert(component, status)
        
        @mcp_server.tool
        def deploy_application_mcp_tool(app_name: str, environment: str, image: str) -> str:
            return deploy_application_mcp(app_name, environment, image)
        
        @mcp_server.tool
        def rollback_deployment_mcp_tool(deployment_name: str, namespace: str = "default") -> str:
            return rollback_deployment_mcp(deployment_name, namespace)
        
        @mcp_server.tool
        def get_deployment_status_mcp_tool(deployment_name: str, namespace: str = "default") -> str:
            return get_deployment_status_mcp(deployment_name, namespace)
        
        @mcp_server.tool
        def git_workflow_automation_mcp(repo_url: str, branch: str = "main") -> str:
            return git_workflow_automation(repo_url, branch)
        
        @mcp_server.tool
        def create_release_tag_mcp(tag: str, message: str = None) -> str:
            return create_release_tag(tag, message)
        
        @mcp_server.tool
        def list_git_agents_mcp() -> str:
            return list_git_agents()

        # Add REST API endpoints for MCP first
        @app.get("/mcp/info")
        async def mcp_info() -> Dict[str, Any]:
            """Get MCP server information."""
            try:
                tools = await mcp_server.get_tools()
                return {
                    "name": "K-Le-PaaS MCP",
                    "version": "0.1.0",
                    "mounted": True,
                    "provider": "fastmcp",
                    "details": "MCP server integrated with FastMCP",
                    "tools_available": list(tools.keys()),
                    "tools_count": len(tools)
                }
            except Exception as e:
                return {
                    "name": "K-Le-PaaS MCP",
                    "version": "0.1.0",
                    "mounted": True,
                    "provider": "fastmcp",
                    "details": f"MCP server integrated with FastMCP (error: {str(e)})",
                    "tools_available": [],
                    "tools_count": 0
                }
        
        @app.get("/mcp/tools")
        async def mcp_tools() -> Dict[str, Any]:
            """Get available MCP tools."""
            try:
                tools = await mcp_server.get_tools()
                tools_list = []
                for tool_name, tool_info in tools.items():
                    tools_list.append({
                        "name": tool_name,
                        "description": tool_info.description or f"MCP tool: {tool_name}",
                        "parameters": tool_info.parameters if hasattr(tool_info, 'parameters') else {}
                    })
                return {
                    "tools": tools_list,
                    "count": len(tools_list)
                }
            except Exception as e:
                return {
                    "tools": [],
                    "count": 0,
                    "error": str(e)
                }
        
        # Mount MCP server at /mcp/stream with explicit path and lifespan
        mcp_app = mcp_server.http_app(path="/")
        app.mount("/mcp/stream", mcp_app)
        
        # Set MCP lifespan on the main app
        if hasattr(mcp_app, 'lifespan'):
            app.router.lifespan_context = mcp_app.lifespan
        
    except Exception as e:  # noqa: BLE001
        # Fallback to stub mode if MCP integration fails
        from fastapi import APIRouter

        stub = APIRouter()
        error_msg = str(e)

        @stub.get("/info")
        async def mcp_info() -> Dict[str, Any]:
            return {
                "name": "K-Le-PaaS MCP (stub)",
                "mounted": True,
                "provider": "stub",
                "details": f"MCP integration failed, using stub mode. Error: {error_msg}",
                "tools_available": [
                    "deploy_application_tool",
                    "k8s_create", "k8s_get", "k8s_apply", "k8s_delete",
                    "rollback_deployment",
                    "query_metrics",
                    "check_system_health", "check_component_health",
                    "get_health_metrics", "send_health_alert",
                    "send_circuit_breaker_alert",
                    "deploy_application_mcp", "rollback_deployment_mcp",
                    "get_deployment_status_mcp", "git_workflow_automation",
                    "create_release_tag", "list_git_agents"
                ]
            }

        @stub.get("/tools")
        async def list_tools() -> Dict[str, Any]:
            return {
                "tools": [
                    {
                        "name": "deploy_application_tool",
                        "description": "Deploy application to Kubernetes cluster"
                    },
                    {
                        "name": "k8s_create",
                        "description": "Create Kubernetes resources"
                    },
                    {
                        "name": "k8s_get",
                        "description": "Get Kubernetes resources"
                    },
                    {
                        "name": "k8s_apply",
                        "description": "Apply Kubernetes resources"
                    },
                    {
                        "name": "k8s_delete",
                        "description": "Delete Kubernetes resources"
                    },
                    {
                        "name": "rollback_deployment",
                        "description": "Rollback deployment to previous version"
                    },
                    {
                        "name": "query_metrics",
                        "description": "Query Prometheus metrics"
                    }
                ]
            }

        app.include_router(stub, prefix="/mcp", tags=["mcp-stub"])


app = create_app()


