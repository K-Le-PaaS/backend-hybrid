#!/usr/bin/env python3
"""
FastMCP 엔드포인트 구조 확인
"""

import asyncio
from fastmcp import FastMCP

async def test_mcp_endpoints():
    """FastMCP 엔드포인트 구조 확인"""
    # FastMCP 서버 생성
    mcp = FastMCP(name="test-server", version="0.1.0")
    
    # 간단한 도구 정의
    @mcp.tool
    def hello_world(name: str) -> str:
        """간단한 인사 도구"""
        return f"Hello, {name}!"
    
    print("✅ FastMCP 서버 생성 성공")
    
    # HTTP 앱 생성
    http_app = mcp.http_app()
    
    # 모든 라우트 확인
    print(f"✅ 전체 라우트 수: {len(http_app.routes)}")
    for i, route in enumerate(http_app.routes):
        print(f"  {i+1}. {route.path} - {route.methods} - {type(route).__name__}")
        
        # 라우트의 하위 라우트가 있는지 확인
        if hasattr(route, 'app') and hasattr(route.app, 'routes'):
            print(f"     하위 라우트 수: {len(route.app.routes)}")
            for j, sub_route in enumerate(route.app.routes):
                print(f"       {j+1}. {sub_route.path} - {sub_route.methods}")
    
    return mcp, http_app

if __name__ == "__main__":
    asyncio.run(test_mcp_endpoints())


