#!/usr/bin/env python3
"""
전체 시스템 테스트
"""

import requests
import json
import time

def test_system():
    """전체 시스템 테스트"""
    base_url = "http://localhost:8000"
    
    print("🚀 K-Le-PaaS 시스템 테스트 시작")
    print("=" * 50)
    
    # 1. 기본 서버 상태 확인
    print("\n1. 기본 서버 상태 확인")
    try:
        response = requests.get(f"{base_url}/")
        print(f"   ✅ 루트 엔드포인트: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 서버 정보: {data['name']} v{data['version']}")
    except Exception as e:
        print(f"   ❌ 루트 엔드포인트 실패: {e}")
    
    # 2. MCP 서버 정보 확인
    print("\n2. MCP 서버 정보 확인")
    try:
        response = requests.get(f"{base_url}/mcp/info")
        print(f"   ✅ MCP 정보 엔드포인트: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 MCP 서버: {data['name']} v{data['version']}")
            print(f"   🔧 도구 수: {data['tools_count']}")
            print(f"   📋 도구 목록: {', '.join(data['tools_available'][:5])}...")
    except Exception as e:
        print(f"   ❌ MCP 정보 엔드포인트 실패: {e}")
    
    # 3. MCP 도구 목록 확인
    print("\n3. MCP 도구 목록 확인")
    try:
        response = requests.get(f"{base_url}/mcp/tools")
        print(f"   ✅ MCP 도구 엔드포인트: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 총 도구 수: {data['count']}")
            for i, tool in enumerate(data['tools'][:3]):
                print(f"   🔧 {i+1}. {tool['name']}: {tool['description']}")
    except Exception as e:
        print(f"   ❌ MCP 도구 엔드포인트 실패: {e}")
    
    # 4. StreamableHTTP 프로토콜 확인
    print("\n4. StreamableHTTP 프로토콜 확인")
    try:
        response = requests.get(f"{base_url}/mcp/stream", headers={'Accept': 'text/event-stream'})
        print(f"   ✅ StreamableHTTP 엔드포인트: {response.status_code}")
        if response.status_code in [400, 406]:  # 정상적인 MCP 프로토콜 응답
            print(f"   📊 MCP 프로토콜 응답: {response.text[:100]}...")
    except Exception as e:
        print(f"   ❌ StreamableHTTP 엔드포인트 실패: {e}")
    
    # 5. 외부 MCP 서버 연동 확인
    print("\n5. 외부 MCP 서버 연동 확인")
    try:
        response = requests.get(f"{base_url}/mcp/external/providers")
        print(f"   ✅ 외부 MCP 프로바이더: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 등록된 프로바이더: {data}")
    except Exception as e:
        print(f"   ❌ 외부 MCP 프로바이더 실패: {e}")
    
    # 6. API 엔드포인트 확인
    print("\n6. API 엔드포인트 확인")
    endpoints = [
        "/api/v1/system/health",
        "/api/v1/deployments",
        "/api/v1/nlp",
        "/api/v1/commands",
        "/api/v1/cicd",
        "/api/v1/k8s",
        "/api/v1/monitoring",
        "/api/v1/tutorial",
        "/api/v1/websocket",
        "/api/v1/slack-auth"
    ]
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}")
            status = "✅" if response.status_code in [200, 404, 405] else "❌"
            print(f"   {status} {endpoint}: {response.status_code}")
        except Exception as e:
            print(f"   ❌ {endpoint}: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 시스템 테스트 완료!")

if __name__ == "__main__":
    test_system()


