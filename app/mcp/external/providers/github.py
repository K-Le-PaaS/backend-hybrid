from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Mapping, Callable
from urllib.parse import urljoin

import httpx

from ..interfaces import ExternalMCPClient
from ..errors import MCPExternalError
from ..metrics import MCP_EXTERNAL_LATENCY, MCP_EXTERNAL_REQUESTS
from ..retry import retry_async
from ..metrics import MCP_EXTERNAL_ERRORS, MCP_EXTERNAL_HEALTH


class GitHubMCPClient(ExternalMCPClient):
    """GitHub MCP connector with GitHub App authentication and rate limiting.

    Supports GitHub App JWT → Installation Token flow and handles rate limits
    with exponential backoff. Uses HTTP transport for MCP communication.
    """

    def __init__(
        self, 
        base_url: str, 
        app_id: str | None = None,
        private_key: str | None = None,
        installation_id: str | None = None,
        token_provider: Callable[[], str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._app_id = app_id
        self._private_key = private_key
        self._installation_id = installation_id
        self._token_provider = token_provider
        self._connected = False
        self._http_client: httpx.AsyncClient | None = http_client
        self._installation_token: str | None = None
        self._token_expires_at: float = 0

    async def connect(self) -> None:
        """Establish HTTP client and authenticate if needed."""
        if self._connected:
            return
            
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        
        # Authenticate if GitHub App credentials provided
        if self._app_id and self._private_key and self._installation_id:
            await self._ensure_installation_token()
        
        self._connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available GitHub MCP tools."""
        provider, op = "github", "list_tools"
        with MCP_EXTERNAL_LATENCY.labels(provider, op).time():
            try:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "attempt").inc()

                async def _run() -> list[dict[str, Any]]:
                    await self._ensure_connected()
                    
                    # Call GitHub MCP discovery endpoint
                    response = await self._make_request("GET", "/mcp/tools")
                    tools_data = response.get("tools", [])
                    
                    # Normalize tool format
                    return [
                        {
                            "name": tool.get("name", ""),
                            "description": tool.get("description", ""),
                            "inputSchema": tool.get("inputSchema", {})
                        }
                        for tool in tools_data
                    ]

                result = await retry_async(_run)
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "ok").inc()
                return result
            except MCPExternalError as e:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, e.code).inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code=e.code).inc()
                raise
            except asyncio.TimeoutError as e:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "timeout").inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code="timeout").inc()
                raise MCPExternalError(code="timeout", message=str(e))
            except Exception as e:  # noqa: BLE001
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "internal").inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code="internal").inc()
                raise MCPExternalError(code="internal", message=str(e))

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Call a GitHub MCP tool by name with arguments."""
        provider, op = "github", f"call:{name}"
        with MCP_EXTERNAL_LATENCY.labels(provider, op).time():
            try:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "attempt").inc()

                async def _run() -> dict[str, Any]:
                    await self._ensure_connected()
                    
                    # Call GitHub MCP tool endpoint
                    response = await self._make_request(
                        "POST", 
                        f"/mcp/tools/{name}",
                        json={"arguments": dict(arguments)}
                    )
                    
                    # Normalize response format
                    return {
                        "ok": response.get("ok", True),
                        "content": response.get("content", response)
                    }

                result = await retry_async(_run)
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "ok").inc()
                return result
            except MCPExternalError as e:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, e.code).inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code=e.code).inc()
                raise
            except asyncio.TimeoutError as e:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "timeout").inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code="timeout").inc()
                raise MCPExternalError(code="timeout", message=str(e))
            except Exception as e:  # noqa: BLE001
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "internal").inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code="internal").inc()
                raise MCPExternalError(code="internal", message=str(e))

    async def health(self) -> dict[str, Any]:
        """Check GitHub MCP server health."""
        provider, op = "github", "health"
        with MCP_EXTERNAL_LATENCY.labels(provider, op).time():
            try:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "attempt").inc()

                async def _run() -> dict[str, Any]:
                    await self._ensure_connected()
                    
                    # Lightweight health check
                    response = await self._make_request("GET", "/mcp/health")
                    return {
                        "ok": response.get("ok", True),
                        "connected": self._connected,
                        "server_status": response.get("status", "unknown")
                    }

                result = await retry_async(_run)
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "ok").inc()
                MCP_EXTERNAL_HEALTH.labels(provider=provider).set(1)
                return result
            except MCPExternalError as e:
                MCP_EXTERNAL_REQUESTS.labels(provider, op, e.code).inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code=e.code).inc()
                MCP_EXTERNAL_HEALTH.labels(provider=provider).set(0)
                raise
            except Exception as e:  # noqa: BLE001
                MCP_EXTERNAL_REQUESTS.labels(provider, op, "internal").inc()
                MCP_EXTERNAL_ERRORS.labels(provider=provider, operation=op, code="internal").inc()
                MCP_EXTERNAL_HEALTH.labels(provider=provider).set(0)
                raise MCPExternalError(code="internal", message=str(e))

    async def close(self) -> None:
        """Close HTTP client and clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._connected = False
        self._installation_token = None
        self._token_expires_at = 0

    async def _ensure_connected(self) -> None:
        """Ensure client is connected and authenticated."""
        if not self._connected:
            await self.connect()

    async def _ensure_installation_token(self) -> None:
        """Ensure we have a valid installation token."""
        if not self._installation_token or time.time() >= self._token_expires_at:
            await self._refresh_installation_token()

    async def _refresh_installation_token(self) -> None:
        """Refresh GitHub App installation token."""
        if not self._app_id or not self._private_key or not self._installation_id:
            return

        # Generate JWT for GitHub App
        jwt_token = self._generate_jwt()
        
        # Request installation token
        headers = {"Authorization": f"Bearer {jwt_token}"}
        url = f"https://api.github.com/app/installations/{self._installation_id}/access_tokens"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            self._installation_token = data["token"]
            # Set expiry with 5 minute buffer
            self._token_expires_at = time.time() + data.get("expires_in", 3600) - 300

    def _generate_jwt(self) -> str:
        """Generate JWT for GitHub App authentication."""
        # This is a simplified implementation
        # In production, use a proper JWT library like PyJWT
        import base64
        import hmac
        import hashlib
        
        # Simplified JWT generation (not production-ready)
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,  # 10 minutes
            "iss": self._app_id
        }
        
        # This is a placeholder - use proper JWT library in production
        return f"jwt.{base64.b64encode(json.dumps(header).encode()).decode()}.{base64.b64encode(json.dumps(payload).encode()).decode()}"

    async def _make_request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Make authenticated HTTP request to GitHub MCP server."""
        if not self._http_client:
            raise MCPExternalError(code="internal", message="HTTP client not initialized")
        
        url = urljoin(self._base_url, path)
        headers = kwargs.get("headers", {})
        
        # Add authentication
        if self._installation_token:
            headers["Authorization"] = f"Bearer {self._installation_token}"
        elif self._token_provider:
            headers["Authorization"] = f"Bearer {self._token_provider()}"
        
        kwargs["headers"] = headers
        
        try:
            response = await self._http_client.request(method, url, **kwargs)
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                MCP_EXTERNAL_ERRORS.labels(provider="github", operation=f"{method} {path}", code="rate_limited").inc()
                raise MCPExternalError(
                    code="rate_limited",
                    message="GitHub API rate limit exceeded",
                    retry_after_seconds=retry_after
                )
            
            # Handle other HTTP errors
            if response.status_code >= 400:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_message = error_data.get("message", f"HTTP {response.status_code}")
                code = "bad_request"
                if response.status_code == 401:
                    code = "unauthorized"
                elif response.status_code == 403:
                    code = "forbidden"
                elif response.status_code == 404:
                    code = "not_found"
                MCP_EXTERNAL_ERRORS.labels(provider="github", operation=f"{method} {path}", code=code).inc()
                raise MCPExternalError(code=code, message=error_message)
            
            return response.json() if response.content else {}
            
        except httpx.TimeoutException as e:
            MCP_EXTERNAL_ERRORS.labels(provider="github", operation=f"{method} {path}", code="timeout").inc()
            raise MCPExternalError(code="timeout", message=str(e))
        except httpx.ConnectError as e:
            MCP_EXTERNAL_ERRORS.labels(provider="github", operation=f"{method} {path}", code="unavailable").inc()
            raise MCPExternalError(code="unavailable", message=str(e))


