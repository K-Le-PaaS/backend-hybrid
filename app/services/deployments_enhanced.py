"""
향상된 배포 서비스

실시간 모니터링과 영구 히스토리 저장을 지원하는 배포 서비스입니다.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator
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


class RollbackRequest(BaseModel):
    app_name: str
    environment: str
    target_image: Optional[str] = None


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

        # Optional real deploy (guarded by settings to keep tests intact)
        settings = get_settings()
        if not settings.enable_k8s_deploy:
            # 배포 성공으로 업데이트
            await history_service.update_deployment_status(
                deployment_id=deployment_id,
                status=DeploymentStatus.SUCCESS,
                progress=100
            )
            plan["status"] = "success"
            plan["progress"] = 100
            return plan
            
        if payload.environment != Environment.STAGING:
            # 배포 성공으로 업데이트
            await history_service.update_deployment_status(
                deployment_id=deployment_id,
                status=DeploymentStatus.SUCCESS,
                progress=100
            )
            plan["status"] = "success"
            plan["progress"] = 100
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
            # 배포 성공으로 업데이트
            await history_service.update_deployment_status(
                deployment_id=deployment_id,
                status=DeploymentStatus.SUCCESS,
                progress=100
            )
            plan["progress"] = 100
        except Exception as e:
            # try patch for idempotency
            try:
                api.patch_namespaced_deployment(name=name, namespace=namespace, body=body)
                plan["status"] = "updated"
                # 배포 성공으로 업데이트
                await history_service.update_deployment_status(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.SUCCESS,
                    progress=100
                )
                plan["progress"] = 100
            except Exception as e2:
                plan["status"] = "error"
                plan["error"] = str(e2)
                # 배포 실패로 업데이트
                await history_service.update_deployment_status(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    progress=0,
                    extra_metadata={"error": str(e2)}
                )
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
        
    except Exception as e:
        # 에러 발생 시 실패 상태로 업데이트
        try:
            history_service = get_deployment_history_service()
            if 'deployment_id' in locals():
                await history_service.update_deployment_status(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    progress=0,
                    extra_metadata={"error": str(e)}
                )
        except:
            pass
        
        raise


async def perform_rollback(app_name: str, environment: str, target_image: str | None = None) -> Dict[str, Any]:
    """롤백을 수행하고 히스토리를 기록합니다."""
    try:
        history_service = get_deployment_history_service()
        
        if target_image:
            # 특정 이미지로 롤백
            # 이전 배포 기록 찾기
            recent_versions = await history_service.get_recent_versions(
                app_name=app_name,
                environment=environment,
                limit=1
            )
            
            if not recent_versions:
                return {"status": "skipped", "reason": "no previous version"}
            
            current_deployment_id = recent_versions[0].id
            
            # 롤백 기록 생성
            rollback_id = await history_service.create_rollback_record(
                app_name=app_name,
                environment=environment,
                target_image=target_image,
                rolled_back_from=current_deployment_id,
                rollback_reason=f"Manual rollback to {target_image}",
                deployed_by="klepaas-rollbacker"
            )
            
            # 롤백 배포 수행
            payload = DeployApplicationInput(
                app_name=app_name,
                environment=Environment(environment),
                image=target_image,
                replicas=2,  # 기본값
            )
            result = await perform_deploy(payload)
            
            return {
                "status": "rolled_back",
                "rollback_id": rollback_id,
                "target_image": target_image,
                "result": result
            }
        else:
            # 이전 버전으로 롤백
            previous_version = await history_service.get_previous_version(
                app_name=app_name,
                environment=environment
            )
            
            if not previous_version:
                return {"status": "skipped", "reason": "no previous version"}
            
            # 롤백 기록 생성
            rollback_id = await history_service.create_rollback_record(
                app_name=app_name,
                environment=environment,
                target_image=previous_version.image,
                rolled_back_from=previous_version.id,
                rollback_reason="Automatic rollback to previous version",
                deployed_by="klepaas-rollbacker"
            )
            
            # 롤백 배포 수행
            payload = DeployApplicationInput(
                app_name=app_name,
                environment=Environment(environment),
                image=previous_version.image,
                replicas=previous_version.replicas,
            )
            result = await perform_deploy(payload)
            
            return {
                "status": "rolled_back",
                "rollback_id": rollback_id,
                "to": {
                    "image": previous_version.image,
                    "replicas": previous_version.replicas
                },
                "result": result
            }
            
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


async def get_deploy_status(app_name: str, environment: str) -> Dict[str, Any]:
    """배포 상태를 조회합니다."""
    try:
        history_service = get_deployment_history_service()
        
        # 최근 배포 정보 조회
        recent_versions = await history_service.get_recent_versions(
            app_name=app_name,
            environment=environment,
            limit=1
        )
        
        if not recent_versions:
            return {
                "app": app_name,
                "environment": environment,
                "status": "not_deployed",
                "ready": 0,
                "total": 0,
                "reasons": [],
                "history_count": 0,
            }
        
        latest_deployment = recent_versions[0]
        
        # Kubernetes 상태 조회 (설정이 활성화된 경우)
        settings = get_settings()
        if settings.enable_k8s_deploy and environment == "staging":
            try:
                namespace = settings.k8s_staging_namespace or "staging"
                core = get_core_v1_api()
                pods = core.list_namespaced_pod(namespace=namespace, label_selector=f"app={app_name}")
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
                    "status": latest_deployment.status,
                    "progress": latest_deployment.progress,
                    "ready": ready,
                    "total": total,
                    "reasons": reasons[:5],
                    "deployment_id": latest_deployment.id,
                    "image": latest_deployment.image,
                    "image_tag": latest_deployment.image_tag,
                    "deployed_at": latest_deployment.deployed_at.isoformat() if latest_deployment.deployed_at else None,
                    "is_rollback": latest_deployment.is_rollback
                }
            except Exception as e:
                # Kubernetes 조회 실패 시 히스토리 정보만 반환
                pass
        
        # 히스토리 기반 상태 반환
        return {
            "app": app_name,
            "environment": environment,
            "status": latest_deployment.status,
            "progress": latest_deployment.progress,
            "ready": 0,
            "total": 0,
            "reasons": [],
            "deployment_id": latest_deployment.id,
            "image": latest_deployment.image,
            "image_tag": latest_deployment.image_tag,
            "deployed_at": latest_deployment.deployed_at.isoformat() if latest_deployment.deployed_at else None,
            "is_rollback": latest_deployment.is_rollback,
            "history_count": 1
        }
        
    except Exception as e:
        return {
            "app": app_name,
            "environment": environment,
            "status": "error",
            "error": str(e),
            "ready": 0,
            "total": 0,
            "reasons": [],
            "history_count": 0
        }


async def list_recent_versions(app_name: str, environment: str, limit: int = 3) -> Dict[str, Any]:
    """최근 배포 버전들을 조회합니다."""
    try:
        history_service = get_deployment_history_service()
        
        # 최근 버전들 조회
        recent_versions = await history_service.get_recent_versions(
            app_name=app_name,
            environment=environment,
            limit=limit
        )
        
        versions = []
        for deployment in recent_versions:
            versions.append({
                "id": deployment.id,
                "image": deployment.image,
                "image_tag": deployment.image_tag,
                "image_tag_type": deployment.image_tag_type,
                "replicas": deployment.replicas,
                "status": deployment.status,
                "progress": deployment.progress,
                "deployed_at": deployment.deployed_at.isoformat() if deployment.deployed_at else None,
                "is_rollback": deployment.is_rollback,
                "deployed_by": deployment.deployed_by
            })
        
        return {
            "app": app_name,
            "environment": environment,
            "versions": versions
        }
        
    except Exception as e:
        return {
            "app": app_name,
            "environment": environment,
            "versions": [],
            "error": str(e)
        }


def _collect_waiting_reasons(app_name: str, namespace: str) -> list[str]:
    """Pod 대기 사유를 수집합니다."""
    try:
        core = get_core_v1_api()
        pods = core.list_namespaced_pod(namespace=namespace, label_selector=f"app={app_name}")
        reasons = []
        
        for pod in pods.items or []:
            for container_status in (pod.status.container_statuses or []) or []:
                state = container_status.state
                if state and state.waiting:
                    reason = state.waiting.reason or "Waiting"
                    message = state.waiting.message or ""
                    reasons.append(f"{container_status.name}:{reason} {message}".strip())
        
        return reasons
    except Exception:
        return []
