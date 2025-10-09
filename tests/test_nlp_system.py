#!/usr/bin/env python3
"""
자연어 명령 처리 시스템 테스트
"""

import asyncio
import requests
import json
import time

def test_nlp_system():
    """자연어 명령 처리 시스템 테스트"""
    base_url = "http://localhost:8000"
    
    print("🚀 자연어 명령 처리 시스템 테스트 시작")
    print("=" * 60)
    
    # 1. 기본 자연어 해석 테스트
    print("\n1. 기본 자연어 해석 테스트")
    try:
        response = requests.post(f"{base_url}/api/v1/nlp/interpret", json={
            "prompt": "web-app을 staging에 3개 복제본으로 배포해줘"
        })
        print(f"   ✅ 기본 해석: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 의도: {data.get('intent', 'unknown')}")
            print(f"   📋 엔티티: {data.get('entities', {})}")
    except Exception as e:
        print(f"   ❌ 기본 해석 실패: {e}")
    
    # 2. 새로운 자연어 명령 처리 테스트
    print("\n2. 새로운 자연어 명령 처리 테스트")
    test_commands = [
        "myapp을 production에 배포해줘",
        "web-service를 5개로 스케일링해줘",
        "api-server의 상태를 확인해줘",
        "frontend-app을 이전 버전으로 롤백해줘"
    ]
    
    for i, command in enumerate(test_commands, 1):
        try:
            print(f"\n   테스트 {i}: {command}")
            response = requests.post(f"{base_url}/api/v1/nlp/command", json={
                "command": command,
                "user_id": "test_user",
                "context": {"environment": "test"}
            })
            print(f"   ✅ 명령 처리: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   📊 명령 ID: {data.get('command_id', 'N/A')}")
                print(f"   📈 상태: {data.get('status', 'unknown')}")
                print(f"   ⏱️ 처리 시간: {data.get('processing_time', 0):.2f}초")
        except Exception as e:
            print(f"   ❌ 명령 처리 실패: {e}")
    
    # 3. 명령 히스토리 테스트
    print("\n3. 명령 히스토리 테스트")
    try:
        response = requests.get(f"{base_url}/api/v1/nlp/history/test_user?limit=5")
        print(f"   ✅ 히스토리 조회: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 총 명령 수: {data.get('total', 0)}")
            print(f"   📋 명령 목록: {len(data.get('commands', []))}개")
    except Exception as e:
        print(f"   ❌ 히스토리 조회 실패: {e}")
    
    # 4. 활성 명령 테스트
    print("\n4. 활성 명령 테스트")
    try:
        response = requests.get(f"{base_url}/api/v1/nlp/active/test_user")
        print(f"   ✅ 활성 명령 조회: {response.status_code}")
        if response.status_code == 200:
            commands = response.json()
            print(f"   📊 활성 명령 수: {len(commands)}")
    except Exception as e:
        print(f"   ❌ 활성 명령 조회 실패: {e}")
    
    # 5. WebSocket 연결 테스트 (간단한 확인)
    print("\n5. WebSocket 연결 테스트")
    try:
        response = requests.get(f"{base_url}/api/v1/ws/stats")
        print(f"   ✅ WebSocket 통계: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   📊 활성 연결: {data.get('active_connections', 0)}")
            print(f"   📈 총 구독: {data.get('total_subscriptions', 0)}")
    except Exception as e:
        print(f"   ❌ WebSocket 통계 실패: {e}")
    
    print("\n" + "=" * 60)
    print("🎉 자연어 명령 처리 시스템 테스트 완료!")

def test_advanced_nlp():
    """고급 자연어 처리 테스트"""
    base_url = "http://localhost:8000"
    
    print("\n🔬 고급 자연어 처리 테스트")
    print("=" * 40)
    
    # 복잡한 자연어 명령 테스트
    complex_commands = [
        "my-web-application을 staging 환경에 최신 이미지로 3개 복제본 배포하고, CPU 사용량을 모니터링해줘",
        "api-server가 너무 느려서 production에서 10개로 스케일링하고, 이전 버전으로 롤백할 준비를 해줘",
        "frontend와 backend를 모두 production에 배포한 후, 전체 시스템 상태를 확인해줘"
    ]
    
    for i, command in enumerate(complex_commands, 1):
        try:
            print(f"\n   복잡한 명령 {i}: {command[:50]}...")
            response = requests.post(f"{base_url}/api/v1/nlp/command", json={
                "command": command,
                "user_id": "advanced_user",
                "context": {
                    "environment": "production",
                    "current_deployments": ["my-web-application", "api-server"]
                }
            })
            print(f"   ✅ 처리 결과: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   📊 신뢰도: {data.get('interpretation', {}).get('confidence', 'N/A')}")
        except Exception as e:
            print(f"   ❌ 처리 실패: {e}")

if __name__ == "__main__":
    test_nlp_system()
    test_advanced_nlp()


