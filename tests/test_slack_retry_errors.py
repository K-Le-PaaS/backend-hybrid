from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
import httpx

from app.mcp.external.providers.slack import SlackMCPClient
from app.mcp.external.errors import MCPExternalError


@pytest.mark.asyncio
async def test_rate_limit_retry_with_retry_after_header():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    
    # First call: 429 with Retry-After
    resp_429 = AsyncMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "2"}
    resp_429.text = "rate limited"
    
    # Second call: success
    resp_200 = AsyncMock()
    resp_200.status_code = 200
    resp_200.aread = AsyncMock(return_value=b'{"ok": true, "ts": "123", "channel": "#test", "message": {}}')
    
    mock_http.post.side_effect = [resp_429, resp_200]

    client = SlackMCPClient(
        bot_token="xoxb-test",
        http_client=mock_http
    )
    await client.connect()

    result = await client.call_tool(
        "slack.send_message",
        {"channel": "#test", "text": "hello"}
    )

    assert result["ok"] is True
    assert mock_http.post.call_count == 2  # retry happened


@pytest.mark.asyncio
async def test_unauthorized_error_not_retried():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    
    resp_401 = AsyncMock()
    resp_401.status_code = 401
    resp_401.text = "unauthorized"
    mock_http.post.return_value = resp_401

    client = SlackMCPClient(
        bot_token="xoxb-invalid",
        http_client=mock_http
    )
    await client.connect()

    with pytest.raises(MCPExternalError) as exc_info:
        await client.call_tool(
            "slack.send_message",
            {"channel": "#test", "text": "hello"}
        )
    
    assert exc_info.value.code == "unauthorized"
    assert mock_http.post.call_count == 1  # no retry for 401


@pytest.mark.asyncio
async def test_webhook_error_handling():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    
    resp_400 = AsyncMock()
    resp_400.status_code = 400
    resp_400.text = "bad request"
    mock_http.post.return_value = resp_400

    client = SlackMCPClient(
        webhook_url="https://hooks.slack.com/invalid",
        http_client=mock_http
    )
    await client.connect()

    with pytest.raises(MCPExternalError) as exc_info:
        await client.call_tool(
            "slack.send_message",
            {"channel": "#test", "text": "hello"}
        )
    
    assert exc_info.value.code == "bad_request"
    assert "Webhook error" in exc_info.value.message


@pytest.mark.asyncio
async def test_template_rendering_error_handling():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    
    client = SlackMCPClient(
        webhook_url="https://hooks.slack.com/test",
        http_client=mock_http
    )
    await client.connect()

    with pytest.raises(MCPExternalError) as exc_info:
        await client.call_tool(
            "slack.send_message",
            {
                "channel": "#test",
                "template": "{{ undefined_var }}",
                "context": {}
            }
        )
    
    assert exc_info.value.code == "bad_request"
    assert "Template rendering failed" in exc_info.value.message
    assert mock_http.post.call_count == 0  # template error before HTTP call
