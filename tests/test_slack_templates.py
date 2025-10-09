from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

import httpx

from app.mcp.external.providers.slack import SlackMCPClient


@pytest.mark.asyncio
async def test_send_message_with_template_rendering():
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
        "slack.send_message",
        {
            "channel": "#deploy",
            "template": "{{ status|upper }}: {{ app }} {{ version }}",
            "context": {"status": "deployed", "app": "svc", "version": "1.2.3"},
        },
    )

    assert result["ok"] is True
    # Verify rendered text used in payload
    args, kwargs = mock_http.post.call_args
    assert args[0] == "https://hooks.slack.com/test"
    assert kwargs["json"]["text"] == "DEPLOYED: svc 1.2.3"
    assert kwargs["json"]["channel"] == "#deploy"


