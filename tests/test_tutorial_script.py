"""
K-Le-PaaS 튜토리얼 스크립트 테스트
"""

import pytest
from unittest.mock import patch
from app.services.tutorial_script import (
    TutorialScript,
    TutorialStateManager,
    TutorialStep,
    TutorialState
)


class TestTutorialScript:
    """튜토리얼 스크립트 테스트"""
    
    def test_script_creation(self):
        """스크립트 생성 테스트"""
        script = TutorialScript()
        assert script is not None
        assert len(script.get_all_steps()) == 5
    
    def test_get_step_message(self):
        """단계별 메시지 조회 테스트"""
        script = TutorialScript()
        
        # WELCOME 단계 테스트
        welcome_message = script.get_step_message(TutorialStep.WELCOME)
        assert welcome_message.title == "🚀 K-Le-PaaS에 오신 것을 환영합니다!"
        assert "1분 만에" in welcome_message.content
        assert len(welcome_message.natural_language_examples) > 0
        
        # DEPLOY_APP 단계 테스트
        deploy_message = script.get_step_message(TutorialStep.DEPLOY_APP)
        assert "배포" in deploy_message.title
        assert "자연어로" in deploy_message.content
        assert len(deploy_message.natural_language_examples) > 0
    
    def test_get_next_step(self):
        """다음 단계 조회 테스트"""
        script = TutorialScript()
        
        # WELCOME -> DEPLOY_APP
        next_step = script.get_next_step(TutorialStep.WELCOME)
        assert next_step == TutorialStep.DEPLOY_APP
        
        # DEPLOY_APP -> CHECK_STATUS
        next_step = script.get_next_step(TutorialStep.DEPLOY_APP)
        assert next_step == TutorialStep.CHECK_STATUS
        
        # COMPLETE -> None
        next_step = script.get_next_step(TutorialStep.COMPLETE)
        assert next_step is None
    
    def test_is_last_step(self):
        """마지막 단계 확인 테스트"""
        script = TutorialScript()
        
        assert not script.is_last_step(TutorialStep.WELCOME)
        assert not script.is_last_step(TutorialStep.DEPLOY_APP)
        assert not script.is_last_step(TutorialStep.CHECK_STATUS)
        assert not script.is_last_step(TutorialStep.ROLLBACK)
        assert script.is_last_step(TutorialStep.COMPLETE)


