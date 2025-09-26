#!/usr/bin/env python3
import asyncio
from fastmcp import FastMCP


async def main():
    mcp = FastMCP(name="test-server", version="0.1.0")
    @mcp.tool
    def hello_world(name: str) -> str:
        return f"Hello, {name}!"
    tools = await mcp.get_tools()
    print(len(tools))


if __name__ == "__main__":
    asyncio.run(main())

