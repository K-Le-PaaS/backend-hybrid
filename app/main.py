from datetime import datetime, timezone
import os
from typing import Any, Dict

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi import Response

from .api.v1.system import router as system_router
from .api.v1.deployments import router as deployments_router
from .api.v1.nlp import router as nlp_router
from .api.v1.commands import router as commands_router
from .api.v1.cicd import router as cicd_router
from .api.v1.k8s import router as k8s_router
from .api.v1.monitoring import router as monitoring_router
from .api.v1.tutorial import router as tutorial_router
from .api.v1.websocket import router as websocket_router
from .mcp.external.api import router as mcp_external_router


APP_NAME = "K-Le-PaaS Backend Hybrid"
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")


def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    app = FastAPI(title=APP_NAME, version=APP_VERSION)

    # App state
    app.state.started_at = datetime.now(timezone.utc)

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
    app.include_router(deployments_router, prefix="/api/v1", tags=["deployments"])
    app.include_router(nlp_router, prefix="/api/v1", tags=["nlp"])
    app.include_router(commands_router, prefix="/api/v1", tags=["commands"])
    app.include_router(cicd_router, prefix="/api/v1", tags=["cicd"])
    app.include_router(k8s_router, prefix="/api/v1", tags=["k8s"])
    app.include_router(monitoring_router, prefix="/api/v1", tags=["monitoring"])
    app.include_router(tutorial_router, prefix="/api/v1", tags=["tutorial"])
    app.include_router(websocket_router, prefix="/api/v1", tags=["websocket"])
    app.include_router(mcp_external_router, tags=["mcp-external"])

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # MCP mount (stub or real based on availability)
    _mount_mcp(app)

    return app


def _mount_mcp(app: FastAPI) -> None:
    """Mount MCP server at /mcp if available; otherwise mount a stub.

    This keeps the app runnable even when fastapi_mcp is not installed yet.
    """
    try:
        # Lazy import to avoid hard dependency during initial scaffolding
        from fastapi_mcp import add_mcp_server  # type: ignore
        from .mcp.tools.deploy_app import deploy_application_tool  # noqa: F401
        from .mcp.tools.k8s_resources import (  # noqa: F401
            k8s_create,
            k8s_get,
            k8s_apply,
            k8s_delete,
        )
        from .mcp.tools.rollback import rollback_deployment  # noqa: F401
        from .mcp.tools.monitor import query_metrics  # noqa: F401

        add_mcp_server(app, mount_path="/mcp", name="K-Le-PaaS")
    except Exception:  # noqa: BLE001 - deliberate broad except to provide stub
        from fastapi import APIRouter

        stub = APIRouter()

        @stub.get("/info")
        async def mcp_info() -> Dict[str, Any]:
            return {
                "name": "K-Le-PaaS MCP (stub)",
                "mounted": True,
                "provider": "stub",
                "details": "fastapi_mcp not available; using placeholder until integrated.",
            }

        app.include_router(stub, prefix="/mcp", tags=["mcp-stub"])


app = create_app()


