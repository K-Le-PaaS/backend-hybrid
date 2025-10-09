import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.mcp.external.providers.slack import SlackMCPClient
from app.mcp.external.errors import MCPExternalError


class TestSlackMCPClient:
    """Test cases for SlackMCPClient."""

    @pytest.fixture
    def mock_http_client(self):
        """Mock HTTP client for testing."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.aclose = AsyncMock()
        return client

    @pytest.fixture
    def slack_client_webhook(self, mock_http_client):
        """Slack client with webhook authentication."""
        return SlackMCPClient(
            webhook_url="https://hooks.slack.com/test",
            http_client=mock_http_client
        )

    @pytest.fixture
    def slack_client_bot(self, mock_http_client):
        """Slack client with bot token authentication."""
        return SlackMCPClient(
            bot_token="xoxb-test-token",
            http_client=mock_http_client
        )

    @pytest.mark.asyncio
    async def test_connect_webhook(self, slack_client_webhook):
        """Test connecting with webhook URL."""
        await slack_client_webhook.connect()
        assert slack_client_webhook._connected is True

    @pytest.mark.asyncio
    async def test_connect_bot_token(self, slack_client_bot):
        """Test connecting with bot token."""
        await slack_client_bot.connect()
        assert slack_client_bot._connected is True

    @pytest.mark.asyncio
    async def test_connect_no_auth(self, mock_http_client):
        """Test connecting without authentication fails."""
        client = SlackMCPClient(http_client=mock_http_client)
        
        with pytest.raises(MCPExternalError) as exc_info:
            await client.connect()
        
        assert exc_info.value.code == "bad_request"
        assert "authentication method" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_list_tools(self, slack_client_webhook):
        """Test listing available tools."""
        tools = await slack_client_webhook.list_tools()
        
        assert len(tools) == 8
        tool_names = [tool["name"] for tool in tools]
        assert "slack.send_message" in tool_names
        assert "slack.list_channels" in tool_names
        assert "slack.get_channel_info" in tool_names
        assert "slack.list_users" in tool_names
        assert "slack.get_user_info" in tool_names
        assert "slack.notify_build" in tool_names
        assert "slack.notify_deploy" in tool_names
        assert "slack.notify_release" in tool_names

    @pytest.mark.asyncio
    async def test_send_message_webhook(self, slack_client_webhook, mock_http_client):
        """Test sending message via webhook."""
        # Mock webhook response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_http_client.post.return_value = mock_response

        await slack_client_webhook.connect()
        
        result = await slack_client_webhook.call_tool(
            "slack.send_message",
            {"channel": "#test", "text": "Hello World"}
        )
        
        assert result["ok"] is True
        assert "content" in result
        assert result["content"]["channel"] == "#test"
        assert result["content"]["text"] == "Hello World"
        
        # Verify webhook was called
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        assert call_args[1]["json"]["channel"] == "#test"
        assert call_args[1]["json"]["text"] == "Hello World"

    @pytest.mark.asyncio
    async def test_send_message_api(self, slack_client_bot, mock_http_client):
        """Test sending message via API."""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "ts": "1234567890.123456", "channel": "C1234567890", "message": {"text": "Hello World"}}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.call_tool(
            "slack.send_message",
            {"channel": "#test", "text": "Hello World"}
        )
        
        assert result["ok"] is True
        assert "content" in result
        assert result["content"]["ts"] == "1234567890.123456"

    @pytest.mark.asyncio
    async def test_list_channels(self, slack_client_bot, mock_http_client):
        """Test listing channels."""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "channels": [{"id": "C123", "name": "general", "is_channel": true}, {"id": "C456", "name": "random", "is_channel": true}]}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.call_tool("slack.list_channels", {})
        
        assert result["ok"] is True
        assert "content" in result
        assert len(result["content"]["channels"]) == 2
        assert result["content"]["channels"][0]["name"] == "general"

    @pytest.mark.asyncio
    async def test_get_channel_info(self, slack_client_bot, mock_http_client):
        """Test getting channel information."""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "channel": {"id": "C123", "name": "general", "is_channel": true, "num_members": 10}}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.call_tool(
            "slack.get_channel_info",
            {"channel": "C123"}
        )
        
        assert result["ok"] is True
        assert "content" in result
        assert result["content"]["name"] == "general"
        assert result["content"]["num_members"] == 10

    @pytest.mark.asyncio
    async def test_list_users(self, slack_client_bot, mock_http_client):
        """Test listing users."""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "members": [{"id": "U123", "name": "user1", "real_name": "User One"}, {"id": "U456", "name": "user2", "real_name": "User Two"}]}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.call_tool("slack.list_users", {})
        
        assert result["ok"] is True
        assert "content" in result
        assert len(result["content"]["users"]) == 2
        assert result["content"]["users"][0]["name"] == "user1"

    @pytest.mark.asyncio
    async def test_get_user_info(self, slack_client_bot, mock_http_client):
        """Test getting user information."""
        # Mock API response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "user": {"id": "U123", "name": "user1", "real_name": "User One", "profile": {"email": "user1@example.com"}}}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.call_tool(
            "slack.get_user_info",
            {"user": "U123"}
        )
        
        assert result["ok"] is True
        assert "content" in result
        assert result["content"]["name"] == "user1"
        assert result["content"]["real_name"] == "User One"

    @pytest.mark.asyncio
    async def test_health_check_webhook(self, slack_client_webhook):
        """Test health check with webhook."""
        await slack_client_webhook.connect()
        
        result = await slack_client_webhook.health()
        
        assert result["ok"] is True
        assert result["connected"] is True
        assert result["provider"] == "slack"
        assert result["auth_type"] == "webhook"

    @pytest.mark.asyncio
    async def test_health_check_bot_token(self, slack_client_bot, mock_http_client):
        """Test health check with bot token."""
        # Mock auth.test response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aread = AsyncMock(return_value=b'{"ok": true, "team": "Test Team", "bot_id": "B123"}')
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        result = await slack_client_bot.health()
        
        assert result["ok"] is True
        assert result["connected"] is True
        assert result["provider"] == "slack"
        assert result["workspace"] == "Test Team"
        assert result["bot_id"] == "B123"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, slack_client_webhook):
        """Test calling unknown tool raises error."""
        await slack_client_webhook.connect()
        
        with pytest.raises(MCPExternalError) as exc_info:
            await slack_client_webhook.call_tool("unknown.tool", {})
        
        assert exc_info.value.code == "bad_request"
        assert "Unknown tool" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_rate_limiting(self, slack_client_bot, mock_http_client):
        """Test rate limiting handling."""
        # Mock rate limit response
        mock_response = AsyncMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}
        mock_http_client.post.return_value = mock_response

        await slack_client_bot.connect()
        
        with pytest.raises(MCPExternalError) as exc_info:
            await slack_client_bot.call_tool("slack.list_channels", {})
        
        assert exc_info.value.code == "rate_limited"
        assert exc_info.value.retry_after_seconds == 1

    @pytest.mark.asyncio
    async def test_close(self, slack_client_webhook, mock_http_client):
        """Test closing the client."""
        await slack_client_webhook.connect()
        await slack_client_webhook.close()
        
        mock_http_client.aclose.assert_called_once()
        assert slack_client_webhook._connected is False
