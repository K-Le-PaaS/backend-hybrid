from __future__ import annotations

from typing import Any, Dict
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("audit")
logger.setLevel(logging.INFO)


def log_audit(event: str, *, user: str | None, source_ip: str | None, action: str, resource: str, status: str, details: Dict[str, Any] | None = None) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user": user or "anonymous",
        "src_ip": source_ip or "unknown",
        "action": action,
        "resource": resource,
        "status": status,
        "details": details or {},
    }
    logger.info(json.dumps(record, ensure_ascii=False))


