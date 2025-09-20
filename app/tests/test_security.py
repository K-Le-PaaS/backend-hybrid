import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI, APIRouter, Depends
from app.services.security import require_scopes


def _app():
    app = FastAPI()
    router = APIRouter()

    @router.post("/commands/execute")
    async def exec_cmd(_=Depends(require_scopes(["mcp:execute"]))):
        return {"ok": True}

    app.include_router(router, prefix="/api/v1")
    return app


def test_require_scopes_forbidden():
    client = TestClient(_app())
    # No scopes header -> forbidden
    resp = client.post("/api/v1/commands/execute")
    assert resp.status_code == 403
    assert "insufficient_scope" in resp.json()["detail"]


def test_require_scopes_allowed():
    client = TestClient(_app())
    resp = client.post(
        "/api/v1/commands/execute",
        headers={"X-Scopes": "mcp:execute, other"},
    )
    assert resp.status_code == 200


