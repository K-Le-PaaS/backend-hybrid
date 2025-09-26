#!/usr/bin/env python3
import asyncio
import httpx


async def main():
    base_url = "http://localhost:8000"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base_url}/api/v1/health")
        print(resp.status_code, resp.text)


if __name__ == "__main__":
    asyncio.run(main())

