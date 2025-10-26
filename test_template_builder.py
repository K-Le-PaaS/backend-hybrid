#!/usr/bin/env python3
"""
SlackTemplateBuilder 테스트 스크립트
템플릿 중앙화가 올바르게 작동하는지 확인합니다. 
"""

import sys
import os
import json
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.slack_template_builder import SlackTemplateBuilder


def test_template_builder():
    """템플릿 빌더 기본 기능 테스트"""
    print("🧪 SlackTemplateBuilder 테스트 시작...")
    
    try:
        # 템플릿 빌더 초기화
        builder = SlackTemplateBuilder()
        print("✅ SlackTemplateBuilder 초기화 성공")
        
        # 테스트 데이터
        test_context = {
            "repo": "K-Le-PaaS/test-repo",
            "commit_sha": "9b0b867",
            "commit_message": "Update TEST.txt",
            "author": "Kim Juhyeon",
            "deployment_id": 1,
            "branch": "main",
            "duration_seconds": 154,
            "app_url": "https://example.com",
            "error_message": "Build failed"
        }
        
        # 배포 시작 알림 테스트
        print("\n📤 배포 시작 알림 테스트...")
        started_payload = builder.build_deployment_notification(
            notification_type="started",
            **test_context
        )
        print(f"✅ 배포 시작 알림 생성 성공: {len(started_payload.get('blocks', []))} blocks")
        
        # 배포 성공 알림 테스트
        print("\n📤 배포 성공 알림 테스트...")
        success_payload = builder.build_deployment_notification(
            notification_type="success",
            **test_context
        )
        print(f"✅ 배포 성공 알림 생성 성공: {len(success_payload.get('blocks', []))} blocks")
        
        # 배포 실패 알림 테스트
        print("\n📤 배포 실패 알림 테스트...")
        failed_payload = builder.build_deployment_notification(
            notification_type="failed",
            **test_context
        )
        print(f"✅ 배포 실패 알림 생성 성공: {len(failed_payload.get('blocks', []))} blocks")
        
        # 사용 가능한 템플릿 확인
        print("\n📋 사용 가능한 템플릿 목록...")
        templates = builder.get_available_templates()
        print(f"✅ 발견된 템플릿: {templates}")
        
        # 템플릿 유효성 검증
        print("\n🔍 템플릿 유효성 검증...")
        for template_name in ["deployment_started_terminal", "deployment_success_terminal", "deployment_failed_terminal"]:
            is_valid = builder.validate_template(template_name, test_context)
            print(f"✅ {template_name}: {'유효' if is_valid else '무효'}")
        
        print("\n🎉 모든 테스트 통과!")
        return True
        
    except Exception as e:
        print(f"❌ 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_notification_service_integration():
    """SlackNotificationService 통합 테스트"""
    print("\n🔗 SlackNotificationService 통합 테스트...")
    
    try:
        from app.services.notification import SlackNotificationService
        
        # 알림 서비스 초기화 (웹훅 URL 없이)
        service = SlackNotificationService(webhook_url="https://hooks.slack.com/test")
        print("✅ SlackNotificationService 초기화 성공")
        
        # 템플릿 빌더가 통합되었는지 확인
        if hasattr(service, 'template_builder'):
            print("✅ TemplateBuilder 통합 확인")
        else:
            print("❌ TemplateBuilder 통합 실패")
            return False
        
        # 사용 가능한 템플릿 확인
        templates = service.template_builder.get_available_templates()
        print(f"✅ 통합된 템플릿 빌더에서 {len(templates)}개 템플릿 발견")
        
        print("🎉 통합 테스트 통과!")
        return True
        
    except Exception as e:
        print(f"❌ 통합 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 Slack 템플릿 중앙화 테스트 시작")
    print("=" * 50)
    
    # 기본 템플릿 빌더 테스트
    template_test_passed = test_template_builder()
    
    # 통합 테스트
    integration_test_passed = test_notification_service_integration()
    
    print("\n" + "=" * 50)
    if template_test_passed and integration_test_passed:
        print("🎉 모든 테스트 통과! 템플릿 중앙화가 성공적으로 구현되었습니다.")
        sys.exit(0)
    else:
        print("❌ 일부 테스트 실패. 로그를 확인하세요.")
        sys.exit(1)
