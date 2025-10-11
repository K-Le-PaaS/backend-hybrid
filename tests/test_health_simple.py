#!/usr/bin/env python3
"""
간단한 헬스체크 테스트 스크립트
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
            
            if response.status_code == 200:
                print("   ✅ 기본 헬스체크 성공")
            else:
                print("   ❌ 기본 헬스체크 실패")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 2. 상세 헬스체크 테스트
    print("\n2. 상세 헬스체크 (/api/v1/healthz)")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{base_url}/api/v1/healthz")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
            
            if response.status_code in [200, 503]:
                print("   ✅ 상세 헬스체크 성공")
            else:
                print("   ❌ 상세 헬스체크 실패")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 3. DB 헬스체크 테스트
    print("\n3. DB 헬스체크 (/api/v1/health/db)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v1/health/db")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
            
            if response.status_code == 200:
                print("   ✅ DB 헬스체크 성공")
            else:
                print("   ❌ DB 헬스체크 실패")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 4. 메트릭 엔드포인트 테스트
    print("\n4. 메트릭 엔드포인트 (/metrics)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/metrics")
            print(f"   상태 코드: {response.status_code}")
            
            if response.status_code == 200:
                content = response.text
                if "health_check_total" in content and "component_status" in content:
                    print("   ✅ 메트릭 엔드포인트 성공")
                else:
                    print("   ⚠️ 메트릭 엔드포인트 응답이 예상과 다름")
            else:
                print("   ❌ 메트릭 엔드포인트 실패")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    # 5. 버전 엔드포인트 테스트
    print("\n5. 버전 엔드포인트 (/api/v1/version)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/api/v1/version")
            print(f"   상태 코드: {response.status_code}")
            print(f"   응답: {response.json()}")
            
            if response.status_code == 200:
                print("   ✅ 버전 엔드포인트 성공")
            else:
                print("   ❌ 버전 엔드포인트 실패")
    except Exception as e:
        print(f"   ❌ 실패: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 Health Check 시스템 테스트 완료")


async def test_alerting_service():
    """알림 서비스 테스트"""
    print("\n🔔 알림 서비스 테스트")
    print("-" * 30)
    
    try:
        # 알림 서비스 모듈 테스트
        from app.services.alerting import Alert, AlertStatus, AlertSeverity, AlertGroup
        
        # Alert 생성 테스트
        alert = Alert(
            alertname="TestAlert",
            status=AlertStatus.FIRING,
            severity=AlertSeverity.CRITICAL,
            component="test-component",
            instance="test-instance",
            summary="Test alert",
            description="This is a test alert",
            starts_at="2024-01-01T00:00:00Z"
        )
        
        print(f"   ✅ Alert 생성 성공: {alert.alertname}")
        
        # AlertGroup 생성 테스트
        group = AlertGroup(
            group_key="test-group",
            status=AlertStatus.FIRING,
            alerts=[alert]
        )
        
        print(f"   ✅ AlertGroup 생성 성공: {group.group_key}")
        
        # 알림 전송 함수 테스트 (실제 전송은 하지 않음)
        from app.services.alerting import send_health_alert, send_circuit_breaker_alert
        
        # 헬스체크 알림 테스트
        result = await send_health_alert(
            component="test-component",
            instance="test-instance",
            is_healthy=False,
            message="테스트 알림"
        )
        
        print(f"   ✅ 헬스체크 알림 함수 테스트: {result}")
        
        # Circuit Breaker 알림 테스트
        result = await send_circuit_breaker_alert(
            component="test-component",
            state="OPEN",
            message="테스트 Circuit Breaker 알림"
        )
        
        print(f"   ✅ Circuit Breaker 알림 함수 테스트: {result}")
        
    except Exception as e:
        print(f"   ❌ 알림 서비스 테스트 실패: {e}")


async def test_prometheus_metrics():
    """Prometheus 메트릭 테스트"""
    print("\n📊 Prometheus 메트릭 테스트")
    print("-" * 30)
    
    try:
        from app.api.v1.system import (
            health_check_counter,
            health_check_duration,
            component_status,
            system_info,
            circuit_breaker_state
        )
        
        # 메트릭이 정상적으로 생성되었는지 확인
        assert health_check_counter is not None
        assert health_check_duration is not None
        assert component_status is not None
        assert system_info is not None
        assert circuit_breaker_state is not None
        
        print("   ✅ Prometheus 메트릭 등록 성공")
        
        # 메트릭 증가 테스트
        health_check_counter.labels(status='success', component='test').inc()
        health_check_counter.labels(status='error', component='test').inc()
        
        print("   ✅ 메트릭 증가 테스트 성공")
        
    except Exception as e:
        print(f"   ❌ Prometheus 메트릭 테스트 실패: {e}")


async def main():
    """메인 테스트 함수"""
    print("🚀 K-Le-PaaS Health Check 시스템 테스트")
    print("=" * 60)
    
    # 서버가 실행 중인지 확인
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8000/api/v1/health")
            if response.status_code == 200:
                print("✅ 서버가 실행 중입니다. 테스트를 시작합니다.")
            else:
                print("⚠️ 서버가 실행 중이지만 응답이 예상과 다릅니다.")
    except Exception as e:
        print(f"❌ 서버가 실행되지 않았습니다: {e}")
        print("   서버를 먼저 실행해주세요: uvicorn app.main:app --reload")
        return
    
    # 테스트 실행
    await test_health_endpoints()
    await test_alerting_service()
    await test_prometheus_metrics()
    
    print("\n🎉 모든 테스트가 완료되었습니다!")


if __name__ == "__main__":
    asyncio.run(main())
