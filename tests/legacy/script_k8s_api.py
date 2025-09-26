#!/usr/bin/env python3
import asyncio
import httpx


BASE_URL = "http://localhost:8000"


async def main():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/v1/health")
        print("health:", resp.status_code)


if __name__ == "__main__":
    asyncio.run(main())

