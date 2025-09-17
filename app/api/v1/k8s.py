from typing import Any, Dict, List

from fastapi import APIRouter

from ...services.k8s_client import list_kube_contexts


router = APIRouter()


@router.get("/k8s/contexts", response_model=List[Dict[str, Any]])
async def get_kube_contexts() -> List[Dict[str, Any]]:
    contexts = list_kube_contexts()
    return [{"name": name, "current": current} for name, current in contexts]


