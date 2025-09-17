from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
import httpx

from app.services.slack_oauth import SlackOAuthService
from app.mcp.external.errors import MCPExternalError


@pytest.mark.asyncio
async def test_exchange_code_success_and_scope_verify():
    mock_http = AsyncMock(spec=httpx.AsyncClient)

    # Mock oauth.v2.access response
    oauth_resp = AsyncMock()
    oauth_resp.status_code = 200
    oauth_resp.aread = AsyncMock(return_value=b'{"ok": true, "access_token": "xoxb-abc", "scope": "chat:write,channels:read"}')
    mock_http.post.return_value = oauth_resp

    svc = SlackOAuthService(
        client_id="cid",
        client_secret="sec",
        http_client=mock_http,
    )

    token, scopes = await svc.exchange_code(code="the-code", redirect_uri="https://app/callback")
    assert token == "xoxb-abc"
    assert "chat:write" in scopes and "channels:read" in scopes

    # Scope verify passes
    await svc.verify_scopes(scopes, required={"chat:write"})


@pytest.mark.asyncio
async def test_exchange_code_handles_rate_limit():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    resp_429 = AsyncMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "1"}
    resp_429.aread = AsyncMock(return_value=b'{"ok": false, "error": "ratelimited"}')
    # first call 429, second call 200
    resp_200 = AsyncMock()
    resp_200.status_code = 200
    resp_200.aread = AsyncMock(return_value=b'{"ok": true, "access_token": "xoxb-xyz", "scope": "chat:write"}')
    mock_http.post.side_effect = [resp_429, resp_200]

    svc = SlackOAuthService("cid", "sec", http_client=mock_http)
    token, scopes = await svc.exchange_code(code="code", redirect_uri="https://cb")
    assert token == "xoxb-xyz"
    assert scopes == {"chat:write"}


@pytest.mark.asyncio
async def test_verify_scopes_fail_raises():
    svc = SlackOAuthService("cid", "sec")
    with pytest.raises(MCPExternalError) as ei:
        await svc.verify_scopes({"chat:write"}, required={"users:read"})
    assert ei.value.code == "forbidden"
    assert "missing scopes" in ei.value.message


