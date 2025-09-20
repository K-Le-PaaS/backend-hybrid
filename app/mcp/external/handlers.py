from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from .interfaces import ExternalMCPClient
from .errors import MCPExternalError
from .message_converter import MCPMessageConverter, MCPRequestHandler
from ...services.notify import slack_notify
from ...core.config import get_settings


@dataclass
class MCPHandlerConfig:
    """Configuration for MCP handlers."""
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    breaker_failure_threshold: int = 5
    breaker_reset_timeout_sec: float = 30.0


class MCPHandler:
    """Main handler for MCP operations."""
    
    def __init__(self, external_client: ExternalMCPClient, config: Optional[MCPHandlerConfig] = None):
        self.external_client = external_client
        self.config = config or MCPHandlerConfig()
        self.converter = MCPMessageConverter()
        self.request_handler = MCPRequestHandler(external_client)
        # Circuit breaker state
        self._breaker_failures = 0
        self._breaker_opened_at: float | None = None
    
    def _select_alert_channel(self, code: str) -> str | None:
        s = get_settings()
        if code == "rate_limited" and s.slack_alert_channel_rate_limited:
            return s.slack_alert_channel_rate_limited
        if code == "unauthorized" and s.slack_alert_channel_unauthorized:
            return s.slack_alert_channel_unauthorized
        return s.slack_alert_channel_default

    def _select_template(self, kind: str) -> str:
        s = get_settings()
        if kind == "health":
            return s.slack_alert_template_health_down or "[MCP][HEALTH][DOWN] code={{code}} msg={{message}}"
        return s.slack_alert_template_error or "[MCP][ERROR] {{operation}} failed: code={{code}} msg={{message}}"

    def _breaker_is_open(self) -> bool:
        if self._breaker_opened_at is None:
            return False
        # Half-open after reset timeout
        elapsed = time.time() - self._breaker_opened_at
        if elapsed >= self.config.breaker_reset_timeout_sec:
            # allow a trial call (half-open)
            return False
        return True

    def _breaker_record_success(self) -> None:
        self._breaker_failures = 0
        self._breaker_opened_at = None

    def _breaker_record_failure(self) -> None:
        self._breaker_failures += 1
        if self._breaker_failures >= self.config.breaker_failure_threshold:
            self._breaker_opened_at = time.time()

    async def initialize(self) -> None:
        """Initialize the MCP handler."""
        await self.external_client.connect()
    
    async def cleanup(self) -> None:
        """Cleanup the MCP handler."""
        await self.external_client.close()
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from external MCP server."""
        if self._breaker_is_open():
            raise MCPExternalError(code="circuit_open", message="Circuit breaker is open")
        try:
            result = await self.request_handler.handle_list_tools()
            self._breaker_record_success()
            return result
        except MCPExternalError as e:
            self._breaker_record_failure()
            # Non-blocking Slack alert
            try:
                await slack_notify(
                    template=self._select_template("error"),
                    context={"operation": "list_tools", "code": e.code, "message": e.message},
                    channel=self._select_alert_channel(e.code),
                )
            except Exception:
                pass
            raise
        except Exception as e:
            self._breaker_record_failure()
            try:
                await slack_notify(
                    template=self._select_template("error"),
                    context={"operation": "list_tools", "code": "internal", "message": str(e)},
                    channel=self._select_alert_channel("internal"),
                )
            except Exception:
                pass
            raise MCPExternalError(
                code="internal",
                message=f"Failed to list tools: {e}"
            )
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on external MCP server."""
        if self._breaker_is_open():
            raise MCPExternalError(code="circuit_open", message="Circuit breaker is open")
        try:
            result = await self.request_handler.handle_tool_call(tool_name, arguments)
            self._breaker_record_success()
            return result
        except MCPExternalError as e:
            self._breaker_record_failure()
            try:
                await slack_notify(
                    template=self._select_template("error"),
                    context={"operation": f"call:{tool_name}", "code": e.code, "message": e.message},
                    channel=self._select_alert_channel(e.code),
                )
            except Exception:
                pass
            raise
        except Exception as e:
            self._breaker_record_failure()
            try:
                await slack_notify(
                    template=self._select_template("error"),
                    context={"operation": f"call:{tool_name}", "code": "internal", "message": str(e)},
                    channel=self._select_alert_channel("internal"),
                )
            except Exception:
                pass
            raise MCPExternalError(
                code="internal",
                message=f"Failed to call tool {tool_name}: {e}"
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of external MCP server."""
        if self._breaker_is_open():
            raise MCPExternalError(code="circuit_open", message="Circuit breaker is open")
        try:
            result = await self.request_handler.handle_health_check()
            self._breaker_record_success()
            return result
        except MCPExternalError as e:
            self._breaker_record_failure()
            try:
                await slack_notify(
                    template=self._select_template("health"),
                    context={"code": e.code, "message": e.message},
                    channel=self._select_alert_channel(e.code),
                )
            except Exception:
                pass
            raise
        except Exception as e:
            self._breaker_record_failure()
            try:
                await slack_notify(
                    template=self._select_template("health"),
                    context={"code": "internal", "message": str(e)},
                    channel=self._select_alert_channel("internal"),
                )
            except Exception:
                pass
            raise MCPExternalError(
                code="internal",
                message=f"Health check failed: {e}"
            )
    
    async def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get schema for a specific tool."""
        try:
            tools = await self.list_tools()
            for tool in tools:
                if tool.get("name") == tool_name:
                    return tool.get("inputSchema", {})
            return None
        except Exception as e:
            try:
                await slack_notify(f"[MCP][ERROR] get_tool_schema {tool_name} failed: code=internal msg={e}")
            except Exception:
                pass
            raise MCPExternalError(
                code="internal",
                message=f"Failed to get tool schema for {tool_name}: {e}"
            )


class MCPHandlerPool:
    """Pool of MCP handlers for multiple external servers."""
    
    def __init__(self):
        self.handlers: Dict[str, MCPHandler] = {}
    
    def add_handler(self, name: str, handler: MCPHandler) -> None:
        """Add a handler to the pool."""
        self.handlers[name] = handler
    
    def get_handler(self, name: str) -> Optional[MCPHandler]:
        """Get a handler by name."""
        return self.handlers.get(name)
    
    def list_handlers(self) -> List[str]:
        """List all handler names."""
        return list(self.handlers.keys())
    
    async def initialize_all(self) -> None:
        """Initialize all handlers."""
        tasks = [handler.initialize() for handler in self.handlers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def cleanup_all(self) -> None:
        """Cleanup all handlers."""
        tasks = [handler.cleanup() for handler in self.handlers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Check health of all handlers."""
        results = {}
        for name, handler in self.handlers.items():
            try:
                results[name] = await handler.health_check()
            except Exception as e:
                results[name] = {
                    "ok": False,
                    "error": str(e)
                }
        return results
