"""
K-Le-PaaS 튜토리얼 API 테스트
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.services.tutorial_script import tutorial_state_manager


client = TestClient(app)


class TestTutorialAPI:
    """튜토리얼 API 테스트"""
    
    def setup_method(self):
        """테스트 전 설정"""
        # 각 테스트 전에 상태 관리자 초기화
        tutorial_state_manager.sessions.clear()
    
    def test_start_tutorial(self):
        """튜토리얼 시작 API 테스트"""
        response = client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "test_session_123"
        assert data["step"] == "welcome"
        assert data["step_index"] == 0
        assert data["total_steps"] == 5
        assert data["state"] == "in_progress"
        assert "환영" in data["title"]
    
    def test_get_current_tutorial(self):
        """현재 튜토리얼 상태 조회 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 현재 상태 조회
        response = client.get(
            "/api/v1/tutorial/current?session_id=test_session_123"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "test_session_123"
        assert data["step"] == "welcome"
        assert data["state"] == "in_progress"
    
    def test_get_current_tutorial_not_found(self):
        """존재하지 않는 세션 조회 API 테스트"""
        response = client.get(
            "/api/v1/tutorial/current?session_id=nonexistent_session"
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_next_tutorial_step(self):
        """다음 단계 진행 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 다음 단계로 진행
        response = client.post(
            "/api/v1/tutorial/next?session_id=test_session_123"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["step"] == "deploy_app"
        assert data["step_index"] == 1
        assert data["state"] == "waiting_user"
        assert "배포" in data["title"]
    
    def test_next_tutorial_step_not_found(self):
        """존재하지 않는 세션의 다음 단계 API 테스트"""
        response = client.post(
            "/api/v1/tutorial/next?session_id=nonexistent_session"
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_complete_tutorial(self):
        """튜토리얼 완료 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 튜토리얼 완료
        response = client.post(
            "/api/v1/tutorial/complete?session_id=test_session_123"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["step"] == "complete"
        assert data["state"] == "completed"
        assert "완료" in data["title"]
    
    def test_add_user_input(self):
        """사용자 입력 추가 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 사용자 입력 추가
        response = client.post(
            "/api/v1/tutorial/input",
            json={
                "session_id": "test_session_123",
                "user_input": "hello-world 앱을 배포해줘"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "test_session_123"
        assert len(data["user_inputs"]) == 1
        assert data["user_inputs"][0]["input"] == "hello-world 앱을 배포해줘"
    
    def test_add_user_input_not_found(self):
        """존재하지 않는 세션에 사용자 입력 추가 API 테스트"""
        response = client.post(
            "/api/v1/tutorial/input",
            json={
                "session_id": "nonexistent_session",
                "user_input": "test input"
            }
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_add_error(self):
        """에러 추가 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 에러 추가
        response = client.post(
            "/api/v1/tutorial/error?session_id=test_session_123&error_message=배포 중 오류 발생"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "test_session_123"
        assert len(data["errors"]) == 1
        assert data["errors"][0]["error"] == "배포 중 오류 발생"
        assert data["state"] == "error"
    
    def test_add_error_not_found(self):
        """존재하지 않는 세션에 에러 추가 API 테스트"""
        response = client.post(
            "/api/v1/tutorial/error?session_id=nonexistent_session&error_message=test error"
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_reset_tutorial(self):
        """튜토리얼 리셋 API 테스트"""
        # 먼저 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": "test_session_123"}
        )
        
        # 튜토리얼 리셋
        response = client.delete(
            "/api/v1/tutorial/reset?session_id=test_session_123"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "reset successfully" in data["message"]
        
        # 세션이 삭제되었는지 확인
        get_response = client.get(
            "/api/v1/tutorial/current?session_id=test_session_123"
        )
        assert get_response.status_code == 404
    
    def test_reset_tutorial_not_found(self):
        """존재하지 않는 세션 리셋 API 테스트"""
        response = client.delete(
            "/api/v1/tutorial/reset?session_id=nonexistent_session"
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_full_tutorial_flow_api(self):
        """전체 튜토리얼 플로우 API 테스트"""
        session_id = "full_flow_test"
        
        # 1. 튜토리얼 시작
        response = client.post(
            "/api/v1/tutorial/start",
            json={"session_id": session_id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "welcome"
        
        # 2. 사용자 입력 추가
        response = client.post(
            "/api/v1/tutorial/input",
            json={
                "session_id": session_id,
                "user_input": "hello-world 앱을 배포해줘"
            }
        )
        assert response.status_code == 200
        
        # 3. 다음 단계로 진행
        response = client.post(f"/api/v1/tutorial/next?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "deploy_app"
        
        # 4. 상태 확인 단계로 진행
        response = client.post(f"/api/v1/tutorial/next?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "check_status"
        
        # 5. 롤백 단계로 진행
        response = client.post(f"/api/v1/tutorial/next?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "rollback"
        
        # 6. 튜토리얼 완료
        response = client.post(f"/api/v1/tutorial/complete?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "complete"
        assert data["state"] == "completed"
    
    def test_tutorial_with_errors_api(self):
        """에러가 포함된 튜토리얼 API 테스트"""
        session_id = "error_test"
        
        # 튜토리얼 시작
        client.post(
            "/api/v1/tutorial/start",
            json={"session_id": session_id}
        )
        
        # 에러 추가
        response = client.post(
            f"/api/v1/tutorial/error?session_id={session_id}&error_message=배포 실패"
        )
        assert response.status_code == 200
        
        # 상태 확인
        response = client.get(f"/api/v1/tutorial/current?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "error"
        assert len(data["errors"]) == 1
        
        # 에러 후에도 다음 단계로 진행 가능한지 확인
        response = client.post(f"/api/v1/tutorial/next?session_id={session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == "deploy_app"
    
    def test_invalid_request_data(self):
        """잘못된 요청 데이터 테스트"""
        # session_id 누락
        response = client.post(
            "/api/v1/tutorial/start",
            json={}
        )
        assert response.status_code == 422
        
        # user_input 누락
        response = client.post(
            "/api/v1/tutorial/input",
            json={"session_id": "test"}
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__])