class TestTutorialStateManager:
    """튜토리얼 상태 관리자 테스트"""
    
    def setup_method(self):
        """테스트 전 설정"""
        self.manager = TutorialStateManager()
        self.session_id = "test_session_123"
    
    def test_start_tutorial(self):
        """튜토리얼 시작 테스트"""
        result = self.manager.start_tutorial(self.session_id)
        
        assert result is not None
        assert result["session_id"] == self.session_id
        assert result["step"] == "welcome"
        assert result["step_index"] == 0
        assert result["total_steps"] == 5
        assert result["state"] == "in_progress"
        assert "환영" in result["title"]
    
    def test_get_current_step(self):
        """현재 단계 조회 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 현재 상태 조회
        result = self.manager.get_current_step(self.session_id)
        
        assert result is not None
        assert result["session_id"] == self.session_id
        assert result["step"] == "welcome"
        assert result["state"] == "in_progress"
    
    def test_get_current_step_not_found(self):
        """존재하지 않는 세션 조회 테스트"""
        result = self.manager.get_current_step("nonexistent_session")
        assert result is None
    
    def test_next_step(self):
        """다음 단계 진행 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 다음 단계로 진행
        result = self.manager.next_step(self.session_id)
        
        assert result is not None
        assert result["step"] == "deploy_app"
        assert result["step_index"] == 1
        assert result["state"] == "waiting_user"
        assert "배포" in result["title"]
    
    def test_next_step_not_found(self):
        """존재하지 않는 세션의 다음 단계 테스트"""
        result = self.manager.next_step("nonexistent_session")
        assert result is None
    
    def test_complete_tutorial(self):
        """튜토리얼 완료 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 튜토리얼 완료
        result = self.manager.complete_tutorial(self.session_id)
        
        assert result is not None
        assert result["step"] == "complete"
        assert result["state"] == "completed"
        assert "완료" in result["title"]
    
    def test_add_user_input(self):
        """사용자 입력 추가 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 사용자 입력 추가
        success = self.manager.add_user_input(self.session_id, "hello-world 앱을 배포해줘")
        
        assert success is True
        
        # 상태 확인
        result = self.manager.get_current_step(self.session_id)
        assert len(result["user_inputs"]) == 1
        assert result["user_inputs"][0]["input"] == "hello-world 앱을 배포해줘"
    
    def test_add_user_input_not_found(self):
        """존재하지 않는 세션에 사용자 입력 추가 테스트"""
        success = self.manager.add_user_input("nonexistent_session", "test input")
        assert success is False
    
    def test_add_error(self):
        """에러 추가 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 에러 추가
        success = self.manager.add_error(self.session_id, "배포 중 오류 발생")
        
        assert success is True
        
        # 상태 확인
        result = self.manager.get_current_step(self.session_id)
        assert len(result["errors"]) == 1
        assert result["errors"][0]["error"] == "배포 중 오류 발생"
        assert result["state"] == "error"
    
    def test_add_error_not_found(self):
        """존재하지 않는 세션에 에러 추가 테스트"""
        success = self.manager.add_error("nonexistent_session", "test error")
        assert success is False
    
    def test_reset_session(self):
        """세션 리셋 테스트"""
        # 튜토리얼 시작
        self.manager.start_tutorial(self.session_id)
        
        # 세션 리셋
        success = self.manager.reset_session(self.session_id)
        
        assert success is True
        
        # 세션이 삭제되었는지 확인
        result = self.manager.get_current_step(self.session_id)
        assert result is None
    
    def test_reset_session_not_found(self):
        """존재하지 않는 세션 리셋 테스트"""
        success = self.manager.reset_session("nonexistent_session")
        assert success is False
    
    def test_full_tutorial_flow(self):
        """전체 튜토리얼 플로우 테스트"""
        # 1. 튜토리얼 시작
        result = self.manager.start_tutorial(self.session_id)
        assert result["step"] == "welcome"
        
        # 2. 사용자 입력 추가
        self.manager.add_user_input(self.session_id, "hello-world 앱을 배포해줘")
        
        # 3. 다음 단계로 진행
        result = self.manager.next_step(self.session_id)
        assert result["step"] == "deploy_app"
        
        # 4. 상태 확인 단계로 진행
        result = self.manager.next_step(self.session_id)
        assert result["step"] == "check_status"
        
        # 5. 롤백 단계로 진행
        result = self.manager.next_step(self.session_id)
        assert result["step"] == "rollback"
        
        # 6. 튜토리얼 완료
        result = self.manager.complete_tutorial(self.session_id)
        assert result["step"] == "complete"
        assert result["state"] == "completed"
        
        # 7. 완료된 단계 확인
        assert len(result["completed_steps"]) == 5
        assert "welcome" in result["completed_steps"]
        assert "deploy_app" in result["completed_steps"]
        assert "check_status" in result["completed_steps"]
        assert "rollback" in result["completed_steps"]
        assert "complete" in result["completed_steps"]


class TestTutorialIntegration:
    """튜토리얼 통합 테스트"""
    
    def test_tutorial_with_errors(self):
        """에러가 포함된 튜토리얼 테스트"""
        manager = TutorialStateManager()
        session_id = "error_test_session"
        
        # 튜토리얼 시작
        manager.start_tutorial(session_id)
        
        # 에러 추가
        manager.add_error(session_id, "배포 실패")
        
        # 상태 확인
        result = manager.get_current_step(session_id)
        assert result["state"] == "error"
        assert len(result["errors"]) == 1
        
        # 에러 후에도 다음 단계로 진행 가능한지 확인
        result = manager.next_step(session_id)
        assert result is not None
        assert result["step"] == "deploy_app"
    
    def test_multiple_sessions(self):
        """여러 세션 동시 관리 테스트"""
        manager = TutorialStateManager()
        session1 = "session_1"
        session2 = "session_2"
        
        # 두 개의 세션 시작
        result1 = manager.start_tutorial(session1)
        result2 = manager.start_tutorial(session2)
        
        assert result1["session_id"] == session1
        assert result2["session_id"] == session2
        
        # 각각 독립적으로 진행
        manager.next_step(session1)
        result1 = manager.get_current_step(session1)
        result2 = manager.get_current_step(session2)
        
        assert result1["step"] == "deploy_app"
        assert result2["step"] == "welcome"  # session2는 아직 첫 단계


if __name__ == "__main__":
    pytest.main([__file__])
