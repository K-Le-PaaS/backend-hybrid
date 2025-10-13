from __future__ import annotations

import os
from typing import Optional, List, Tuple

from kubernetes import client, config


def load_kube_config(context: Optional[str] = None) -> None:
    """
    외부에서 NKS 클러스터 접속 설정 로드 (환경변수 필수)
    
    설정: KLEPAAS_K8S_CONFIG_FILE 환경변수 (메인 서버/로컬 모두 사용)
    
    Context 우선순위:
    1. 함수 인자로 전달된 context
    2. Settings의 k8s_context
    3. kubeconfig의 current-context
    
    배경: 메인 서버에서만 실행되며, 외부에서 NKS를 제어
    환경변수가 없으면 실행 안됨 (명시적 설정 강제)
    """
    # Settings에서 설정 가져오기
    from ..core.config import get_settings
    settings = get_settings()
    
    # KLEPAAS_K8S_CONFIG_FILE 환경변수 필수
    if not settings.k8s_config_file:
        raise RuntimeError(
            "KLEPAAS_K8S_CONFIG_FILE 환경변수가 설정되지 않았습니다. "
            "NKS kubeconfig 파일 경로를 환경변수로 설정해주세요. "
            "예: KLEPAAS_K8S_CONFIG_FILE=/path/to/nks-kubeconfig.yaml"
        )
    
    kubeconfig_path = settings.k8s_config_file
    
    # 파일 존재 확인
    if not os.path.exists(kubeconfig_path):
        raise FileNotFoundError(
            f"Kubeconfig 파일을 찾을 수 없습니다: {kubeconfig_path}\n"
            f"KLEPAAS_K8S_CONFIG_FILE 경로를 확인해주세요."
        )
    
    # Context 결정
    effective_context = context or settings.k8s_context
    
    # Kubeconfig 로드
    config.load_kube_config(config_file=kubeconfig_path, context=effective_context)


def get_core_v1_api(context: Optional[str] = None) -> client.CoreV1Api:
    load_kube_config(context=context)
    return client.CoreV1Api()


def get_apps_v1_api(context: Optional[str] = None) -> client.AppsV1Api:
    load_kube_config(context=context)
    return client.AppsV1Api()


def get_networking_v1_api(context: Optional[str] = None) -> client.NetworkingV1Api:
    load_kube_config(context=context)
    return client.NetworkingV1Api()


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


