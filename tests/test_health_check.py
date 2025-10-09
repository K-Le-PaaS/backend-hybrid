#!/usr/bin/env python3
"""
Health Check 시스템 테스트 스크립트
"""

import asyncio
import httpx
import json
from datetime import datetime, timezone


async def test_health_endpoints():
    """헬스체크 엔드포인트 테스트"""
    base_url = "http://localhost:8000"
    
    print("🔍 Health Check 시스템 테스트 시작")
    print("=" * 50)
    
    # 1. 기본 헬스체크 테스트
    print("\n1. 기본 헬스체크 (/api/v1/health)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v1/health")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 2. 상세 헬스체크 테스트
    print("\n2. 상세 헬스체크 (/api/v1/healthz)")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{base_url}/api/v1/healthz")
            print(f"   상태 코드: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   전체 상태: {data['status']}")
                print(f"   전체 헬스: {data['overall_health']}")
                print(f"   컴포넌트 수: {len(data['components'])}")
                for comp in data['components']:
                    status_icon = "✅" if comp['status'] == 'healthy' else "❌"
                    print(f"     {status_icon} {comp['component']}: {comp['status']}")
                    if comp.get('message'):
                        print(f"       메시지: {comp['message']}")
                    if comp.get('response_time_ms'):
                        print(f"       응답시간: {comp['response_time_ms']:.2f}ms")
            else:
                print(f"   응답: {response.text}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 3. 메트릭 엔드포인트 테스트
    print("\n3. 메트릭 엔드포인트 (/metrics)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/metrics")
            print(f"   상태 코드: {response.status_code}")
            if response.status_code == 200:
                metrics_text = response.text
                # 헬스체크 관련 메트릭 확인
                health_metrics = [line for line in metrics_text.split('\n') 
                                if 'health_check' in line or 'component_status' in line or 'circuit_breaker' in line]
                print(f"   헬스체크 관련 메트릭 수: {len(health_metrics)}")
                for metric in health_metrics[:5]:  # 처음 5개만 표시
                    print(f"     {metric}")
                if len(health_metrics) > 5:
                    print(f"     ... 및 {len(health_metrics) - 5}개 더")
            else:
                print(f"   응답: {response.text}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 4. DB 헬스체크 테스트
    print("\n4. DB 헬스체크 (/api/v1/health/db)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v1/health/db")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 5. MCP 서버 테스트
    print("\n5. MCP 서버 테스트 (/mcp/info)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/mcp/info")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Health Check 시스템 테스트 완료")


async def test_alerting():
    """알림 시스템 테스트"""
    print("\n🔔 알림 시스템 테스트")
    print("=" * 30)
    
    try:
        from app.services.alerting import send_health_alert, send_circuit_breaker_alert
        
        # 헬스체크 알림 테스트
        print("\n1. 헬스체크 알림 전송 테스트")
        success = await send_health_alert(
            component="test-component",
            instance="test-instance",
            is_healthy=False,
            message="테스트 알림입니다"
        )
        print(f"   결과: {'✅ 성공' if success else '❌ 실패'}")
        
        # Circuit Breaker 알림 테스트
        print("\n2. Circuit Breaker 알림 전송 테스트")
        success = await send_circuit_breaker_alert(
            component="test-component",
            state="OPEN",
            message="테스트 Circuit Breaker 알림입니다"
        )
        print(f"   결과: {'✅ 성공' if success else '❌ 실패'}")
        
    except Exception as e:
        print(f"   ❌ 알림 테스트 실패: {e}")


async def main():
    """메인 테스트 함수"""
    print(f"🚀 K-Le-PaaS Health Check 테스트 시작 - {datetime.now(timezone.utc).isoformat()}")
    
    await test_health_endpoints()
    await test_alerting()
    
    print(f"\n🏁 테스트 완료 - {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
