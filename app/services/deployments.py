from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator
from .history import record_deploy, get_history
from .deployment_history import (
    get_deployment_history_service,
    DeploymentHistoryService,
    DeploymentStatus
)
from ..core.config import get_settings
from .k8s_client import get_apps_v1_api
from kubernetes.client import V1Deployment, V1ObjectMeta, V1DeploymentSpec, V1LabelSelector, V1PodTemplateSpec, V1PodSpec, V1Container, V1ContainerPort, V1LocalObjectReference
from kubernetes.client import AppsV1Api
from .k8s_client import get_core_v1_api
from .notify import slack_notify


class Environment(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class DeployApplicationInput(BaseModel):
    app_name: str = Field(min_length=1)
    environment: Environment
    image: str = Field(min_length=3, description="OCI image reference, e.g., repo/app:tag")
    replicas: int = Field(default=2, ge=1, le=50)

    @field_validator("app_name")
    @classmethod
    def validate_app_name(cls, v: str) -> str:
        if " " in v:
            raise ValueError("app_name must not contain spaces")
        return v


async def perform_deploy(payload: DeployApplicationInput) -> Dict[str, Any]:
    """배포를 수행하고 히스토리를 기록합니다."""
    try:
        # 배포 히스토리 서비스 가져오기
        history_service = get_deployment_history_service()
        
        # 배포 기록 생성
        deployment_id = await history_service.create_deployment_record(
            app_name=payload.app_name,
            environment=payload.environment.value,
            image=payload.image,
            replicas=payload.replicas,
            namespace=f"klepaas-{payload.environment.value}",
            deployed_by="klepaas-deployer",
            deployment_reason="Manual deployment",
            extra_metadata={
                "source": "api",
                "original_payload": payload.model_dump()
            }
        )
        
        # 기존 메모리 히스토리도 유지 (호환성)
        record_deploy(
            app_name=payload.app_name,
            environment=payload.environment.value,
            image=payload.image,
            replicas=payload.replicas,
        )
        
        # 배포 상태를 진행 중으로 업데이트
        await history_service.update_deployment_status(
            deployment_id=deployment_id,
            status=DeploymentStatus.IN_PROGRESS,
            progress=10
        )
        
        plan: Dict[str, Any] = {
            "action": "deploy",
            "app_name": payload.app_name,
            "environment": payload.environment.value,
            "image": payload.image,
            "replicas": payload.replicas,
            "status": "in_progress",
            "deployment_id": deployment_id,
            "progress": 10
        }
        
        plan["history"] = get_history(payload.app_name, payload.environment.value)

    except Exception as e:
        # 에러 발생 시 기본 플랜 반환
        return {
            "action": "deploy",
            "app_name": payload.app_name,
            "environment": payload.environment.value,
            "image": payload.image,
            "replicas": payload.replicas,
            "status": "error",
            "error": str(e)
        }

    # Optional real deploy (guarded by settings to keep tests intact)
    settings = get_settings()
    if not settings.enable_k8s_deploy:
        return plan
    if payload.environment != Environment.STAGING:
        return plan

    namespace = settings.k8s_staging_namespace or "staging"
    name = f"stg-{payload.app_name}"
    labels = {
        "app": payload.app_name,
        "env": payload.environment.value,
    }

    container = V1Container(
        name=payload.app_name,
        image=payload.image,
        ports=[V1ContainerPort(container_port=8080)],
    )
    pod_spec = V1PodSpec(
        containers=[container],
        image_pull_secrets=[V1LocalObjectReference(name=settings.k8s_image_pull_secret)] if settings.k8s_image_pull_secret else None,
    )
    template = V1PodTemplateSpec(
        metadata=V1ObjectMeta(labels=labels),
        spec=pod_spec,
    )
    spec = V1DeploymentSpec(
        replicas=payload.replicas,
        selector=V1LabelSelector(match_labels={"app": payload.app_name}),
        template=template,
    )
    body = V1Deployment(
        metadata=V1ObjectMeta(name=name, labels=labels),
        spec=spec,
    )

    api = get_apps_v1_api()
    try:
        api.create_namespaced_deployment(namespace=namespace, body=body)
        plan["status"] = "applied"
    except Exception as e:
        # try patch for idempotency
        try:
            api.patch_namespaced_deployment(name=name, namespace=namespace, body=body)
            plan["status"] = "updated"
        except Exception as e2:
            plan["status"] = "error"
            plan["error"] = str(e2)
            # summarize pod issues (best-effort) and notify Slack
            try:
                summary = _collect_waiting_reasons(app_name=payload.app_name, namespace=namespace)
                context = {
                    "app": payload.app_name,
                    "env": payload.environment.value,
                    "image": payload.image,
                    "reasons": "\n".join(summary) if summary else "unknown",
                }
                template = "[Deploy][FAILED] {{app}} ({{env}}) -> {{image}}\nReasons:\n{{reasons}}"
                # fire-and-forget async not available here; this is sync path
                import asyncio
                asyncio.create_task(slack_notify(template=template, context=context))
            except Exception:
                pass
    return plan


def perform_rollback(app_name: str, environment: str, target_image: str | None = None) -> Dict[str, Any]:
    from .history import get_previous

    prev = None
    if target_image:
        # create a lightweight record-like object
        class _R:
            def __init__(self, image: str, replicas: int = 2):
                self.image = image
                self.replicas = replicas
        prev = _R(target_image, 2)
    else:
        prev = get_previous(app_name, environment)
        if not prev:
            return {"status": "skipped", "reason": "no previous version"}
    # Re-deploy previous image/replicas (still Phase 1: return plan)
    payload = DeployApplicationInput(
        app_name=app_name,
        environment=Environment(environment),
        image=prev.image,
        replicas=prev.replicas,
    )
    result = perform_deploy(payload)

    # Optional direct patch to point Deployment back to previous image for staging
    settings = get_settings()
    if settings.enable_k8s_deploy and payload.environment == Environment.STAGING:
        try:
            api: AppsV1Api = get_apps_v1_api()
            name = f"stg-{app_name}"
            ns = settings.k8s_staging_namespace or "staging"
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {"name": app_name, "image": prev.image}
                            ]
                        }
                    }
                }
            }
            api.patch_namespaced_deployment(name=name, namespace=ns, body=patch)
        except Exception as e:
            return {"status": "rolled_back", "to": {"image": prev.image, "replicas": prev.replicas}, "result": result, "warning": str(e)}
    return {"status": "rolled_back", "to": {"image": prev.image, "replicas": prev.replicas}, "result": result}


