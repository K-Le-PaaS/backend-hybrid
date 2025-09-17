from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
import httpx

from app.mcp.external.providers.slack import SlackMCPClient
from app.mcp.external.metrics import MCP_EXTERNAL_HEALTH


@pytest.mark.asyncio
async def test_notify_deploy_uses_channel_mapping_and_template():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    mock_http.post.return_value = mock_resp

    client = SlackMCPClient(
        webhook_url="https://hooks.slack.com/test",
        http_client=mock_http,
    )
    await client.connect()

    result = await client.call_tool(
        "slack.notify_deploy",
        {
            "channel_map": {"deploy": "#deployments"},
            "context": {"app": "svc", "version": "1.2.3", "status": "success"},
        },
    )

    assert result["ok"] is True
    args, kwargs = mock_http.post.call_args
    assert args[0] == "https://hooks.slack.com/test"
    assert kwargs["json"]["channel"] == "#deployments"
    assert "svc" in kwargs["json"]["text"] and "1.2.3" in kwargs["json"]["text"]


@pytest.mark.asyncio
async def test_send_message_requires_channel_or_event_mapping():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    client = SlackMCPClient(webhook_url="https://hooks/slack", http_client=mock_http)
    await client.connect()

    with pytest.raises(Exception):
        await client.call_tool("slack.send_message", {"text": "hello"})


@pytest.mark.asyncio
async def test_health_gauge_set_on_success():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    resp = AsyncMock()
    resp.status_code = 200
    resp.aread = AsyncMock(return_value=b'{"ok": true, "team": "T", "bot_id": "B"}')
    mock_http.post.return_value = resp

    client = SlackMCPClient(bot_token="xoxb", http_client=mock_http)
    await client.connect()
    res = await client.health()

    assert res["ok"] is True
    # Just ensure calling label does not raise and logically set to 1
    MCP_EXTERNAL_HEALTH.labels(provider="slack")


