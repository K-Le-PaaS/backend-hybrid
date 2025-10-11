#!/usr/bin/env python3
"""
FastMCP HTTP 서버 테스트
"""

import asyncio
from fastmcp import FastMCP

async def test_http_mcp():
    """FastMCP HTTP 서버 테스트"""
    # FastMCP 서버 생성
    mcp = FastMCP(name="test-server", version="0.1.0")
    
    # 간단한 도구 정의
    @mcp.tool
    def hello_world(name: str) -> str:
        """간단한 인사 도구"""
        return f"Hello, {name}!"
    
    print("✅ FastMCP 서버 생성 성공")
    print("✅ 도구 등록 성공")
    
    # HTTP 앱 생성
    http_app = mcp.http_app()
    print(f"✅ HTTP 앱 생성 성공: {type(http_app)}")
    
    # HTTP 앱의 구조 확인
    print(f"✅ HTTP 앱 속성들: {[attr for attr in dir(http_app) if not attr.startswith('_')]}")
    
    # 라우트 확인
    if hasattr(http_app, 'routes'):
        print(f"✅ 라우트 수: {len(http_app.routes)}")
        for route in http_app.routes:
            print(f"  - {route.path} ({route.methods})")
    
    return mcp, http_app

if __name__ == "__main__":
    mcp, http_app = asyncio.run(test_http_mcp())


