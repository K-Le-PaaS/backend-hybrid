import asyncio
import pytest

from app.mcp.external.handlers import MCPHandler, MCPHandlerConfig
from app.mcp.external.interfaces import ExternalMCPClient
from app.mcp.external.errors import MCPExternalError


class FailingClient(ExternalMCPClient):
    async def connect(self):
        return None

    async def close(self):
        return None

    async def list_tools(self):
        raise MCPExternalError(code="upstream_unavailable", message="fail")

    async def call_tool(self, tool_name, arguments):
        raise MCPExternalError(code="upstream_unavailable", message="fail")

    async def health(self):
        raise MCPExternalError(code="upstream_unavailable", message="fail")


class SuccessClient(ExternalMCPClient):
    async def connect(self):
        return None

    async def close(self):
        return None

    async def list_tools(self):
        return []

    async def call_tool(self, tool_name, arguments):
        return {"ok": True}

    async def health(self):
        return {"ok": True}


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold(monkeypatch):
    cfg = MCPHandlerConfig(breaker_failure_threshold=2, breaker_reset_timeout_sec=60)
    handler = MCPHandler(FailingClient(), cfg)
    await handler.initialize()
    # first failure
    with pytest.raises(MCPExternalError) as e1:
        await handler.call_tool("x", {})
    assert e1.value.code == "upstream_unavailable"
    # second failure triggers open
    with pytest.raises(MCPExternalError) as e2:
        await handler.call_tool("x", {})
    assert e2.value.code == "upstream_unavailable"
    # now circuit open blocks immediately
    with pytest.raises(MCPExternalError) as e3:
        await handler.call_tool("x", {})
    assert e3.value.code == "circuit_open"


@pytest.mark.asyncio
async def test_circuit_resets_after_timeout(monkeypatch):
    cfg = MCPHandlerConfig(breaker_failure_threshold=1, breaker_reset_timeout_sec=0.1)
    handler = MCPHandler(FailingClient(), cfg)
    await handler.initialize()
    # trip breaker
    with pytest.raises(MCPExternalError):
        await handler.call_tool("x", {})
    with pytest.raises(MCPExternalError) as e:
        await handler.call_tool("x", {})
    assert e.value.code == "circuit_open"
    # wait for reset timeout
    await asyncio.sleep(0.12)
    # half-open trial still fails -> stays open
    with pytest.raises(MCPExternalError):
        await handler.call_tool("x", {})


@pytest.mark.asyncio
async def test_circuit_closes_on_success_after_timeout(monkeypatch):
    cfg = MCPHandlerConfig(breaker_failure_threshold=1, breaker_reset_timeout_sec=0.05)
    failing = FailingClient()
    handler = MCPHandler(failing, cfg)
    await handler.initialize()
    with pytest.raises(MCPExternalError):
        await handler.call_tool("x", {})
    with pytest.raises(MCPExternalError):
        await handler.call_tool("x", {})
    # swap client to success
    handler.external_client = SuccessClient()
    handler.request_handler.external_client = handler.external_client
    await asyncio.sleep(0.06)
    # trial call succeeds -> breaker closes
    res = await handler.call_tool("y", {})
    assert res["ok"] is True
    # confirm closed
    res2 = await handler.call_tool("y", {})
    assert res2["ok"] is True




