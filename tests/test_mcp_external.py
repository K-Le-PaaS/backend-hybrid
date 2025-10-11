from __future__ import annotations

import json
import pytest
import httpx

from app.mcp.external.providers.github import GitHubMCPClient
from app.mcp.external.handlers import MCPHandler


@pytest.mark.asyncio
async def test_github_mcp_list_tools_and_call_and_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp/tools") and request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "tools": [
                        {"name": "gh.clone", "description": "Clone repository", "inputSchema": {"type": "object"}}
                    ]
                },
            )
        if "/mcp/tools/gh.clone" in request.url.path and request.method == "POST":
            body = json.loads(request.content or b"{}")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"ok": True, "content": {"received": body}},
            )
        if request.url.path.endswith("/mcp/health") and request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"ok": True, "status": "healthy"},
            )
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://mcp.example") as client:
        gh = GitHubMCPClient(base_url="https://mcp.example", http_client=client)
        handler_wrap = MCPHandler(gh)

        await handler_wrap.initialize()

        tools = await handler_wrap.list_tools()
        assert tools and tools[0]["name"] == "gh.clone"

        res = await handler_wrap.call_tool("gh.clone", {"repo": "owner/repo"})
        assert res["ok"] is True
        assert res["content"]["received"]["arguments"]["repo"] == "owner/repo"

        health = await handler_wrap.health_check()
        assert health["ok"] is True
        assert health["connected"] is True

        await handler_wrap.cleanup()