def get_deploy_status(app_name: str, environment: str) -> Dict[str, Any]:
    """Return high-level readiness status for the application's deployment.

    If k8s deploy is disabled, fall back to history-based stub.
    """
    settings = get_settings()
    env = Environment(environment)
    if not settings.enable_k8s_deploy or env != Environment.STAGING:
        hist = get_history(app_name, environment)
        return {
            "app": app_name,
            "environment": environment,
            "ready": 0,
            "total": 0,
            "reasons": [],
            "history_count": len(hist or []),
        }

    ns = settings.k8s_staging_namespace or "staging"
    core = get_core_v1_api()
    pods = core.list_namespaced_pod(namespace=ns, label_selector=f"app={app_name}")
    total = len(pods.items or [])
    ready = 0
    reasons: list[str] = []
    for p in pods.items or []:
        conds = {c.type: c.status for c in (p.status.conditions or [])}
        if conds.get("Ready") == "True":
            ready += 1
        for cs in (p.status.container_statuses or []) or []:
            state = cs.state
            if state and state.waiting:
                reason = state.waiting.reason or "Waiting"
                msg = state.waiting.message or ""
                reasons.append(f"{cs.name}:{reason} {msg}".strip())
    return {
        "app": app_name,
        "environment": environment,
        "ready": ready,
        "total": total,
        "reasons": reasons[:5],
    }


def list_recent_versions(app_name: str, environment: str, limit: int = 3) -> Dict[str, Any]:
    hist = get_history(app_name, environment) or []
    versions = []
    for h in hist[-limit:][::-1]:
        versions.append({"image": h.image, "replicas": h.replicas, "at": getattr(h, "ts", None)})
    return {"app": app_name, "environment": environment, "versions": versions}


def _collect_waiting_reasons(app_name: str, namespace: str) -> list[str]:
    try:
        core = get_core_v1_api()
        pods = core.list_namespaced_pod(namespace=namespace, label_selector=f"app={app_name}")
        reasons: list[str] = []
        for p in pods.items or []:
            for cs in (p.status.container_statuses or []) or []:
                st = cs.state
                if st and st.waiting:
                    reason = st.waiting.reason or "Waiting"
                    msg = st.waiting.message or ""
                    reasons.append(f"{cs.name}:{reason} {msg}".strip())
        return reasons[:5]
    except Exception:
        return []


