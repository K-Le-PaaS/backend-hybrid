from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional


@dataclass
class DeployRecord:
    app_name: str
    environment: str
    image: str
    replicas: int
    timestamp: str


_history: Dict[str, Deque[DeployRecord]] = defaultdict(lambda: deque(maxlen=3))


def _key(app_name: str, environment: str) -> str:
    return f"{app_name}:{environment}"


def record_deploy(app_name: str, environment: str, image: str, replicas: int) -> DeployRecord:
    rec = DeployRecord(
        app_name=app_name,
        environment=environment,
        image=image,
        replicas=replicas,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    _history[_key(app_name, environment)].appendleft(rec)
    return rec


def get_history(app_name: str, environment: str) -> List[Dict[str, str | int]]:
    return [asdict(r) for r in _history.get(_key(app_name, environment), deque())]


def get_previous(app_name: str, environment: str) -> Optional[DeployRecord]:
    dq = _history.get(_key(app_name, environment))
    if not dq or len(dq) < 2:
        return None
    # index 1 is previous version (index 0 is current)
    return dq[1]


