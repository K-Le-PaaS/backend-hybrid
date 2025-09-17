from __future__ import annotations

from typing import Optional, List, Tuple

from kubernetes import client, config


def load_kube_config(context: Optional[str] = None) -> None:
    """Load kube config (in-cluster first, then local kubeconfig)."""
    try:
        config.load_incluster_config()
        return
    except Exception:
        pass

    # Fallback to local kubeconfig
    config.load_kube_config(context=context)


def get_core_v1_api(context: Optional[str] = None) -> client.CoreV1Api:
    load_kube_config(context=context)
    return client.CoreV1Api()


def get_apps_v1_api(context: Optional[str] = None) -> client.AppsV1Api:
    load_kube_config(context=context)
    return client.AppsV1Api()


def list_kube_contexts() -> List[Tuple[str, bool]]:
    """Return available kube contexts as list of (name, is_current)."""
    try:
        contexts, active_context = config.list_kube_config_contexts()
        result: List[Tuple[str, bool]] = []
        current_name = active_context["name"] if active_context else None
        for ctx in contexts:
            name = ctx.get("name")
            result.append((name, name == current_name))
        return result
    except Exception:
        # In-cluster likely; no kubeconfig contexts
        return []


