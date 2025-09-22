"""
K-Le-PaaS 인터랙티브 튜토리얼 스크립트
1분 플로우: 배포 → 상태 확인 → 롤백
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum


class TutorialStep(Enum):
    """튜토리얼 단계 정의"""
    WELCOME = "welcome"
    DEPLOY_APP = "deploy_app"
    CHECK_STATUS = "check_status"
    ROLLBACK = "rollback"
    COMPLETE = "complete"


class TutorialState(Enum):
    """튜토리얼 상태 정의"""
    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class TutorialMessage:
    """튜토리얼 메시지 구조"""
    title: str
    content: str
    action_text: Optional[str] = None
    natural_language_examples: List[str] = None
    success_message: Optional[str] = None
    error_message: Optional[str] = None


class TutorialScript:
    """1분 플로우 튜토리얼 스크립트"""
    
    def __init__(self):
        self.steps = self._create_tutorial_steps()
    
    def _create_tutorial_steps(self) -> Dict[TutorialStep, TutorialMessage]:
        """튜토리얼 단계별 메시지 생성"""
        return {
            TutorialStep.WELCOME: TutorialMessage(
                title="🚀 K-Le-PaaS에 오신 것을 환영합니다!",
                content="""안녕하세요! K-Le-PaaS는 자연어 명령만으로 Kubernetes 애플리케이션을 배포하고 관리할 수 있는 AI-First PaaS 플랫폼입니다.

이 튜토리얼에서는 1분 만에 다음을 경험해보실 수 있습니다:
1. 📦 애플리케이션 배포
2. 📊 배포 상태 확인  
3. 🔄 문제 발생 시 롤백

준비되셨나요? 시작해보겠습니다!""",
                action_text="시작하기",
                natural_language_examples=[
                    "애플리케이션을 배포해줘",
                    "hello-world 앱을 스테이징에 배포해줘",
                    "nginx 이미지로 웹서버를 만들어줘"
                ]
            ),
            
            TutorialStep.DEPLOY_APP: TutorialMessage(
                title="📦 1단계: 애플리케이션 배포",
                content="""이제 자연어로 애플리케이션을 배포해보겠습니다!

아래 예시 중 하나를 입력하거나, 자유롭게 자연어로 명령해보세요:

**예시 명령어:**
• "hello-world 앱을 스테이징에 배포해줘"
• "nginx 이미지로 웹서버를 만들어줘"  
• "my-app을 2개 복제본으로 배포해줘"

입력창에 명령을 입력하고 실행해보세요!""",
                action_text="배포 실행",
                natural_language_examples=[
                    "hello-world 앱을 스테이징에 배포해줘",
                    "nginx 이미지로 웹서버를 만들어줘",
                    "my-app을 2개 복제본으로 배포해줘",
                    "redis 컨테이너를 배포해줘",
                    "postgres 데이터베이스를 배포해줘"
                ],
                success_message="✅ 배포가 성공적으로 시작되었습니다! 잠시 후 상태를 확인해보겠습니다.",
                error_message="❌ 배포 중 오류가 발생했습니다. 다시 시도해주세요."
            ),
            
            TutorialStep.CHECK_STATUS: TutorialMessage(
                title="📊 2단계: 배포 상태 확인",
                content="""배포가 진행 중입니다! 이제 배포 상태를 확인해보겠습니다.

K-Le-PaaS는 실시간으로 다음을 모니터링합니다:
• 🟢 Pod 상태 (Running, Pending, Error)
• 📈 리소스 사용량 (CPU, Memory)
• 🔗 서비스 연결 상태
• 📋 이벤트 로그

아래 명령어로 상태를 확인해보세요:""",
                action_text="상태 확인",
                natural_language_examples=[
                    "배포 상태를 확인해줘",
                    "hello-world 앱이 정상적으로 실행되고 있나?",
                    "모든 파드가 준비되었는지 확인해줘",
                    "리소스 사용량을 보여줘",
                    "로그를 확인해줘"
                ],
                success_message="✅ 모든 파드가 정상적으로 실행 중입니다! 배포가 성공적으로 완료되었습니다.",
                error_message="⚠️ 일부 파드에 문제가 있습니다. 롤백을 고려해보세요."
            ),
            
            TutorialStep.ROLLBACK: TutorialMessage(
                title="🔄 3단계: 롤백 (문제 해결)",
                content="""만약 배포에 문제가 있다면, 즉시 이전 버전으로 롤백할 수 있습니다!

K-Le-PaaS의 원-클릭 롤백 기능:
• ⚡ 1분 내 이전 버전으로 복구
• 🔒 데이터 손실 없이 안전한 롤백
• 📊 롤백 후 자동 상태 확인
• 🔄 언제든지 다시 배포 가능

아래 명령어로 롤백을 실행해보세요:""",
                action_text="롤백 실행",
                natural_language_examples=[
                    "이전 버전으로 롤백해줘",
                    "hello-world 앱을 롤백해줘",
                    "문제가 있으니 되돌려줘",
                    "마지막 정상 버전으로 복구해줘",
                    "배포를 취소하고 이전 상태로 돌려줘"
                ],
                success_message="✅ 롤백이 성공적으로 완료되었습니다! 이전 안정 버전으로 복구되었습니다.",
                error_message="❌ 롤백 중 오류가 발생했습니다. 수동으로 확인이 필요합니다."
            ),
            
            TutorialStep.COMPLETE: TutorialMessage(
                title="🎉 튜토리얼 완료!",
                content="""축하합니다! K-Le-PaaS의 핵심 기능을 모두 경험해보셨습니다!

