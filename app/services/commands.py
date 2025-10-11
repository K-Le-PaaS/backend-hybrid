from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from kubernetes import client
from kubernetes.client.rest import ApiException

from .deployments import DeployApplicationInput, perform_deploy
from .k8s_client import get_apps_v1_api, get_core_v1_api


class CommandRequest(BaseModel):
    command: str = Field(min_length=1)
    app_name: str = Field(default="")
    replicas: int = Field(default=1)
    lines: int = Field(default=30)
    version: str = Field(default="")


@dataclass
class CommandPlan:
    tool: str
    args: Dict[str, Any]


def _parse_environment(text: str) -> Optional[str]:
    if re.search(r"프로덕션|production", text, re.I):
        return "production"
    if re.search(r"스테이징|staging", text, re.I):
        return "staging"
    return None


def _parse_replicas(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*(개|레플리카|replicas?)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _parse_app_name(text: str) -> Optional[str]:
    # naive: word before '배포' or explicit quotes
    q = re.search(r"[\"'`](.+?)[\"'`].*배포", text)
    if q:
        return q.group(1)
    m = re.search(r"([a-z0-9-_.]+)\s*(앱|app)?\s*.*배포", text, re.I)
    if m:
        return m.group(1)
    # For non-deploy commands, extract app name more broadly
    # Handle Korean particles like '를', '을', '이', '가', '은', '는'
    m = re.search(r"([a-z0-9-_.]+)(?:[를을이가은는]|$)", text, re.I)
    if m:
        return m.group(1)
    # Fallback: extract any alphanumeric word
    m = re.search(r"([a-z0-9-_.]+)\s*(앱|app)?", text, re.I)
    if m:
        return m.group(1)
    return None


def _parse_log_lines(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*(줄|줄|lines?)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _parse_version(text: str) -> Optional[str]:
    m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
    if m:
        return f"v{m.group(1)}"
    return None


def plan_command(req: CommandRequest) -> CommandPlan:
    command = req.command.lower()
    app_name = req.app_name or "app"
    ns = "default"

    if command == "deploy":
        return CommandPlan(
            tool="deploy_application",
            args={
                "app_name": app_name,
                "environment": "staging",
                "image": f"{app_name}:latest",
                "replicas": 2,
            },
        )
    
    elif command == "scale":
        return CommandPlan(
            tool="k8s_scale_deployment",
            args={"name": app_name, "namespace": ns, "replicas": req.replicas},
        )
    
    elif command == "status":
        return CommandPlan(
            tool="k8s_get_status",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "logs":
        return CommandPlan(
            tool="k8s_get_logs",
            args={"name": app_name, "namespace": ns, "lines": req.lines},
        )
    
    elif command == "endpoint":
        return CommandPlan(
            tool="k8s_get_endpoints",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "restart":
        return CommandPlan(
            tool="k8s_restart_deployment",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "rollback":
        return CommandPlan(
            tool="k8s_rollback_deployment",
            args={"name": app_name, "namespace": ns, "version": req.version},
        )
    
    elif command == "list_pods" or command == "pods":
        return CommandPlan(
            tool="k8s_list_pods",
            args={"namespace": ns},
        )

    raise ValueError("해석할 수 없는 명령입니다.")


async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    """
    명령 실행 계획을 실제 Kubernetes API 호출로 변환하여 실행
    """
    if plan.tool == "deploy_application":
        payload = DeployApplicationInput(**plan.args)
        return await perform_deploy(payload)

    if plan.tool == "k8s_scale_deployment":
        return await _execute_scale(plan.args)

    if plan.tool == "k8s_get_status":
        return await _execute_get_status(plan.args)

    if plan.tool == "k8s_get_logs":
        return await _execute_get_logs(plan.args)

    if plan.tool == "k8s_get_endpoints":
        return await _execute_get_endpoints(plan.args)

    if plan.tool == "k8s_restart_deployment":
        return await _execute_restart(plan.args)

    if plan.tool == "k8s_rollback_deployment":
        return await _execute_rollback(plan.args)

    if plan.tool == "k8s_list_pods":
        return await _execute_list_pods(plan.args)

    raise ValueError("지원하지 않는 실행 계획입니다.")


# ========================================
# Kubernetes 명령어 실행 핸들러
# ========================================

async def _execute_get_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    배포 상태 조회 (status 명령어)
    예: "내 앱 상태 보여줘", "chat-app 상태 어때?"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        apps_v1 = get_apps_v1_api()
        
        # Deployment 정보 조회
        deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        
        # Pod 목록 조회 (Deployment의 Pod 상태 확인)
        core_v1 = get_core_v1_api()
        label_selector = f"app={name}"
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        
        # Pod 상태 정보 추출
        pod_statuses = []
        for pod in pods.items:
            pod_status = {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "ready": False,
                "restarts": 0
            }
            
            # Container 상태 체크
            if pod.status.container_statuses:
                for container_status in pod.status.container_statuses:
                    pod_status["ready"] = container_status.ready
                    pod_status["restarts"] = container_status.restart_count
                    break
            
            pod_statuses.append(pod_status)
        
        return {
            "status": "success",
            "deployment": {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": {
                    "desired": deployment.spec.replicas,
                    "current": deployment.status.replicas or 0,
                    "ready": deployment.status.ready_replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                },
                "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None,
                "created_at": deployment.metadata.creation_timestamp.isoformat() if deployment.metadata.creation_timestamp else None
            },
            "pods": pod_statuses
        }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Deployment '{name}'을 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"상태 조회 실패: {str(e)}"}


async def _execute_get_logs(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pod 로그 조회 (logs 명령어)
    예: "최신 로그 100줄 보여줘", "로그 확인"
    """
    name = args["name"]
    namespace = args["namespace"]
    lines = args.get("lines", 30)
    
    try:
        core_v1 = get_core_v1_api()
        
        # Deployment와 연결된 Pod 찾기
        label_selector = f"app={name}"
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        
        if not pods.items:
            return {"status": "error", "message": f"'{name}' 관련 Pod를 찾을 수 없습니다."}
        
        # 첫 번째 Pod의 로그 조회
        pod_name = pods.items[0].metadata.name
        logs = core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=lines
        )
        
        return {
            "status": "success",
            "pod_name": pod_name,
            "lines": lines,
            "logs": logs
        }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Pod를 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"로그 조회 실패: {str(e)}"}


async def _execute_get_endpoints(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    서비스 엔드포인트 조회 (endpoint 명령어)
    예: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        core_v1 = get_core_v1_api()
        
        # Service 조회
        try:
            service = core_v1.read_namespaced_service(name=name, namespace=namespace)
            service_type = service.spec.type
            ports = service.spec.ports
            
            endpoints = []
            
            # LoadBalancer 타입
            if service_type == "LoadBalancer":
                if service.status.load_balancer.ingress:
                    for ingress in service.status.load_balancer.ingress:
                        ip_or_host = ingress.ip or ingress.hostname
                        for port in ports:
                            endpoints.append(f"http://{ip_or_host}:{port.port}")
            
            # NodePort 타입
            elif service_type == "NodePort":
                # Node IP를 가져와서 NodePort로 접속 정보 제공
                nodes = core_v1.list_node()
                if nodes.items:
                    node_ip = nodes.items[0].status.addresses[0].address
                    for port in ports:
                        if port.node_port:
                            endpoints.append(f"http://{node_ip}:{port.node_port}")
            
            # ClusterIP 타입
            else:
                cluster_ip = service.spec.cluster_ip
                for port in ports:
                    endpoints.append(f"http://{cluster_ip}:{port.port} (클러스터 내부 전용)")
            
            return {
                "status": "success",
                "service_name": name,
                "service_type": service_type,
                "endpoints": endpoints if endpoints else ["서비스 엔드포인트를 찾을 수 없습니다."]
            }
            
        except ApiException as e:
            if e.status == 404:
                return {"status": "error", "message": f"Service '{name}'을 찾을 수 없습니다."}
            raise
        
    except Exception as e:
        return {"status": "error", "message": f"엔드포인트 조회 실패: {str(e)}"}


async def _execute_restart(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 재시작 (restart 명령어)
    예: "앱 재시작해줘", "chat-app 껐다 켜줘"
    
    구현 방법: Deployment의 Pod template에 annotation을 추가하여 재시작 트리거
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        apps_v1 = get_apps_v1_api()
        
        # Deployment 조회
        deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        
        # Pod template에 재시작 annotation 추가 (이렇게 하면 Pod가 재생성됨)
        if deployment.spec.template.metadata.annotations is None:
            deployment.spec.template.metadata.annotations = {}
        
        deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now(timezone.utc).isoformat()
        
        # Deployment 업데이트
        apps_v1.patch_namespaced_deployment(
            name=name,
            namespace=namespace,
            body=deployment
        )
        
        return {
            "status": "success",
            "message": f"Deployment '{name}'이 재시작되었습니다.",
            "deployment": name,
            "namespace": namespace
        }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Deployment '{name}'을 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"재시작 실패: {str(e)}"}


async def _execute_scale(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 스케일링 (scale 명령어)
    예: "서버 3대로 늘려줘", "chat-app 스케일 아웃"
    """
    name = args["name"]
    namespace = args["namespace"]
    replicas = args["replicas"]
    
    try:
        apps_v1 = get_apps_v1_api()
        
        # Deployment의 replicas 값만 업데이트
        body = {
            "spec": {
                "replicas": replicas
            }
        }
        
        apps_v1.patch_namespaced_deployment_scale(
            name=name,
            namespace=namespace,
            body=body
        )
        
        return {
            "status": "success",
            "message": f"Deployment '{name}'의 replicas를 {replicas}개로 변경했습니다.",
            "deployment": name,
            "replicas": replicas
        }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Deployment '{name}'을 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"스케일링 실패: {str(e)}"}


async def _execute_rollback(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 롤백 (rollback 명령어)
    예: "v1.1 버전으로 롤백해줘", "이전 배포로 되돌려"
    """
    name = args["name"]
    namespace = args["namespace"]
    version = args.get("version")
    
    try:
        apps_v1 = get_apps_v1_api()
        
        if version:
            # 특정 버전으로 롤백 (이미지 태그 변경)
            deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            
            # 첫 번째 컨테이너의 이미지를 변경
            if deployment.spec.template.spec.containers:
                current_image = deployment.spec.template.spec.containers[0].image
                image_base = current_image.rsplit(":", 1)[0]  # 태그 제거
                new_image = f"{image_base}:{version}"
                
                deployment.spec.template.spec.containers[0].image = new_image
                
                apps_v1.patch_namespaced_deployment(
                    name=name,
                    namespace=namespace,
                    body=deployment
                )
                
                return {
                    "status": "success",
                    "message": f"Deployment '{name}'을 {version} 버전으로 롤백했습니다.",
                    "deployment": name,
                    "version": version,
                    "image": new_image
                }
        else:
            # 이전 ReplicaSet으로 롤백 (kubectl rollout undo와 동일)
            # Kubernetes API는 직접적인 undo를 지원하지 않으므로, 이전 ReplicaSet을 찾아서 이미지를 변경
            return {
                "status": "error",
                "message": "버전을 명시해주세요. 예: 'v1.0으로 롤백'"
            }
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Deployment '{name}'을 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"롤백 실패: {str(e)}"}


async def _execute_list_pods(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    모든 파드 목록 조회 (list_pods 명령어)
    예: "모든 파드 조회해줘", "파드 목록 보여줘"
    """
    namespace = args.get("namespace", "default")
    
    try:
        core_v1 = get_core_v1_api()
        
        # 네임스페이스의 모든 파드 조회
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        
        pod_list = []
        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "ready": False,
                "restarts": 0,
                "age": None,
                "node": pod.spec.node_name if pod.spec else None
            }
            
            # Container 상태 체크
            if pod.status.container_statuses:
                ready_count = 0
                total_count = len(pod.status.container_statuses)
                total_restarts = 0
                
                for container_status in pod.status.container_statuses:
                    if container_status.ready:
                        ready_count += 1
                    total_restarts += container_status.restart_count
                
                pod_info["ready"] = f"{ready_count}/{total_count}"
                pod_info["restarts"] = total_restarts
            
            # Pod 생성 시간 계산
            if pod.metadata.creation_timestamp:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                age = now - pod.metadata.creation_timestamp
                pod_info["age"] = str(age).split('.')[0]  # 초 단위 제거
            
            pod_list.append(pod_info)
        
        return {
            "status": "success",
            "namespace": namespace,
            "total_pods": len(pod_list),
            "pods": pod_list
        }
        
    except ApiException as e:
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"파드 목록 조회 실패: {str(e)}"}


