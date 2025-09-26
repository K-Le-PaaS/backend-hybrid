#!/usr/bin/env python3
import asyncio
import httpx
import json
from datetime import datetime, timezone


async def test_health_endpoints():
    base_url = "http://localhost:8000"
    print("🔍 Health Check 시스템 테스트 시작")
    print("=" * 50)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v1/health")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")


async def main():
    print(f"🚀 K-Le-PaaS Health Check 테스트 시작 - {datetime.now(timezone.utc).isoformat()}")
    await test_health_endpoints()


if __name__ == "__main__":
    asyncio.run(main())