**이제 할 수 있는 것들:**
• 🚀 자연어로 애플리케이션 배포
• 📊 실시간 모니터링 및 상태 확인
• 🔄 원-클릭 롤백으로 안전한 운영
• 🤖 AI가 모든 복잡한 설정을 자동 처리

**다음 단계:**
• GitHub 리포지토리 연결
• CI/CD 파이프라인 설정
• 프로덕션 환경 배포
• 고급 모니터링 설정

K-Le-PaaS와 함께 더 빠르고 안전한 배포를 경험해보세요!""",
                action_text="완료",
                natural_language_examples=[]
            )
        }
    
    def get_step_message(self, step: TutorialStep) -> TutorialMessage:
        """특정 단계의 메시지 반환"""
        return self.steps.get(step)
    
    def get_all_steps(self) -> List[TutorialStep]:
        """모든 튜토리얼 단계 반환"""
        return list(TutorialStep)
    
    def get_step_by_index(self, index: int) -> Optional[TutorialStep]:
        """인덱스로 튜토리얼 단계 반환"""
        steps = self.get_all_steps()
        if 0 <= index < len(steps):
            return steps[index]
        return None
    
    def get_next_step(self, current_step: TutorialStep) -> Optional[TutorialStep]:
        """다음 단계 반환"""
        steps = self.get_all_steps()
        try:
            current_index = steps.index(current_step)
            if current_index < len(steps) - 1:
                return steps[current_index + 1]
        except ValueError:
            pass
        return None
    
    def is_last_step(self, step: TutorialStep) -> bool:
        """마지막 단계인지 확인"""
        return step == TutorialStep.COMPLETE


class TutorialStateManager:
    """튜토리얼 상태 관리자"""
    
    def __init__(self):
        self.script = TutorialScript()
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def start_tutorial(self, session_id: str) -> Dict[str, Any]:
        """튜토리얼 시작"""
        self.sessions[session_id] = {
            "current_step": TutorialStep.WELCOME,
            "state": TutorialState.IN_PROGRESS,
            "started_at": None,
            "completed_steps": [],
            "user_inputs": [],
            "errors": []
        }
        
        step_message = self.script.get_step_message(TutorialStep.WELCOME)
        return {
            "session_id": session_id,
            "step": TutorialStep.WELCOME.value,
            "step_index": 0,
            "total_steps": len(self.script.get_all_steps()),
            "title": step_message.title,
            "content": step_message.content,
            "action_text": step_message.action_text,
            "natural_language_examples": step_message.natural_language_examples,
            "state": TutorialState.IN_PROGRESS.value
        }
    
    def get_current_step(self, session_id: str) -> Optional[Dict[str, Any]]:
        """현재 단계 정보 반환"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        current_step = session["current_step"]
        step_message = self.script.get_step_message(current_step)
        step_index = self.script.get_all_steps().index(current_step)
        
        return {
            "session_id": session_id,
            "step": current_step.value,
            "step_index": step_index,
            "total_steps": len(self.script.get_all_steps()),
            "title": step_message.title,
            "content": step_message.content,
            "action_text": step_message.action_text,
            "natural_language_examples": step_message.natural_language_examples,
            "state": session["state"].value,
            "completed_steps": session["completed_steps"],
            "user_inputs": session["user_inputs"][-5:],  # 최근 5개 입력만
            "errors": session["errors"][-3:]  # 최근 3개 에러만
        }
    
    def next_step(self, session_id: str) -> Optional[Dict[str, Any]]:
        """다음 단계로 진행"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        current_step = session["current_step"]
        next_step = self.script.get_next_step(current_step)
        
        if next_step:
            session["completed_steps"].append(current_step.value)
            session["current_step"] = next_step
            session["state"] = TutorialState.WAITING_USER
            
            step_message = self.script.get_step_message(next_step)
            step_index = self.script.get_all_steps().index(next_step)
            
            return {
                "session_id": session_id,
                "step": next_step.value,
                "step_index": step_index,
                "total_steps": len(self.script.get_all_steps()),
                "title": step_message.title,
                "content": step_message.content,
                "action_text": step_message.action_text,
                "natural_language_examples": step_message.natural_language_examples,
                "state": session["state"].value,
                "completed_steps": session["completed_steps"]
            }
        
        return None
    
    def complete_tutorial(self, session_id: str) -> Optional[Dict[str, Any]]:
        """튜토리얼 완료"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        session["state"] = TutorialState.COMPLETED
        session["completed_steps"].append(session["current_step"].value)
        
        step_message = self.script.get_step_message(TutorialStep.COMPLETE)
        step_index = self.script.get_all_steps().index(TutorialStep.COMPLETE)
        
        return {
            "session_id": session_id,
            "step": TutorialStep.COMPLETE.value,
            "step_index": step_index,
            "total_steps": len(self.script.get_all_steps()),
            "title": step_message.title,
            "content": step_message.content,
            "action_text": step_message.action_text,
            "natural_language_examples": step_message.natural_language_examples,
            "state": session["state"].value,
            "completed_steps": session["completed_steps"]
        }
    
    def add_user_input(self, session_id: str, user_input: str) -> bool:
        """사용자 입력 추가"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        session["user_inputs"].append({
            "input": user_input,
            "timestamp": None,  # 실제 구현에서는 datetime.now() 사용
            "step": session["current_step"].value
        })
        return True
    
    def add_error(self, session_id: str, error: str) -> bool:
        """에러 추가"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        session["errors"].append({
            "error": error,
            "timestamp": None,  # 실제 구현에서는 datetime.now() 사용
            "step": session["current_step"].value
        })
        session["state"] = TutorialState.ERROR
        return True
    
    def reset_session(self, session_id: str) -> bool:
        """세션 리셋"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False


# 전역 상태 관리자 인스턴스
tutorial_state_manager = TutorialStateManager()
