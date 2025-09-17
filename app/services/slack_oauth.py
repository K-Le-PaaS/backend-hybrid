from __future__ import annotations

import json
from typing import Tuple, Set

import httpx

from ..mcp.external.errors import MCPExternalError
from ..mcp.external.retry import retry_async


class SlackOAuthService:
    def __init__(self, client_id: str, client_secret: str, http_client: httpx.AsyncClient | None = None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._http = http_client
        self._token_url = "https://slack.com/api/oauth.v2.access"

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._http

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Tuple[str, Set[str]]:
        async def op():
            client = await self._client()
            resp = await client.post(
                self._token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code == 429:
                raise MCPExternalError(code="rate_limited", message="Slack OAuth rate limit", retry_after_seconds=int(resp.headers.get("Retry-After", "1")))
            if resp.status_code != 200:
                raise MCPExternalError(code="bad_request", message=f"Slack OAuth error: {resp.status_code}")

            data = json.loads(await resp.aread())
            if not data.get("ok", False):
                raise MCPExternalError(code="unauthorized", message=f"Slack OAuth failed: {data.get('error','unknown')}")

            token = data.get("access_token")
            scope_str = data.get("scope", "")
            scopes = {s.strip() for s in scope_str.split(",") if s.strip()}
            return token, scopes

        token, scopes = await retry_async(op, attempts=3, base_delay=1.0)
        if not token:
            raise MCPExternalError(code="unauthorized", message="Slack OAuth did not return token")
        return token, scopes

    async def verify_scopes(self, granted: Set[str], *, required: Set[str]) -> None:
        missing = required - granted
        if missing:
            raise MCPExternalError(code="forbidden", message=f"missing scopes: {', '.join(sorted(missing))}")


