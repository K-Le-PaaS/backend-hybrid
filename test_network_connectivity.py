#!/usr/bin/env python3
"""
배포 환경에서 NCP 서비스 네트워크 연결 테스트 스크립트
"""
import asyncio
import httpx
import socket
import subprocess
import sys
from urllib.parse import urlparse

async def test_dns_resolution():
    """DNS 해석 테스트"""
    print("🔍 DNS 해석 테스트...")
    try:
        result = socket.gethostbyname('devtools.ncloud.com')
        print(f"✅ devtools.ncloud.com -> {result}")
        return True
    except socket.gaierror as e:
        print(f"❌ DNS 해석 실패: {e}")
        return False

async def test_https_connection():
    """HTTPS 연결 테스트"""
    print("🔗 HTTPS 연결 테스트...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get('https://devtools.ncloud.com')
            print(f"✅ HTTPS 연결 성공: {response.status_code}")
            return True
    except httpx.ConnectError as e:
        print(f"❌ HTTPS 연결 실패: {e}")
        return False
    except httpx.TimeoutException:
        print("❌ HTTPS 연결 타임아웃")
        return False
    except Exception as e:
        print(f"❌ HTTPS 연결 에러: {e}")
        return False

async def test_ncp_api():
    """NCP API 연결 테스트"""
    print("🌐 NCP API 연결 테스트...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # SourceCommit API 테스트
            response = await client.get('https://sourcecommit.apigw.ntruss.com/api/v1/repository')
            print(f"✅ SourceCommit API: {response.status_code}")
            
            # SourceBuild API 테스트  
            response = await client.get('https://sourcebuild.apigw.ntruss.com/api/v1/project')
            print(f"✅ SourceBuild API: {response.status_code}")
            
            # SourceDeploy API 테스트
            response = await client.get('https://vpcsourcedeploy.apigw.ntruss.com/api/v1/project')
            print(f"✅ SourceDeploy API: {response.status_code}")
            
            return True
    except Exception as e:
        print(f"❌ NCP API 연결 실패: {e}")
        return False

def test_ping():
    """Ping 테스트"""
    print("📡 Ping 테스트...")
    try:
        result = subprocess.run(['ping', '-c', '3', 'devtools.ncloud.com'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Ping 성공")
            return True
        else:
            print(f"❌ Ping 실패: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Ping 타임아웃")
        return False
    except Exception as e:
        print(f"❌ Ping 에러: {e}")
        return False

async def main():
    """메인 테스트 함수"""
    print("🚀 배포 환경 네트워크 연결 테스트 시작\n")
    
    tests = [
        ("DNS 해석", test_dns_resolution()),
        ("Ping 테스트", test_ping()),
        ("HTTPS 연결", test_https_connection()),
        ("NCP API 연결", test_ncp_api()),
    ]
    
    results = []
    for name, test in tests:
        print(f"\n{'='*50}")
        print(f"테스트: {name}")
        print('='*50)
        try:
            result = await test if asyncio.iscoroutine(test) else test
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} 테스트 중 에러: {e}")
            results.append((name, False))
    
    print(f"\n{'='*50}")
    print("📊 테스트 결과 요약")
    print('='*50)
    
    for name, result in results:
        status = "✅ 성공" if result else "❌ 실패"
        print(f"{name}: {status}")
    
    failed_tests = [name for name, result in results if not result]
    if failed_tests:
        print(f"\n⚠️  실패한 테스트: {', '.join(failed_tests)}")
        print("\n🔧 해결 방안:")
        print("1. 쿠버네티스 클러스터의 네트워크 정책 확인")
        print("2. 방화벽 및 보안 그룹 설정 확인")
        print("3. DNS 서버 설정 확인")
        print("4. 프록시 설정 확인")
        print("5. VPN 연결 상태 확인")
    else:
        print("\n🎉 모든 네트워크 테스트 통과!")

if __name__ == "__main__":
    asyncio.run(main())
