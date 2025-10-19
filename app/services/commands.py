from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from kubernetes import client
from kubernetes.client.rest import ApiException

from .deployments import DeployApplicationInput, perform_deploy
from .k8s_client import get_apps_v1_api, get_core_v1_api, get_networking_v1_api


class CommandRequest(BaseModel):
    command: str = Field(min_length=1)
    # 리소스 타입별 명확한 필드 분리
    pod_name: str = Field(default="")          # Pod 관련 명령어용
    deployment_name: str = Field(default="")   # Deployment 관련 명령어용
    service_name: str = Field(default="")      # Service 관련 명령어용
    # 기타 파라미터들
    replicas: int = Field(default=1)
    lines: int = Field(default=30, ge=1, le=100)  # 최소 1줄, 최대 100줄
    version: str = Field(default="")
    namespace: str = Field(default="default")
    previous: bool = Field(default=False)  # 이전 파드 로그 여부
    # NCP 롤백 관련 필드
    github_owner: str = Field(default="")      # GitHub 저장소 소유자
    github_repo: str = Field(default="")       # GitHub 저장소 이름
    target_commit_sha: str = Field(default="") # 롤백할 커밋 SHA
    steps_back: int = Field(default=0, ge=0)   # 몇 번 전으로 롤백할지


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
    ns = req.namespace or "default"
    
    # 리소스 타입별로 적절한 이름 선택
    def get_resource_name():
        # 리소스 타입별 필드 사용
        if command in ("status", "logs", "restart") and req.pod_name:
            return req.pod_name
        elif command in ("scale", "rollback", "deploy", "get_deployment") and req.deployment_name:
            return req.deployment_name
        elif command in ("endpoint", "get_service") and req.service_name:
            return req.service_name
        # 기본값
        else:
            return "app"
    
    resource_name = get_resource_name()

    if command == "deploy":
        return CommandPlan(
            tool="deploy_application",
            args={
                "app_name": resource_name,
                "environment": "staging",
                "image": f"{resource_name}:latest",
                "replicas": 2,
            },
        )
    
    elif command == "scale":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.deployment_name or req.deployment_name.strip() == "":
            raise ValueError("스케일링 명령어에는 배포 이름을 명시해야 합니다. 예: 'nginx-deployment 3개로 늘려줘'")
        return CommandPlan(
            tool="k8s_scale_deployment",
            args={"name": resource_name, "namespace": ns, "replicas": req.replicas},
        )
    
    elif command == "status":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.pod_name or req.pod_name.strip() == "":
            raise ValueError("상태 확인 명령어에는 리소스 이름을 명시해야 합니다. 예: 'chat-app 상태 보여줘'")
        return CommandPlan(
            tool="k8s_get_status",
            args={"name": resource_name, "namespace": ns},
        )
    
    elif command == "logs":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.pod_name or req.pod_name.strip() == "":
            raise ValueError("로그 조회 명령어에는 리소스 이름을 명시해야 합니다. 예: 'chat-app 로그 보여줘'")
        return CommandPlan(
            tool="k8s_get_logs",
            args={
                "name": resource_name, 
                "namespace": req.namespace or ns, 
                "lines": req.lines,
                "previous": req.previous
            },
        )
    
    elif command == "endpoint":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.service_name or req.service_name.strip() == "":
            raise ValueError("엔드포인트 조회 명령어에는 서비스 이름을 명시해야 합니다. 예: 'nginx-service 엔드포인트 보여줘'")
        return CommandPlan(
            tool="k8s_get_endpoints",
            args={"name": resource_name, "namespace": req.namespace or ns},
        )
    
    elif command == "restart":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.pod_name or req.pod_name.strip() == "":
            raise ValueError("재시작 명령어에는 리소스 이름을 명시해야 합니다. 예: 'chat-app 재시작해줘'")
        return CommandPlan(
            tool="k8s_restart_deployment",
            args={"name": resource_name, "namespace": req.namespace or ns},
        )
    
    elif command == "rollback":
        # NCP 파이프라인 롤백 (deployment_histories 기반)
        if not req.github_owner or not req.github_repo:
            raise ValueError("NCP 롤백 명령어에는 GitHub 저장소 정보가 필요합니다. 예: 'owner/repo를 3번 전으로 롤백'")
        return CommandPlan(
            tool="rollback_deployment",
            args={
                "owner": req.github_owner,
                "repo": req.github_repo,
                "target_commit_sha": req.target_commit_sha,
                "steps_back": req.steps_back
            },
        )
    
    elif command == "list_pods" or command == "pods":
        return CommandPlan(
            tool="k8s_list_pods",
            args={"namespace": ns},
        )
    
    elif command == "overview":
        return CommandPlan(
            tool="k8s_get_overview",
            args={"namespace": req.namespace or ns},
        )
    
    elif command == "list_deployments":
        return CommandPlan(
            tool="k8s_list_all_deployments",
            args={},
        )
    
    elif command == "list_services":
        return CommandPlan(
            tool="k8s_list_all_services",
            args={},
        )
    
    elif command == "list_ingresses":
        return CommandPlan(
            tool="k8s_list_all_ingresses",
            args={},
        )
    
    elif command == "list_namespaces":
        return CommandPlan(
            tool="k8s_list_namespaces",
            args={},
        )
    
    elif command == "list_apps":
        return CommandPlan(
            tool="k8s_list_deployments",
            args={"namespace": ns},
        )
    
    elif command == "get_service":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.service_name or req.service_name.strip() == "":
            raise ValueError("Service 조회 명령어에는 서비스 이름을 명시해야 합니다. 예: 'nginx-service 정보 보여줘'")
        return CommandPlan(
            tool="k8s_get_service",
            args={"name": resource_name, "namespace": ns},
        )
    
    elif command == "get_deployment":
        # 리소스 이름이 명시되지 않았을 때 유효성 검사
        if not req.deployment_name or req.deployment_name.strip() == "":
            raise ValueError("Deployment 조회 명령어에는 배포 이름을 명시해야 합니다. 예: 'nginx-deployment 정보 보여줘'")
        return CommandPlan(
            tool="k8s_get_deployment",
            args={"name": resource_name, "namespace": ns},
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

    if plan.tool == "rollback_deployment":
        return await _execute_ncp_rollback(plan.args)

    if plan.tool == "k8s_list_pods":
        return await _execute_list_pods(plan.args)

    if plan.tool == "k8s_get_overview":
        return await _execute_get_overview(plan.args)

    if plan.tool == "k8s_list_all_deployments":
        return await _execute_list_all_deployments(plan.args)

    if plan.tool == "k8s_list_all_services":
        return await _execute_list_all_services(plan.args)

    if plan.tool == "k8s_list_all_ingresses":
        return await _execute_list_all_ingresses(plan.args)

    if plan.tool == "k8s_list_namespaces":
        return await _execute_list_namespaces(plan.args)

    if plan.tool == "k8s_list_deployments":
        return await _execute_list_deployments(plan.args)

    if plan.tool == "k8s_get_service":
        return await _execute_get_service(plan.args)

    if plan.tool == "k8s_get_deployment":
        return await _execute_get_deployment(plan.args)

    raise ValueError("지원하지 않는 실행 계획입니다.")


# ========================================
# 공통 헬퍼 함수
# ========================================

def _format_pod_statuses(pods: list, include_labels: bool = True, include_creation_time: bool = True, include_namespace: bool = False, include_age: bool = False) -> list:
    """
    Pod 목록을 상태 정보로 포맷팅하는 공통 헬퍼 함수
    
    Args:
        pods: Kubernetes Pod 객체 목록
        include_labels: 라벨 정보 포함 여부
        include_creation_time: 생성 시간 정보 포함 여부
        include_namespace: 네임스페이스 정보 포함 여부
        include_age: 나이 정보 포함 여부
    
    Returns:
        포맷팅된 Pod 상태 정보 목록
    """
    pod_statuses = []
    for pod in pods:
        pod_status = {
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "ready": False,
            "restarts": 0,
            "node": pod.spec.node_name if pod.spec else None,
        }
        
        # 조건부 필드 추가
        if include_namespace:
            pod_status["namespace"] = pod.metadata.namespace
        if include_labels:
            pod_status["labels"] = pod.metadata.labels or {}
        if include_creation_time:
            pod_status["creation_timestamp"] = pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
        if include_age:
            pod_status["age"] = None
            if pod.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age = now - pod.metadata.creation_timestamp
                pod_status["age"] = str(age).split('.')[0]  # 초 단위 제거
        
        # Container 상태 체크
        if pod.status.container_statuses:
            ready_count = 0
            total_count = len(pod.status.container_statuses)
            total_restarts = 0
            
            for container_status in pod.status.container_statuses:
                if container_status.ready:
                    ready_count += 1
                total_restarts += container_status.restart_count
            
            pod_status["ready"] = f"{ready_count}/{total_count}"
            pod_status["restarts"] = total_restarts
        
        pod_statuses.append(pod_status)
    
    return pod_statuses


# ========================================
# Kubernetes 명령어 실행 핸들러
# ========================================

async def _execute_get_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pod 상태 조회 (status 명령어)
    예: "내 앱 상태 보여줘", "chat-app 상태 어때?"
    "app" 호칭이 들어오면 라벨 셀렉터 app=<name>으로 Pod 조회
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        core_v1 = get_core_v1_api()
        
        # Pod 목록 조회 (라벨 셀렉터 사용: app=<name>)
        label_selector = f"app={name}"
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        
        if not pods.items:
            return {
                "status": "error", 
                "message": f"라벨 'app={name}'로 Pod를 찾을 수 없습니다. 앱 이름을 확인해주세요."
            }
        
        # Pod 상태 정보 추출 (헬퍼 함수 사용)
        pod_statuses = _format_pod_statuses(pods.items, include_labels=True, include_creation_time=True)
        
        return {
            "status": "success",
            "message": f"라벨 'app={name}'로 {len(pod_statuses)}개 Pod 조회 완료",
            "label_selector": label_selector,
            "namespace": namespace,
            "total_pods": len(pod_statuses),
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
    예: "최신 로그 100줄 보여줘", "로그 확인", "이전 로그 확인해줘"
    """
    name = args["name"]
    namespace = args["namespace"]
    lines = args.get("lines", 30)
    previous = args.get("previous", False)  # 이전 파드 로그 여부
    
    try:
        core_v1 = get_core_v1_api()
        
        # Step 1: 앱 이름으로 실제 파드 이름 찾아오기 (레이블 셀렉터 활용)
        # 먼저 app 레이블로 시도
        label_selector = f"app={name}"
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        
        # app 레이블로 찾을 수 없으면 파드 이름으로 직접 찾기
        if not pods.items:
            try:
                pod = core_v1.read_namespaced_pod(name=name, namespace=namespace)
                pods.items = [pod]  # 단일 파드를 리스트 형태로 변환
            except ApiException as e:
                if e.status == 404:
                    # 네임스페이스 존재 여부 확인
                    try:
                        core_v1.read_namespace(name=namespace)
                        # 네임스페이스는 존재하지만 파드가 없음
                        return {"status": "error", "message": f"라벨 'app={name}'로 Pod를 찾을 수 없습니다. 앱 이름을 확인해주세요."}
                    except ApiException:
                        # 네임스페이스 자체가 존재하지 않음
                        return {"status": "error", "message": f"네임스페이스 '{namespace}'가 존재하지 않습니다. 네임스페이스 이름을 확인해주세요."}
                else:
                    return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
        
        # 첫 번째 Pod 선택
        pod = pods.items[0]
        pod_name = pod.metadata.name
        
        # Step 3: CrashLoopBackOff 상태 확인 및 대응
        if pod.status.phase == "Failed" or (pod.status.container_statuses and 
            any(cs.state.waiting and cs.state.waiting.reason == "CrashLoopBackOff" 
                for cs in pod.status.container_statuses)):
            
            # CrashLoopBackOff 상태일 때 --previous 옵션으로 이전 파드 로그 조회
            try:
                logs = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=lines,
                    previous=True  # --previous 옵션
                )
                
                return {
                    "status": "success",
                    "pod_name": pod_name,
                    "lines": lines,
                    "logs": logs,
                    "warning": "앱이 CrashLoopBackOff 상태입니다. 원인 파악을 위해 직전에 실패했던 파드의 로그를 보여드립니다.",
                    "pod_status": pod.status.phase
                }
            except ApiException as prev_e:
                # 이전 로그도 없으면 현재 로그라도 보여주기
                logs = core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=lines
                )
                return {
                    "status": "success",
                    "pod_name": pod_name,
                    "lines": lines,
                    "logs": logs,
                    "warning": "앱이 CrashLoopBackOff 상태이지만 이전 로그를 찾을 수 없어 현재 로그를 보여드립니다.",
                    "pod_status": pod.status.phase
                }
        
        # Step 2: kubectl logs 명령어 조립하기 (정상 상태)
        # follow 옵션은 실시간 로그이므로 API에서는 지원하지 않음
        # 대신 최신 로그를 반환하고 follow=True일 때는 안내 메시지 추가
        logs = core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=lines
        )
        
        response = {
            "status": "success",
            "pod_name": pod_name,
            "lines": lines,
            "logs": logs,
            "pod_status": pod.status.phase
        }
        
        return response
        
    except ApiException as e:
        if e.status == 404:
            return {"status": "error", "message": f"Pod를 찾을 수 없습니다."}
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"로그 조회 실패: {str(e)}"}


async def _execute_get_endpoints(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    서비스 엔드포인트 조회 - Ingress 도메인만 반환 (endpoint 명령어)
    예: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        networking_v1 = get_networking_v1_api()
        
        # Ingress 조회 - 해당 서비스와 연결된 Ingress 찾기
        try:
            # 네임스페이스의 모든 Ingress 조회
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
            
            for ingress in ingresses.items:
                # Ingress 규칙에서 해당 서비스를 백엔드로 사용하는지 확인
                for rule in ingress.spec.rules or []:
                    for path in rule.http.paths or []:
                        if hasattr(path.backend.service, 'name') and path.backend.service.name == name:
                            # 도메인 추출
                            host = rule.host
                            if host:
                                # HTTPS 도메인 반환
                                domain = f"https://{host}"
                                return {
                                    "status": "success",
                                    "service_name": name,
                                    "namespace": namespace,
                                    "endpoints": [domain],
                                    "message": "Ingress 도메인으로 접속 가능합니다."
                                }
            
            # Ingress를 찾지 못한 경우
            return {
                "status": "error",
                "service_name": name,
                "namespace": namespace,
                "message": f"'{name}' 서비스에 대한 Ingress 도메인이 설정되지 않았습니다. 도메인 설정이 필요합니다."
            }
            
        except ApiException as e:
            if e.status == 404:
                return {
                    "status": "error", 
                    "service_name": name,
                    "namespace": namespace,
                    "message": f"'{name}' 서비스에 대한 Ingress를 찾을 수 없습니다. 도메인 설정이 필요합니다."
                }
            raise
        
    except Exception as e:
        return {
            "status": "error",
            "service_name": name,
            "namespace": namespace,
            "message": f"엔드포인트 조회 실패: {str(e)}"
        }


async def _execute_restart(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 재시작 (restart 명령어)
    예: "앱 재시작해줘", "chat-app 껐다 켜줘"
    
    "app" 호칭이 들어오면 라벨 셀렉터로 Pod를 찾아 해당 Deployment 재시작
    구현 방법: kubectl rollout restart deployment 방식으로 Pod 재시작
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        apps_v1 = get_apps_v1_api()
        core_v1 = get_core_v1_api()
        
        # Deployment 존재 확인 - 먼저 직접 이름으로 시도
        deployment_name = name
        try:
            deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                # "app" 호칭인 경우 라벨로 Pod를 찾아 Deployment 이름 추출
                try:
                    label_selector = f"app={name}"
                    pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
                    
                    if not pods.items:
                        return {
                            "status": "error",
                            "deployment": name,
                            "namespace": namespace,
                            "message": f"라벨 'app={name}'로 Pod를 찾을 수 없습니다. 앱 이름을 확인해주세요."
                        }
                    
                    # Pod에서 Deployment 이름 추출 (일반적으로 app 라벨과 동일)
                    pod = pods.items[0]
                    if pod.metadata.labels and "app" in pod.metadata.labels:
                        deployment_name = pod.metadata.labels["app"]
                        deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
                    else:
                        return {
                            "status": "error",
                            "deployment": name,
                            "namespace": namespace,
                            "message": f"Pod에서 Deployment 정보를 찾을 수 없습니다."
                        }
                except ApiException:
                    return {
                        "status": "error",
                        "deployment": name,
                        "namespace": namespace,
                        "message": f"Deployment '{name}'을 찾을 수 없습니다. 앱 이름을 확인해주세요."
                    }
            else:
                raise
        
        # kubectl rollout restart deployment 구현
        # Pod template에 재시작 annotation 추가하여 Pod 재생성 트리거
        if deployment.spec.template.metadata.annotations is None:
            deployment.spec.template.metadata.annotations = {}
        
        # 현재 시간으로 재시작 annotation 설정
        deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.now(timezone.utc).isoformat()
        
        # Deployment 업데이트 (이것이 kubectl rollout restart와 동일한 효과)
        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=deployment
        )
        
        return {
            "status": "success",
            "message": f"Deployment '{deployment_name}'이 재시작되었습니다. Pod들이 새로 생성됩니다.",
            "deployment": deployment_name,
            "namespace": namespace,
            "restart_method": "kubectl rollout restart",
            "label_selector": f"app={name}" if deployment_name != name else None
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": "error",
                "deployment": name,
                "namespace": namespace,
                "message": f"라벨 'app={name}'로 Pod 또는 Deployment를 찾을 수 없습니다. 앱 이름을 확인해주세요."
            }
        return {
            "status": "error",
            "deployment": name,
            "namespace": namespace,
            "message": f"Kubernetes API 오류: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "deployment": name,
            "namespace": namespace,
            "message": f"재시작 실패: {str(e)}"
        }


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


async def _execute_ncp_rollback(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    NCP 파이프라인 롤백 (ncp_rollback 명령어)
    deployment_histories 테이블 기반으로 이전 배포로 롤백
    예: "owner/repo를 3번 전으로 롤백", "owner/repo를 커밋 abc1234로 롤백"
    """
    from .rollback import rollback_to_commit, rollback_to_previous
    from ..database import get_db

    owner = args["owner"]
    repo = args["repo"]
    target_commit_sha = args.get("target_commit_sha", "")
    steps_back = args.get("steps_back", 0)
    user_id = args.get("user_id", "nlp_user")  # JWT에서 전달된 user_id 사용, 없으면 기본값

    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        # 커밋 SHA가 지정되었으면 해당 커밋으로 롤백
        if target_commit_sha:
            result = await rollback_to_commit(
                owner=owner,
                repo=repo,
                target_commit_sha=target_commit_sha,
                db=db,
                user_id=user_id  # 실제 사용자 ID 사용
            )

            return {
                "status": "success",
                "action": "ncp_rollback_to_commit",
                "message": f"{owner}/{repo}를 커밋 {target_commit_sha[:7]}로 롤백했습니다.",
                "result": result
            }

        # steps_back이 지정되었으면 N번 전으로 롤백
        elif steps_back > 0:
            result = await rollback_to_previous(
                owner=owner,
                repo=repo,
                steps_back=steps_back,
                db=db,
                user_id=user_id  # 실제 사용자 ID 사용
            )

            return {
                "status": "success",
                "action": "ncp_rollback_to_previous",
                "message": f"{owner}/{repo}를 {steps_back}번 전 배포로 롤백했습니다.",
                "result": result
            }

        else:
            # 기본값: 1번 전으로 롤백
            result = await rollback_to_previous(
                owner=owner,
                repo=repo,
                steps_back=1,
                db=db,
                user_id=user_id  # 실제 사용자 ID 사용
            )

            return {
                "status": "success",
                "action": "ncp_rollback_to_previous",
                "message": f"{owner}/{repo}를 이전 배포로 롤백했습니다.",
                "result": result
            }

    except Exception as e:
        return {
            "status": "error",
            "action": "ncp_rollback",
            "message": f"NCP 롤백 실패: {str(e)}",
            "owner": owner,
            "repo": repo
        }


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
        
        # Pod 상태 정보 추출 (헬퍼 함수 사용)
        pod_list = _format_pod_statuses(pods.items, include_labels=False, include_creation_time=False, include_namespace=True, include_age=True)
        
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


async def _execute_get_overview(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    통합 대시보드 조회 (overview 명령어)
    예: "전체 상황 보여줘", "대시보드 확인", "모든 리소스 상태"
    
    Deployment, Pod, Service, Ingress 모든 리소스를 한번에 조회
    """
    namespace = args.get("namespace", "default")
    
    try:
        apps_v1 = get_apps_v1_api()
        core_v1 = get_core_v1_api()
        networking_v1 = get_networking_v1_api()
        
        overview_data = {
            "namespace": namespace,
            "deployments": [],
            "pods": [],
            "services": [],
            "ingresses": []
        }
        
        # 1. Deployments 조회
        try:
            deployments = apps_v1.list_namespaced_deployment(namespace=namespace)
            for deployment in deployments.items:
                deployment_info = {
                    "name": deployment.metadata.name,
                    "replicas": {
                        "desired": deployment.spec.replicas,
                        "current": deployment.status.replicas or 0,
                        "ready": deployment.status.ready_replicas or 0,
                        "available": deployment.status.available_replicas or 0,
                    },
                    "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None,
                    "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
                }
                overview_data["deployments"].append(deployment_info)
        except ApiException as e:
            if e.status != 404:  # 404는 네임스페이스가 없는 경우
                raise
        
        # 2. Pods 조회
        try:
            pods = core_v1.list_namespaced_pod(namespace=namespace)
            # Pod 상태 정보 추출 (헬퍼 함수 사용)
            overview_data["pods"] = _format_pod_statuses(pods.items, include_labels=False, include_creation_time=False, include_namespace=False, include_age=False)
        except ApiException as e:
            if e.status != 404:
                raise
        
        # 3. Services 조회
        try:
            services = core_v1.list_namespaced_service(namespace=namespace)
            for service in services.items:
                service_info = {
                    "name": service.metadata.name,
                    "type": service.spec.type,
                    "cluster_ip": service.spec.cluster_ip,
                    "ports": []
                }
                
                # Service 포트 정보
                if service.spec.ports:
                    for port in service.spec.ports:
                        port_info = {
                            "port": port.port,
                            "target_port": port.target_port,
                            "protocol": port.protocol or "TCP"
                        }
                        if service.spec.type == "NodePort" and port.node_port:
                            port_info["node_port"] = port.node_port
                        service_info["ports"].append(port_info)
                
                overview_data["services"].append(service_info)
        except ApiException as e:
            if e.status != 404:
                raise
        
        # 4. Ingresses 조회
        try:
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
            for ingress in ingresses.items:
                ingress_info = {
                    "name": ingress.metadata.name,
                    "hosts": [],
                    "addresses": []
                }
                
                # Ingress 호스트 정보
                if ingress.spec.rules:
                    for rule in ingress.spec.rules:
                        if rule.host:
                            ingress_info["hosts"].append(rule.host)
                
                # Ingress 주소 정보
                if ingress.status.load_balancer.ingress:
                    for lb_ingress in ingress.status.load_balancer.ingress:
                        address = lb_ingress.ip or lb_ingress.hostname
                        if address:
                            ingress_info["addresses"].append(address)
                
                overview_data["ingresses"].append(ingress_info)
        except ApiException as e:
            if e.status != 404:
                raise
        
        # 요약 통계
        summary = {
            "total_deployments": len(overview_data["deployments"]),
            "total_pods": len(overview_data["pods"]),
            "total_services": len(overview_data["services"]),
            "total_ingresses": len(overview_data["ingresses"]),
            "running_pods": len([p for p in overview_data["pods"] if p["phase"] == "Running"]),
            "ready_deployments": len([d for d in overview_data["deployments"] if d["status"] == "Running"])
        }
        
        return {
            "status": "success",
            "message": f"'{namespace}' 네임스페이스 통합 대시보드 조회 완료",
            "summary": summary,
            "resources": overview_data
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": "error",
                "namespace": namespace,
                "message": f"네임스페이스 '{namespace}'가 존재하지 않습니다. 네임스페이스 이름을 확인해주세요."
            }
        return {
            "status": "error",
            "namespace": namespace,
            "message": f"통합 대시보드 조회 실패: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "namespace": namespace,
            "message": f"통합 대시보드 조회 실패: {str(e)}"
        }


async def _execute_list_all_deployments(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    모든 네임스페이스의 Deployment 목록 조회 (list_deployments 명령어)
    예: "모든 Deployment 조회해줘", "전체 앱 목록 보여줘"
    """
    try:
        apps_v1 = get_apps_v1_api()
        
        # 모든 네임스페이스의 Deployment 조회
        deployments = apps_v1.list_deployment_for_all_namespaces()
        
        deployment_list = []
        for deployment in deployments.items:
            deployment_info = {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": {
                    "desired": deployment.spec.replicas,
                    "current": deployment.status.replicas or 0,
                    "ready": deployment.status.ready_replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                },
                "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None,
                "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
            }
            deployment_list.append(deployment_info)
        
        return {
            "status": "success",
            "message": "모든 네임스페이스의 Deployment 목록 조회 완료",
            "total_deployments": len(deployment_list),
            "deployments": deployment_list
        }
        
    except Exception as e:
        return {"status": "error", "message": f"전체 Deployment 조회 실패: {str(e)}"}


async def _execute_list_all_services(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    모든 네임스페이스의 Service 목록 조회 (list_services 명령어)
    예: "모든 Service 조회해줘", "전체 서비스 목록 보여줘"
    """
    try:
        core_v1 = get_core_v1_api()
        
        # 모든 네임스페이스의 Service 조회
        services = core_v1.list_service_for_all_namespaces()
        
        service_list = []
        for service in services.items:
            service_info = {
                "name": service.metadata.name,
                "namespace": service.metadata.namespace,
                "type": service.spec.type,
                "cluster_ip": service.spec.cluster_ip,
                "ports": []
            }
            
            # Service 포트 정보
            if service.spec.ports:
                for port in service.spec.ports:
                    port_info = {
                        "port": port.port,
                        "target_port": port.target_port,
                        "protocol": port.protocol or "TCP"
                    }
                    if service.spec.type == "NodePort" and port.node_port:
                        port_info["node_port"] = port.node_port
                    service_info["ports"].append(port_info)
            
            service_list.append(service_info)
        
        return {
            "status": "success",
            "message": "모든 네임스페이스의 Service 목록 조회 완료",
            "total_services": len(service_list),
            "services": service_list
        }
        
    except Exception as e:
        return {"status": "error", "message": f"전체 Service 조회 실패: {str(e)}"}


async def _execute_list_all_ingresses(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    모든 네임스페이스의 Ingress 목록 조회 (list_ingresses 명령어)
    예: "모든 도메인 조회해줘", "전체 Ingress 목록 보여줘"
    """
    try:
        networking_v1 = get_networking_v1_api()
        
        # 모든 네임스페이스의 Ingress 조회
        ingresses = networking_v1.list_ingress_for_all_namespaces()
        
        ingress_list = []
        for ingress in ingresses.items:
            ingress_info = {
                "name": ingress.metadata.name,
                "namespace": ingress.metadata.namespace,
                "hosts": [],
                "addresses": []
            }
            
            # Ingress 호스트 정보
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.host:
                        ingress_info["hosts"].append(rule.host)
            
            # Ingress 주소 정보
            if ingress.status.load_balancer.ingress:
                for lb_ingress in ingress.status.load_balancer.ingress:
                    address = lb_ingress.ip or lb_ingress.hostname
                    if address:
                        ingress_info["addresses"].append(address)
            
            ingress_list.append(ingress_info)
        
        return {
            "status": "success",
            "message": "모든 네임스페이스의 Ingress 목록 조회 완료",
            "total_ingresses": len(ingress_list),
            "ingresses": ingress_list
        }
        
    except Exception as e:
        return {"status": "error", "message": f"전체 Ingress 조회 실패: {str(e)}"}


async def _execute_list_namespaces(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    클러스터의 모든 네임스페이스 목록 조회 (list_namespaces 명령어)
    예: "모든 네임스페이스 조회해줘", "네임스페이스 목록 보여줘"
    """
    try:
        core_v1 = get_core_v1_api()
        
        # 모든 네임스페이스 조회
        namespaces = core_v1.list_namespace()
        
        namespace_list = []
        for namespace in namespaces.items:
            namespace_info = {
                "name": namespace.metadata.name,
                "status": namespace.status.phase,
                "age": None
            }
            
            # 네임스페이스 생성 시간 계산
            if namespace.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age = now - namespace.metadata.creation_timestamp
                namespace_info["age"] = str(age).split('.')[0]  # 초 단위 제거
            
            namespace_list.append(namespace_info)
        
        return {
            "status": "success",
            "message": "모든 네임스페이스 목록 조회 완료",
            "total_namespaces": len(namespace_list),
            "namespaces": namespace_list
        }
        
    except Exception as e:
        return {"status": "error", "message": f"네임스페이스 목록 조회 실패: {str(e)}"}


async def _execute_list_deployments(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    네임스페이스의 모든 Deployment 목록 조회 (list_apps 명령어)
    예: "test 네임스페이스 앱 목록 보여줘", "default 네임스페이스 모든 앱 확인"
    """
    namespace = args.get("namespace", "default")
    
    try:
        apps_v1 = get_apps_v1_api()
        
        # 네임스페이스의 모든 Deployment 조회
        deployments = apps_v1.list_namespaced_deployment(namespace=namespace)
        
        deployment_list = []
        for deployment in deployments.items:
            deployment_info = {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": {
                    "desired": deployment.spec.replicas,
                    "current": deployment.status.replicas or 0,
                    "ready": deployment.status.ready_replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                },
                "image": deployment.spec.template.spec.containers[0].image if deployment.spec.template.spec.containers else None,
                "age": None,
                "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
            }
            
            # Deployment 생성 시간 계산
            if deployment.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age = now - deployment.metadata.creation_timestamp
                deployment_info["age"] = str(age).split('.')[0]  # 초 단위 제거
            
            deployment_list.append(deployment_info)
        
        return {
            "status": "success",
            "namespace": namespace,
            "total_deployments": len(deployment_list),
            "deployments": deployment_list
        }
        
    except ApiException as e:
        return {"status": "error", "message": f"Kubernetes API 오류: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"Deployment 목록 조회 실패: {str(e)}"}


async def _execute_get_service(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Service 단일 조회 (get_service 명령어)
    예: "nginx-service 정보 보여줘", "frontend 서비스 상세 확인"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        core_v1 = get_core_v1_api()
        
        # Service 정보 조회
        service = core_v1.read_namespaced_service(name=name, namespace=namespace)
        
        # Service 상세 정보 구성
        service_info = {
            "name": service.metadata.name,
            "namespace": service.metadata.namespace,
            "type": service.spec.type,
            "cluster_ip": service.spec.cluster_ip,
            "external_ips": service.spec.external_i_ps or [],
            "session_affinity": service.spec.session_affinity,
            "ports": [],
            "selector": service.spec.selector or {},
            "labels": service.metadata.labels or {},
            "annotations": service.metadata.annotations or {},
            "creation_timestamp": service.metadata.creation_timestamp.isoformat() if service.metadata.creation_timestamp else None
        }
        
        # Service 포트 정보
        if service.spec.ports:
            for port in service.spec.ports:
                port_info = {
                    "name": port.name,
                    "port": port.port,
                    "target_port": port.target_port,
                    "protocol": port.protocol or "TCP"
                }
                if service.spec.type == "NodePort" and port.node_port:
                    port_info["node_port"] = port.node_port
                if service.spec.type == "LoadBalancer":
                    port_info["node_port"] = port.node_port
                service_info["ports"].append(port_info)
        
        # LoadBalancer 상태 정보
        if service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
            service_info["load_balancer"] = {
                "ingress": []
            }
            for lb_ingress in service.status.load_balancer.ingress:
                ingress_info = {
                    "ip": lb_ingress.ip,
                    "hostname": lb_ingress.hostname
                }
                service_info["load_balancer"]["ingress"].append(ingress_info)
        
        # 연결된 Endpoints 확인
        try:
            endpoints = core_v1.read_namespaced_endpoints(name=name, namespace=namespace)
            if endpoints.subsets:
                service_info["endpoints"] = {
                    "total": len(endpoints.subsets),
                    "addresses": []
                }
                for subset in endpoints.subsets:
                    for address in subset.addresses:
                        service_info["endpoints"]["addresses"].append({
                            "ip": address.ip,
                            "target_ref": {
                                "kind": address.target_ref.kind if address.target_ref else None,
                                "name": address.target_ref.name if address.target_ref else None,
                                "namespace": address.target_ref.namespace if address.target_ref else None
                            } if address.target_ref else None
                        })
            else:
                service_info["endpoints"] = {
                    "total": 0,
                    "addresses": [],
                    "note": "연결된 Pod가 없습니다."
                }
        except ApiException:
            service_info["endpoints"] = {
                "total": 0,
                "addresses": [],
                "note": "Endpoints 정보를 조회할 수 없습니다."
            }
        
        return {
            "status": "success",
            "message": f"Service '{name}' 상세 정보 조회 완료",
            "service": service_info
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": "error",
                "service_name": name,
                "namespace": namespace,
                "message": f"Service '{name}'을 찾을 수 없습니다. 서비스 이름을 확인해주세요."
            }
        return {
            "status": "error",
            "service_name": name,
            "namespace": namespace,
            "message": f"Kubernetes API 오류: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "service_name": name,
            "namespace": namespace,
            "message": f"Service 조회 실패: {str(e)}"
        }


async def _execute_get_deployment(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 단일 조회 (get_deployment 명령어)
    예: "nginx-deployment 정보 보여줘", "frontend 앱 상세 확인"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        apps_v1 = get_apps_v1_api()
        core_v1 = get_core_v1_api()
        
        # Deployment 정보 조회
        deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        
        # Deployment 상세 정보 구성
        deployment_info = {
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "labels": deployment.metadata.labels or {},
            "annotations": deployment.metadata.annotations or {},
            "creation_timestamp": deployment.metadata.creation_timestamp.isoformat() if deployment.metadata.creation_timestamp else None,
            "replicas": {
                "desired": deployment.spec.replicas,
                "current": deployment.status.replicas or 0,
                "ready": deployment.status.ready_replicas or 0,
                "available": deployment.status.available_replicas or 0,
                "unavailable": deployment.status.unavailable_replicas or 0
            },
            "strategy": {
                "type": deployment.spec.strategy.type,
                "rolling_update": {
                    "max_unavailable": str(deployment.spec.strategy.rolling_update.max_unavailable) if deployment.spec.strategy.rolling_update.max_unavailable else None,
                    "max_surge": str(deployment.spec.strategy.rolling_update.max_surge) if deployment.spec.strategy.rolling_update.max_surge else None
                } if deployment.spec.strategy.rolling_update else None
            },
            "conditions": [],
            "pod_template": {
                "containers": [],
                "restart_policy": deployment.spec.template.spec.restart_policy,
                "node_selector": deployment.spec.template.spec.node_selector or {}
            }
        }
        
        # Deployment 상태 조건
        if deployment.status.conditions:
            for condition in deployment.status.conditions:
                deployment_info["conditions"].append({
                    "type": condition.type,
                    "status": condition.status,
                    "last_transition_time": condition.last_transition_time.isoformat() if condition.last_transition_time else None,
                    "reason": condition.reason,
                    "message": condition.message
                })
        
        # Pod 템플릿 컨테이너 정보
        if deployment.spec.template.spec.containers:
            for container in deployment.spec.template.spec.containers:
                container_info = {
                    "name": container.name,
                    "image": container.image,
                    "ports": [],
                    "resources": {
                        "requests": container.resources.requests if container.resources and container.resources.requests else {},
                        "limits": container.resources.limits if container.resources and container.resources.limits else {}
                    },
                    "env": []
                }
                
                # 컨테이너 포트 정보
                if container.ports:
                    for port in container.ports:
                        port_info = {
                            "name": port.name,
                            "container_port": port.container_port,
                            "protocol": port.protocol or "TCP"
                        }
                        container_info["ports"].append(port_info)
                
                # 환경 변수 정보
                if container.env:
                    for env_var in container.env:
                        env_info = {
                            "name": env_var.name,
                            "value": env_var.value if env_var.value else "***",
                            "value_from": {
                                "config_map_key_ref": env_var.value_from.config_map_key_ref.name if env_var.value_from and env_var.value_from.config_map_key_ref else None,
                                "secret_key_ref": env_var.value_from.secret_key_ref.name if env_var.value_from and env_var.value_from.secret_key_ref else None
                            } if env_var.value_from else None
                        }
                        container_info["env"].append(env_info)
                
                deployment_info["pod_template"]["containers"].append(container_info)
        
        # 연결된 Pod 정보 조회
        label_selector = f"app={name}"
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        
        # Pod 상태 정보 추출 (헬퍼 함수 사용)
        pod_list = _format_pod_statuses(pods.items, include_labels=False, include_creation_time=True)
        
        deployment_info["pods"] = {
            "total": len(pod_list),
            "list": pod_list
        }
        
        return {
            "status": "success",
            "message": f"Deployment '{name}' 상세 정보 조회 완료",
            "deployment": deployment_info
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": "error",
                "deployment_name": name,
                "namespace": namespace,
                "message": f"Deployment '{name}'을 찾을 수 없습니다. 배포 이름을 확인해주세요."
            }
        return {
            "status": "error",
            "deployment_name": name,
            "namespace": namespace,
            "message": f"Kubernetes API 오류: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "deployment_name": name,
            "namespace": namespace,
            "message": f"Deployment 조회 실패: {str(e)}"
        }


