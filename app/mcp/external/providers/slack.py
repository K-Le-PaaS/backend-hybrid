from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Mapping, Callable, Optional
from urllib.parse import urljoin

import httpx
from jinja2 import Environment, StrictUndefined

from ..interfaces import ExternalMCPClient
from ..errors import MCPExternalError
from ..metrics import MCP_EXTERNAL_LATENCY, MCP_EXTERNAL_REQUESTS
from ..metrics import MCP_EXTERNAL_ERRORS, MCP_EXTERNAL_HEALTH
from ..retry import retry_async
from ....services.slack_notification_service import get_slack_notification_service
from ....models.slack_events import SlackEventType


class SlackMCPClient(ExternalMCPClient):
    """Slack MCP connector with Webhook and Bot Token authentication.

    Supports both Incoming Webhooks and Bot Token authentication for comprehensive
    Slack API access. Handles rate limiting and provides MCP tools for messaging,
    channel management, and user operations.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        bot_token: str | None = None,
        token_provider: Callable[[], str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._bot_token = bot_token
        self._token_provider = token_provider
        self._connected = False
        self._http_client: httpx.AsyncClient | None = http_client
        self._api_base_url = "https://slack.com/api"
        self._notification_service = get_slack_notification_service()

    async def connect(self) -> None:
        """Establish HTTP client and authenticate if needed."""
        if self._connected:
            return
            
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        
        # Validate authentication
        if not self._webhook_url and not self._bot_token and not self._token_provider:
            raise MCPExternalError(
                code="bad_request",
                message="At least one authentication method (webhook_url, bot_token, or token_provider) must be provided"
            )
        
        self._connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return available Slack MCP tools."""
        return [
            {
                "name": "slack.send_message",
                "description": "Send a message to a Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel name or ID"},
                        "text": {"type": "string", "description": "Message text"},
                        "blocks": {"type": "array", "description": "Block Kit blocks"},
                        "attachments": {"type": "array", "description": "Message attachments"},
                        "thread_ts": {"type": "string", "description": "Thread timestamp for replies"},
                        "template": {"type": "string", "description": "Jinja2 template string"},
                        "context": {"type": "object", "description": "Template context key-values"},
                        "event_type": {"type": "string", "description": "Event key for channel_map lookup"},
                        "channel_map": {"type": "object", "description": "Mapping of event->channel"}
                    },
                    "required": [],
                    "oneOf": [
                        {"required": ["channel"]},
                        {"required": ["event_type", "channel_map"]}
                    ],
                    "anyOf": [
                        {"required": ["text"]},
                        {"required": ["blocks"]},
                        {"required": ["attachments"]},
                        {"required": ["template"]}
                    ]
                },
            },
            {
                "name": "slack.list_channels",
                "description": "List all channels in the workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "exclude_archived": {"type": "boolean", "default": True},
                        "types": {"type": "string", "default": "public_channel,private_channel"}
                    }
                }
            },
            {
                "name": "slack.get_channel_info",
                "description": "Get information about a specific channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel name or ID"}
                    },
                    "required": ["channel"]
                }
            },
            {
                "name": "slack.list_users",
                "description": "List all users in the workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_locale": {"type": "boolean", "default": False}
                    }
                }
            },
            {
                "name": "slack.get_user_info",
                "description": "Get information about a specific user",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user": {"type": "string", "description": "User ID"}
                    },
                    "required": ["user"]
                }
            },
            {
                "name": "slack.notify_build",
                "description": "Send build status notification",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_map": {"type": "object"},
                        "context": {"type": "object"}
                    },
                    "required": ["channel_map", "context"]
                }
            },
            {
                "name": "slack.notify_deploy",
                "description": "Send deploy status notification",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_map": {"type": "object"},
                        "context": {"type": "object"}
                    },
                    "required": ["channel_map", "context"]
                }
            },
            {
                "name": "slack.notify_release",
                "description": "Send release status notification",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_map": {"type": "object"},
                        "context": {"type": "object"}
                    },
                    "required": ["channel_map", "context"]
                }
            },
        ]

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke a Slack MCP tool."""
        if not self._connected:
            await self.connect()

        # Get current token
        token = await self._get_token()
        
        # Route to appropriate tool handler
        if name == "slack.send_message":
            return await self._send_message(arguments, token)
        elif name == "slack.list_channels":
            return await self._list_channels(arguments, token)
        elif name == "slack.get_channel_info":
            return await self._get_channel_info(arguments, token)
        elif name == "slack.list_users":
            return await self._list_users(arguments, token)
        elif name == "slack.get_user_info":
            return await self._get_user_info(arguments, token)
        elif name == "slack.notify_build":
            return await self._notify_event("build", arguments, token)
        elif name == "slack.notify_deploy":
            return await self._notify_event("deploy", arguments, token)
        elif name == "slack.notify_release":
            return await self._notify_event("release", arguments, token)
        else:
            raise MCPExternalError(
                code="bad_request",
                message=f"Unknown tool: {name}"
            )

    async def health(self) -> dict[str, Any]:
        """Check Slack API connectivity."""
        if not self._connected:
            await self.connect()

        try:
            # Test with auth.test endpoint if we have a bot token
            token = await self._get_token()
            if token and not self._webhook_url:
                response = await self._make_api_request("auth.test", {}, token)
                MCP_EXTERNAL_HEALTH.labels(provider="slack").set(1)
                return {
                    "ok": True,
                    "connected": True,
                    "provider": "slack",
                    "workspace": response.get("team", "unknown"),
                    "bot_id": response.get("bot_id", "unknown")
                }
            else:
                # For webhook-only, just check if we can connect
                MCP_EXTERNAL_HEALTH.labels(provider="slack").set(1)
                return {
                    "ok": True,
                    "connected": True,
                    "provider": "slack",
                    "auth_type": "webhook"
                }
        except Exception as e:
            MCP_EXTERNAL_HEALTH.labels(provider="slack").set(0)
            return {
                "ok": False,
                "connected": False,
                "provider": "slack",
                "error": str(e)
            }

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False

    async def _get_token(self) -> str | None:
        """Get current authentication token."""
        if self._token_provider:
            return self._token_provider()
        return self._bot_token

    async def _make_api_request(
        self, 
        endpoint: str, 
        params: dict[str, Any], 
        token: str | None = None
    ) -> dict[str, Any]:
        """Make authenticated API request to Slack with retry logic."""
        async def _request():
            url = urljoin(self._api_base_url, endpoint)
            headers = {"Content-Type": "application/json"}
            
            if token:
                headers["Authorization"] = f"Bearer {token}"
            
            # Add token to params if not in headers
            if token and "token" not in params:
                params["token"] = token

            with MCP_EXTERNAL_LATENCY.labels(provider="slack", operation=endpoint).time():
                response = await self._http_client.post(url, json=params, headers=headers)
                
                MCP_EXTERNAL_REQUESTS.labels(
                    provider="slack", 
                    operation=endpoint, 
                    result="success" if response.status_code == 200 else "error"
                ).inc()

                if response.status_code == 429:
                    # Rate limited
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    MCP_EXTERNAL_ERRORS.labels(provider="slack", operation=endpoint, code="rate_limited").inc()
                    raise MCPExternalError(
                        code="rate_limited",
                        message="Slack API rate limit exceeded",
                        retry_after_seconds=retry_after
                    )
                
                if response.status_code == 401:
                    MCP_EXTERNAL_ERRORS.labels(provider="slack", operation=endpoint, code="unauthorized").inc()
                    raise MCPExternalError(
                        code="unauthorized",
                        message="Slack API authentication failed"
                    )
                
                if response.status_code != 200:
                    MCP_EXTERNAL_ERRORS.labels(provider="slack", operation=endpoint, code="bad_request").inc()
                    raise MCPExternalError(
                        code="bad_request",
                        message=f"Slack API error: {response.status_code} - {response.text}"
                    )

                data = await response.aread()
                data = json.loads(data)
                if not data.get("ok", False):
                    error = data.get("error", "unknown_error")
                    MCP_EXTERNAL_ERRORS.labels(provider="slack", operation=endpoint, code=error).inc()
                    raise MCPExternalError(
                        code="bad_request",
                        message=f"Slack API error: {error}"
                    )
                
                return data

        return await retry_async(_request, attempts=3, base_delay=1.0)

    async def _send_message(
        self, 
        arguments: Mapping[str, Any], 
        token: str | None
    ) -> dict[str, Any]:
        """Send message to Slack channel."""
        channel = arguments.get("channel")
        text = arguments.get("text", "")
        # Support inline Jinja2 template rendering
        template_str = arguments.get("template")
        context = arguments.get("context", {})
        if template_str:
            env = Environment(undefined=StrictUndefined, autoescape=False)
            try:
                text = env.from_string(template_str).render(**context)
            except Exception as e:
                raise MCPExternalError(
                    code="bad_request",
                    message=f"Template rendering failed: {e}"
                )
        blocks = arguments.get("blocks")
        attachments = arguments.get("attachments")
        thread_ts = arguments.get("thread_ts")
        # support event-based channel mapping
        if not channel:
            event_type = arguments.get("event_type")
            channel_map = arguments.get("channel_map") or {}
            if event_type and isinstance(channel_map, dict):
                channel = channel_map.get(str(event_type))

        if not channel:
            raise MCPExternalError(
                code="bad_request",
                message="Channel is required"
            )

        # Use webhook if available, otherwise use Web API
        if self._webhook_url and not token:
            return await self._send_webhook_message(
                channel, text, blocks, attachments, thread_ts
            )
        else:
            return await self._send_api_message(
                channel, text, blocks, attachments, thread_ts, token
            )

    async def _send_webhook_message(
        self,
        channel: str,
        text: str,
        blocks: list[dict] | None,
        attachments: list[dict] | None,
        thread_ts: str | None
    ) -> dict[str, Any]:
        """Send message via webhook."""
        payload = {
            "channel": channel,
            "text": text
        }
        
        if blocks:
            payload["blocks"] = blocks
        if attachments:
            payload["attachments"] = attachments
        if thread_ts:
            payload["thread_ts"] = thread_ts

        with MCP_EXTERNAL_LATENCY.labels(provider="slack", operation="webhook.send").time():
            response = await self._http_client.post(self._webhook_url, json=payload)
            
            MCP_EXTERNAL_REQUESTS.labels(
                provider="slack",
                operation="webhook.send",
                result="success" if response.status_code == 200 else "error"
            ).inc()

            if response.status_code != 200:
                raise MCPExternalError(
                    code="bad_request",
                    message=f"Webhook error: {response.status_code} - {response.text}"
                )

            return {
                "ok": True,
                "content": {
                    "message": "Message sent via webhook",
                    "channel": channel,
                    "text": text
                }
            }

    async def _send_api_message(
        self,
        channel: str,
        text: str,
        blocks: list[dict] | None,
        attachments: list[dict] | None,
        thread_ts: str | None,
        token: str | None
    ) -> dict[str, Any]:
        """Send message via Slack Web API."""
        params = {
            "channel": channel,
            "text": text
        }
        
        if blocks:
            params["blocks"] = blocks
        if attachments:
            params["attachments"] = attachments
        if thread_ts:
            params["thread_ts"] = thread_ts

        response = await self._make_api_request("chat.postMessage", params, token)
        
        return {
            "ok": True,
            "content": {
                "ts": response.get("ts"),
                "channel": response.get("channel"),
                "message": response.get("message", {})
            }
        }

    async def _list_channels(
        self, 
        arguments: Mapping[str, Any], 
        token: str | None
    ) -> dict[str, Any]:
        """List all channels."""
        if not token:
            raise MCPExternalError(
                code="unauthorized",
                message="Bot token required for channel listing"
            )

        params = {
            "exclude_archived": arguments.get("exclude_archived", True),
            "types": arguments.get("types", "public_channel,private_channel")
        }

        response = await self._make_api_request("conversations.list", params, token)
        
        return {
            "ok": True,
            "content": {
                "channels": response.get("channels", [])
            }
        }

    async def _get_channel_info(
        self, 
        arguments: Mapping[str, Any], 
        token: str | None
    ) -> dict[str, Any]:
        """Get channel information."""
        if not token:
            raise MCPExternalError(
                code="unauthorized",
                message="Bot token required for channel info"
            )

        channel = arguments.get("channel")
        if not channel:
            raise MCPExternalError(
                code="bad_request",
                message="Channel is required"
            )

        params = {"channel": channel}
        response = await self._make_api_request("conversations.info", params, token)
        
        return {
            "ok": True,
            "content": response.get("channel", {})
        }

    async def _list_users(
        self, 
        arguments: Mapping[str, Any], 
        token: str | None
    ) -> dict[str, Any]:
        """List all users."""
        if not token:
            raise MCPExternalError(
                code="unauthorized",
                message="Bot token required for user listing"
            )

        params = {
            "include_locale": arguments.get("include_locale", False)
        }

        response = await self._make_api_request("users.list", params, token)
        
        return {
            "ok": True,
            "content": {
                "users": response.get("members", [])
            }
        }

    async def _get_user_info(
        self, 
        arguments: Mapping[str, Any], 
        token: str | None
    ) -> dict[str, Any]:
        """Get user information."""
        if not token:
            raise MCPExternalError(
                code="unauthorized",
                message="Bot token required for user info"
            )

        user = arguments.get("user")
        if not user:
            raise MCPExternalError(
                code="bad_request",
                message="User ID is required"
            )

        params = {"user": user}
        response = await self._make_api_request("users.info", params, token)
        
        return {
            "ok": True,
            "content": response.get("user", {})
        }

    async def _notify_event(self, event: str, arguments: Mapping[str, Any], token: str | None) -> dict[str, Any]:
        """이벤트 알림을 새로운 알림 서비스를 통해 전송합니다."""
        channel_map = arguments.get("channel_map") or {}
        context = arguments.get("context") or {}
        
        if not isinstance(channel_map, dict) or event not in channel_map:
            raise MCPExternalError(code="bad_request", message=f"Missing channel mapping for event: {event}")
        
        channel = channel_map[event]
        
        # 이벤트 타입 매핑
        event_type_map = {
            "build": SlackEventType.CI_CD_SUCCESS if context.get("status", "").lower() in ["success", "completed", "passed"] else SlackEventType.CI_CD_FAILURE,
            "deploy": SlackEventType.DEPLOYMENT_SUCCESS if context.get("status", "").lower() in ["success", "completed", "deployed"] else SlackEventType.DEPLOYMENT_FAILURE,
            "release": SlackEventType.DEPLOYMENT_SUCCESS if context.get("status", "").lower() in ["success", "completed", "released"] else SlackEventType.DEPLOYMENT_FAILURE,
        }
        
        event_type = event_type_map.get(event, SlackEventType.GENERIC_INFO)
        
        try:
            # 새로운 알림 서비스 사용
            response = await self._notification_service.send_notification(
                event_type=event_type,
                context=context,
                default_channel=channel
            )
            
            return {
                "ok": True,
                "content": {
                    "message": f"Event notification sent via new service",
                    "event": event,
                    "channel": channel,
                    "event_type": event_type.value,
                    "response": response
                }
            }
            
        except Exception as e:
            # 폴백: 기존 방식 사용
            template = "[{{ status|default('unknown')|upper }}] {{ app|default('app') }} {{ version|default('n/a') }}"
            template = arguments.get("template") or template
            return await self._send_message({
                "channel": channel,
                "template": template,
                "context": context,
            }, token)
