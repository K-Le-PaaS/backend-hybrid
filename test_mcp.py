#!/usr/bin/env python3
"""
간단한 FastMCP 테스트
"""

import asyncio
from fastmcp import FastMCP

async def test_simple_mcp():
    """간단한 MCP 서버 테스트"""
    # FastMCP 서버 생성
    mcp = FastMCP(name="test-server", version="0.1.0")
    
    # 간단한 도구 정의
    @mcp.tool
    def hello_world(name: str) -> str:
        """간단한 인사 도구"""
        return f"Hello, {name}!"
    
    @mcp.tool
    def add_numbers(a: int, b: int) -> int:
        """숫자 더하기 도구"""
        return a + b
    
    print("✅ FastMCP 서버 생성 성공")
    print("✅ 도구 등록 성공")
    
    # 도구 목록 확인
    tools = await mcp.get_tools()
    print(f"✅ 등록된 도구 수: {len(tools)}")
    for tool_name, tool_info in tools.items():
        print(f"  - {tool_name}: {tool_info}")
    
    # 도구 호출 테스트 (원본 함수 호출)
    result1 = hello_world.fn("K-Le-PaaS")
    result2 = add_numbers.fn(5, 3)
    
    print(f"✅ hello_world 테스트: {result1}")
    print(f"✅ add_numbers 테스트: {result2}")
    
    return mcp

if __name__ == "__main__":
    asyncio.run(test_simple_mcp())
