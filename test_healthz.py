#!/usr/bin/env python3
"""
healthz 엔드포인트 테스트
"""

import asyncio
import httpx


async def test_healthz():
    """healthz 엔드포인트 상세 테스트"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get("http://localhost:8000/api/v1/healthz")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                print("✅ healthz 엔드포인트 정상 작동")
            else:
                print(f"❌ healthz 엔드포인트 실패: {response.status_code}")
                
    except Exception as e:
        print(f"❌ 연결 실패: {e}")


if __name__ == "__main__":
    asyncio.run(test_healthz())
