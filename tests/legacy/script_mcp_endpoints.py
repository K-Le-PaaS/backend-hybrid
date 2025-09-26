#!/usr/bin/env python3
import asyncio
from fastmcp import FastMCP


async def test_mcp_endpoints():
    mcp = FastMCP(name="test-server", version="0.1.0")
    @mcp.tool
    def hello_world(name: str) -> str:
        return f"Hello, {name}!"
    http_app = mcp.http_app()
    print(f"routes: {len(http_app.routes)}")
    for i, route in enumerate(http_app.routes):
        print(f"{i+1}. {route.path} - {route.methods}")


if __name__ == "__main__":
    asyncio.run(test_mcp_endpoints())

