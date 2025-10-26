#!/usr/bin/env python3
"""
Simple SlackTemplateBuilder test
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_template_builder():
    """Test template builder basic functionality"""
    print("Testing SlackTemplateBuilder...")
    
    try:
        from app.services.slack_template_builder import SlackTemplateBuilder
        
        # Initialize template builder
        builder = SlackTemplateBuilder()
        print("SUCCESS: SlackTemplateBuilder initialized")
        
        # Test data
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
        
        # Test deployment started notification
        print("Testing deployment started notification...")
        started_payload = builder.build_deployment_notification(
            notification_type="started",
            **test_context
        )
        print(f"SUCCESS: Started notification generated with {len(started_payload.get('blocks', []))} blocks")
        
        # Test deployment success notification
        print("Testing deployment success notification...")
        success_payload = builder.build_deployment_notification(
            notification_type="success",
            **test_context
        )
        print(f"SUCCESS: Success notification generated with {len(success_payload.get('blocks', []))} blocks")
        
        # Test deployment failed notification
        print("Testing deployment failed notification...")
        failed_payload = builder.build_deployment_notification(
            notification_type="failed",
            **test_context
        )
        print(f"SUCCESS: Failed notification generated with {len(failed_payload.get('blocks', []))} blocks")
        
        # Check available templates
        templates = builder.get_available_templates()
        print(f"SUCCESS: Found {len(templates)} templates: {templates}")
        
        print("ALL TESTS PASSED!")
        return True
        
    except Exception as e:
        print(f"ERROR: Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_template_builder()
    sys.exit(0 if success else 1)
