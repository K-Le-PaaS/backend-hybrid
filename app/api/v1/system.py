from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    """Liveness/Readiness combined health endpoint.

    Returns basic process health with uptime in seconds.
    """
    started_at = getattr(request.app.state, "started_at", None)
    now = datetime.now(timezone.utc)
    uptime_seconds = (now - started_at).total_seconds() if started_at else None

    return {
        "status": "ok",
        "time": now.isoformat(),
        "uptime_seconds": uptime_seconds,
    }


@router.get("/version")
async def version(request: Request) -> Dict[str, Any]:
    """Return app name and version info."""
    return {
        "name": request.app.title,
        "version": request.app.version,
    }


