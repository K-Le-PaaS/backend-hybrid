from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


STEPS: List[str] = [
    "GitHub Webhook 시크릿 설정",
    "헬스체크 확인 (/api/v1/health)",
    "스테이징 배포 실행 (/api/v1/deploy)",
    "컨텍스트 조회 (/api/v1/k8s/contexts)",
    "프로메테우스 쿼리 (/api/v1/monitoring/query)",
]


@dataclass
class TutorialSession:
    id: str
    current_index: int = 0

    def get(self) -> Dict[str, object]:
        return {"id": self.id, "step": self.current_index + 1, "title": STEPS[self.current_index]}

    def next(self) -> Dict[str, object]:
        if self.current_index < len(STEPS) - 1:
            self.current_index += 1
        return self.get()

    def complete(self) -> Dict[str, object]:
        self.current_index = len(STEPS) - 1
        return self.get()


_sessions: Dict[str, TutorialSession] = {}


def start_session(session_id: str) -> Dict[str, object]:
    sess = TutorialSession(id=session_id)
    _sessions[session_id] = sess
    return sess.get()


def get_session(session_id: str) -> Optional[Dict[str, object]]:
    sess = _sessions.get(session_id)
    return sess.get() if sess else None


def next_step(session_id: str) -> Optional[Dict[str, object]]:
    sess = _sessions.get(session_id)
    if not sess:
        return None
    return sess.next()


def complete_session(session_id: str) -> Optional[Dict[str, object]]:
    sess = _sessions.get(session_id)
    if not sess:
        return None
    return sess.complete()


