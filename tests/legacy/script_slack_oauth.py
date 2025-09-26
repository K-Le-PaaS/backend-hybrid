#!/usr/bin/env python3
import asyncio
import httpx


async def main():
    print("Slack OAuth 테스트 도구")
    # 실제 상호작용 코드는 원본 스크립트 참고 필요
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("http://localhost:8000/api/v1/health")
        print(resp.status_code)


if __name__ == "__main__":
    asyncio.run(main())

