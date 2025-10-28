from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from kubernetes.client import CoreV1Api
from kubernetes.client.rest import ApiException


def _is_pod_ready(pod: Any) -> bool:
    try:
        conditions = pod.status.conditions or []
        for cond in conditions:
            if getattr(cond, "type", None) == "Ready" and getattr(cond, "status", None) == "True":
                return True
        return False
    except Exception:
        return False


def _get_restart_count(pod: Any) -> int:
    try:
        total = 0
        for cs in pod.status.container_statuses or []:
            total += int(getattr(cs, "restart_count", 0))
        return total
    except Exception:
        return 0


def _get_start_time(pod: Any) -> Optional[datetime]:
    try:
        return getattr(pod.status, "start_time", None)
    except Exception:
        return None


def _list_pods_with_fallbacks(core_v1: CoreV1Api, namespace: str, app_name: str):
    """Try multiple common label selectors to find pods for an app."""
    selectors = [
        f"app={app_name}",
        f"app.kubernetes.io/name={app_name}",
        f"app.kubernetes.io/instance={app_name}",
    ]
    for sel in selectors:
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=sel)
        if pods.items:
            return pods
    # final fallback: no selector → list all and filter by prefix match on name
    try:
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        pods.items = [p for p in pods.items or [] if app_name in getattr(p.metadata, "name", "")]
        return pods
    except Exception:
        return core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={app_name}")


def list_pods_by_app(core_v1: CoreV1Api, namespace: str, app_name: str) -> List[Dict[str, Any]]:
    """List pods for app using multiple label fallbacks; return stable metadata list."""
    pods = _list_pods_with_fallbacks(core_v1, namespace, app_name)
    result: List[Dict[str, Any]] = []
    for p in pods.items or []:
        phase = getattr(p.status, "phase", "Unknown")
        ready = _is_pod_ready(p)
        restarts = _get_restart_count(p)
        start_time = _get_start_time(p)
        result.append(
            {
                "name": p.metadata.name,
                "phase": phase,
                "ready": ready,
                "restarts": restarts,
                "startTime": start_time.isoformat() if start_time else None,
            }
        )
    result.sort(key=lambda x: x["name"])  # stable
    return result


def select_representative_pod(core_v1: CoreV1Api, namespace: str, app_name: str) -> Optional[str]:
    """Select a representative pod using rules:
    1) Ready pods by latest start_time desc
    2) If none, any Running pod (first)
    3) Else the pod with highest restart count (likely problematic)
    """
    pods = _list_pods_with_fallbacks(core_v1, namespace, app_name)
    items = pods.items or []
    if not items:
        return None

    ready_pods: List[Tuple[str, Optional[datetime]]] = [
        (p.metadata.name, _get_start_time(p)) for p in items if _is_pod_ready(p)
    ]
    if ready_pods:
        ready_pods.sort(key=lambda t: (t[1] or datetime.min), reverse=True)
        return ready_pods[0][0]

    for p in items:
        if getattr(p.status, "phase", None) == "Running":
            return p.metadata.name

    # fallback: most restarts
    items.sort(key=lambda p: _get_restart_count(p), reverse=True)
    return items[0].metadata.name


def get_pod_logs(
    core_v1: CoreV1Api,
    namespace: str,
    pod_name: str,
    *,
    lines: int = 200,
    previous: bool = False,
) -> Dict[str, Any]:
    """Fetch pod logs with CrashLoopBackOff-friendly behavior.

    If previous=True is requested and fails, falls back to current logs.
    """
    tail_lines = max(1, min(lines, 1000))
    try:
        logs = core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
            previous=previous,
        )
        return {"podName": pod_name, "logs": logs, "lines": tail_lines}
    except ApiException:
        # fallback to current logs when previous not available
        if previous:
            logs = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines,
            )
            return {
                "podName": pod_name,
                "logs": logs,
                "lines": tail_lines,
                "warning": "이전 로그를 찾을 수 없어 현재 로그를 반환했습니다.",
            }
        raise


