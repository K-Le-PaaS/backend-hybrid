from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
import httpx

from app.mcp.external.providers.slack import SlackMCPClient


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


