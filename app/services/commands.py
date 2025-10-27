from __future__ import annotations

import re
import os
import subprocess
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel, Field
from kubernetes import client
from kubernetes.client.rest import ApiException
from fastapi import HTTPException

from .deployments import DeployApplicationInput, perform_deploy
from .k8s_client import get_apps_v1_api, get_core_v1_api, get_networking_v1_api
from .response_formatter import ResponseFormatter
from .github_app import github_app_auth
from ..models.user_project_integration import UserProjectIntegration
from ..database import SessionLocal

logger = structlog.get_logger(__name__)


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
    # 비용 분석 관련 필드
    analysis_type: str = Field(default="usage")  # usage, optimization, forecast   # 몇 번 전으로 롤백할지


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
        # GitHub 저장소 기반 배포
        if not req.github_owner or not req.github_repo:
            raise ValueError("배포 명령어에는 GitHub 저장소 정보가 필요합니다. 예: 'K-Le-PaaS/test01 배포해줘'")
        return CommandPlan(
            tool="deploy_github_repository",
            args={
                "github_owner": req.github_owner,
                "github_repo": req.github_repo,
                "branch": getattr(req, "branch", "main"),
            },
        )
    
    elif command == "scale":
        # NCP SourceCommit 기반 스케일링만 지원
        if not req.github_owner or not req.github_repo:
            raise ValueError("스케일링 명령어에는 GitHub 저장소 정보가 필요합니다. 예: 'K-Le-PaaS/test01을 3개로 늘려줘'")
        return CommandPlan(
            tool="scale",
            args={
                "owner": req.github_owner,
                "repo": req.github_repo,
                "github_owner": req.github_owner,
                "github_repo": req.github_repo,
                "replicas": req.replicas
            },
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
            raise ValueError("접속 주소를 확인하려면 서비스 이름이 필요합니다. 먼저 '서비스 목록' 명령어로 사용 가능한 서비스를 확인하시거나, 구체적인 서비스 이름을 명시해주세요. 예: 'nginx-service 접속 주소' 또는 'frontend-svc URL'")
        return CommandPlan(
            tool="k8s_get_endpoints",
            args={"name": resource_name, "namespace": req.namespace or ns},
        )
    
    elif command == "restart":
        # GitHub 저장소 정보 기반 재시작
        if not req.github_owner or not req.github_repo:
            raise ValueError("재시작 명령어에는 GitHub 저장소 정보가 필요합니다. 예: 'K-Le-PaaS/test01 재시작해줘'")
        return CommandPlan(
            tool="k8s_restart_deployment",
            args={
                "github_owner": req.github_owner,
                "github_repo": req.github_repo,
                "namespace": req.namespace or ns
            },
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
    
    elif command == "list_endpoints":
        return CommandPlan(
            tool="k8s_list_namespaced_endpoints",
            args={"namespace": ns},
        )

    elif command == "list_rollback":
        # 롤백 목록 조회 명령어
        if not req.github_owner or not req.github_repo:
            raise ValueError("롤백 목록 조회에는 프로젝트 정보가 필요합니다. 예: 'K-Le-PaaS/test01 롤백 목록'")
        return CommandPlan(
            tool="get_rollback_list",
            args={"owner": req.github_owner, "repo": req.github_repo},
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

    elif command == "cost_analysis":
        # 비용 분석 명령어
        return CommandPlan(
            tool="cost_analysis",
            args={
                "namespace": ns,
                "analysis_type": req.analysis_type or "usage"
            },
        )

    raise ValueError("해석할 수 없는 명령입니다.")


async def _execute_cost_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    클러스터 비용 분석 실행
    """
    namespace = args.get("namespace", "default")
    analysis_type = args.get("analysis_type", "usage")
    
    # TODO: 실제 비용 분석 로직 구현
    # 현재는 mock 데이터 반환
    
    if analysis_type == "optimization":
        return {
            "message": f"{namespace} 네임스페이스의 비용 최적화 제안을 생성했습니다.",
            "cost_estimate": {
                "current_cost": 150000,
                "estimated_cost": 105000,
                "savings": 45000,
                "currency": "KRW",
                "period": "월간",
                "breakdown": {
                    "compute": 80000,
                    "storage": 30000,
                    "network": 25000,
                    "idle_resources": -45000
                }
            },
            "recommendations": [
                "미사용 Pod 3개 제거 시 월 20,000원 절감",
                "스토리지 최적화로 월 15,000원 절감",
                "인스턴스 다운사이징으로 월 10,000원 절감"
            ]
        }
    elif analysis_type == "forecast":
        return {
            "message": f"{namespace} 네임스페이스의 월간 예상 비용을 계산했습니다.",
            "cost_estimate": {
                "estimated_cost": 150000,
                "currency": "KRW",
                "period": "월간 예상",
                "breakdown": {
                    "compute": 85000,
                    "storage": 35000,
                    "network": 30000
                }
            },
            "trend": "지난달 대비 5% 증가 예상"
        }
    else:  # usage
        return {
            "message": f"{namespace} 네임스페이스의 현재 비용 현황입니다.",
            "cost_estimate": {
                "current_cost": 150000,
                "currency": "KRW",
                "period": "이번 달",
                "breakdown": {
                    "compute": 85000,
                    "storage": 35000,
                    "network": 30000
                }
            },
            "resource_usage": {
                "pods": 12,
                "deployments": 5,
                "services": 8,
                "storage_gb": 150
            }
        }


async def _execute_deploy_github_repository(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    GitHub 저장소 배포 실행 (자연어 명령어용)
    예: "K-Le-PaaS/test01 배포해줘"
    """
    owner = args.get("github_owner")
    repo = args.get("github_repo")
    branch = args.get("branch", "main")
    user_id = args.get("user_id")

    if not owner or not repo:
        return {
            "status": "error",
            "message": "GitHub 저장소 정보가 필요합니다 (owner/repo 형식)"
        }

    if not user_id:
        return {
            "status": "error",
            "message": "사용자 인증 정보가 필요합니다"
        }

    db = SessionLocal()
    try:
        # 1. UserProjectIntegration에서 연동 정보 조회
        integration = db.query(UserProjectIntegration).filter(
            UserProjectIntegration.github_owner == owner,
            UserProjectIntegration.github_repo == repo,
            UserProjectIntegration.user_id == str(user_id)
        ).first()

        if not integration:
            return {
                "status": "error",
                "message": f"저장소 {owner}/{repo}가 연동되지 않았습니다. Connected Repositories에서 먼저 연동해주세요."
            }

        # 2. GitHub API로 최신 커밋 정보 가져오기
        try:
            commit_info = await github_app_auth.get_latest_commit(owner, repo, branch, db)
        except Exception as e:
            logger.error(f"Failed to fetch latest commit: {str(e)}")
            return {
                "status": "error",
                "message": f"최신 커밋 정보를 가져오는데 실패했습니다: {str(e)}"
            }

        # 3. 웹훅 payload 형식으로 데이터 구성
        payload = {
            "ref": f"refs/heads/{branch}",
            "head_commit": {
                "id": commit_info["sha"],
                "message": commit_info["message"],
                "author": {
                    "name": commit_info["author"]["name"],
                    "email": commit_info["author"].get("email", ""),
                },
                "url": commit_info["url"],
                "timestamp": commit_info["timestamp"],
            },
            "pusher": {
                "name": "nlp-deploy",  # NLP 명령어를 통한 배포 식별자
            },
            "repository": {
                "full_name": f"{owner}/{repo}",
            }
        }

        logger.info(f"NLP deploy triggered for {owner}/{repo} (commit: {commit_info['sha'][:7]})")

        # 4. handle_push_webhook을 백그라운드에서 실행
        from ..api.v1.github_workflows import handle_push_webhook

        def run_async_in_thread(coro_func, *args, **kwargs):
            """백그라운드 스레드에서 비동기 함수 실행"""
            session = SessionLocal()
            try:
                # 통합 객체는 스레드 세이프하게 재조회
                integ = session.query(UserProjectIntegration).filter(
                    UserProjectIntegration.id == integration.id
                ).first()
                if integ is None:
                    logger.error(f"Integration {integration.id} not found in background task")
                    return
                asyncio.run(coro_func(*args, **kwargs, db=session, integration=integ))
            finally:
                try:
                    session.close()
                except Exception:
                    pass

        # 백그라운드 태스크로 배포 시작
        import threading
        thread = threading.Thread(
            target=run_async_in_thread,
            args=(handle_push_webhook, payload)
        )
        thread.start()

        # 5. 즉시 응답 반환 (배포는 백그라운드에서 진행)
        short_sha = commit_info["sha"][:7]
        return {
            "status": "success",
            "message": f"{owner}/{repo} 배포를 시작했습니다",
            "repository": f"{owner}/{repo}",
            "branch": branch,
            "commit": {
                "sha": short_sha,
                "message": commit_info["message"][:50] + ("..." if len(commit_info["message"]) > 50 else ""),
                "author": commit_info["author"]["name"]
            },
            "deployment_status": "배포가 백그라운드에서 진행 중입니다. CI/CD Pipelines 탭에서 진행 상황을 확인하세요."
        }

    except Exception as e:
        logger.error(f"Deploy execution failed: {str(e)}")
        return {
            "status": "error",
            "message": f"배포 실행 중 오류가 발생했습니다: {str(e)}"
        }
    finally:
        try:
            db.close()
        except Exception:
            pass


async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    """
    명령 실행 계획을 실제 Kubernetes API 호출로 변환하여 실행
    스케일링 명령의 경우 포맷팅하지 않고 원시 결과를 반환 (nlp.py에서 별도 처리)
    """
    # 원본 실행 결과를 가져옵니다
    raw_result = await _execute_raw_command(plan)
    
    # 스케일링/재시작 명령의 경우 포맷팅하지 않고 원시 결과 반환 (nlp.py에서 별도 처리)
    if plan.tool in ("scale", "k8s_restart_deployment"):
        return raw_result
    
    # 다른 명령어들은 ResponseFormatter를 사용하여 포맷팅
    formatter = ResponseFormatter()
    formatted_result = formatter.format_by_command(plan.tool, raw_result)
    
    return formatted_result


async def _execute_raw_command(plan: CommandPlan) -> Dict[str, Any]:
    """
    원본 명령 실행 (포맷팅 없이)
    """
    if plan.tool == "deploy_application":
        payload = DeployApplicationInput(**plan.args)
        return await perform_deploy(payload)

    if plan.tool == "deploy_github_repository":
        return await _execute_deploy_github_repository(plan.args)

    if plan.tool == "scale":
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

    if plan.tool == "get_rollback_list":
        return await _execute_get_rollback_list(plan.args)

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

    if plan.tool == "k8s_list_namespaced_endpoints":
        return await _execute_list_namespaced_endpoints(plan.args)

    if plan.tool == "k8s_get_service":
        return await _execute_get_service(plan.args)

    if plan.tool == "k8s_get_deployment":
        return await _execute_get_deployment(plan.args)

    if plan.tool == "cost_analysis":
        return await _execute_cost_analysis(plan.args)

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
    서비스 엔드포인트 조회 - 상세 정보 반환 (endpoint 명령어)
    예: "내 앱 접속 주소 알려줘", "서비스 URL 뭐야?"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        core_v1 = get_core_v1_api()
        networking_v1 = get_networking_v1_api()
        
        # 1. 서비스 정보 조회
        try:
            service = core_v1.read_namespaced_service(name=name, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                return {
                    "status": "error",
                    "service_name": name,
                    "namespace": namespace,
                    "message": f"'{name}' 서비스를 찾을 수 없습니다."
                }
            raise
        
        # 서비스 정보 추출
        service_type = service.spec.type
        cluster_ip = service.spec.cluster_ip or "None"
        ports = []
        for port in service.spec.ports or []:
            ports.append({
                "port": port.port,
                "target_port": port.target_port if hasattr(port.target_port, '__str__') else str(port.target_port),
                "protocol": port.protocol or "TCP"
            })
        
        # 서비스 엔드포인트 생성 (첫 번째 포트 사용)
        service_endpoint = f"http://{name}:{ports[0]['port']}" if ports else None
        
        # 2. Ingress 정보 조회
        ingress_name = None
        ingress_domain = None
        ingress_path = None
        found_ingress = None
        ingress_port = None
        
        try:
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
            
            for ingress in ingresses.items:
                # Ingress 규칙에서 해당 서비스를 백엔드로 사용하는지 확인
                for rule in ingress.spec.rules or []:
                    for path in rule.http.paths or []:
                        if hasattr(path.backend.service, 'name') and path.backend.service.name == name:
                            found_ingress = ingress
                            ingress_name = ingress.metadata.name
                            ingress_domain = rule.host
                            ingress_path = path.path
                            # 대상 서비스 포트 가져오기
                            if hasattr(path.backend.service, 'port'):
                                if hasattr(path.backend.service.port, 'number'):
                                    ingress_port = path.backend.service.port.number
                            break
                    if ingress_name:
                        break
                if ingress_name:
                    break
        except ApiException:
            pass  # Ingress가 없을 수 있음
        
        # 인그리스 이름 생성 (서비스이름-svc -> 서비스이름-ingress)
        if not ingress_name:
            # 서비스 이름에서 -svc를 -ingress로 변경
            if name.endswith("-svc"):
                ingress_name = name.replace("-svc", "-ingress")
            else:
                ingress_name = f"{name}-ingress"
        
        # TLS/HTTPS 설정 확인
        has_tls = False
        if found_ingress and found_ingress.spec.tls:
            for tls in found_ingress.spec.tls:
                if ingress_domain in (tls.hosts or []):
                    has_tls = True
                    break
        
        # 접속 가능한 URL 생성
        accessible_url = None
        if ingress_domain and found_ingress:
            # TLS 설정 확인
            protocol = "https" if has_tls else "http"
            accessible_url = f"{protocol}://{ingress_domain}{ingress_path or ''}"
        elif service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
            lb_ip = service.status.load_balancer.ingress[0].ip
            accessible_url = f"http://{lb_ip}:{ports[0]['port']}" if ports else None
        
        return {
            "status": "success",
            "service_name": name,
            "service_type": service_type,
            "cluster_ip": cluster_ip,
            "ports": ports,
            "namespace": namespace,
            "service_endpoint": service_endpoint,
            "ingress_name": ingress_name,
            "ingress_domain": ingress_domain,
            "ingress_path": ingress_path,
            "ingress_port": ingress_port,
            "ingress_has_tls": has_tls,
            "accessible_url": accessible_url,
            "message": "엔드포인트 정보를 조회했습니다."
        }
        
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
    예: "K-Le-PaaS/test01 재시작해줘"

    owner/repo를 받아서 deployment 이름으로 변환
    실제 deployment 이름: {owner}-{repo}-deploy (소문자)
    구현 방법: kubectl rollout restart deployment 방식으로 Pod 재시작
    """
    owner = args.get("github_owner", "")
    repo = args.get("github_repo", "")
    namespace = args.get("namespace", "default")

    # owner/repo → deployment 이름 변환
    # K-Le-PaaS/test01 → k-le-paas-test01-deploy
    if not owner or not repo:
        return {
            "status": "error",
            "message": "GitHub 저장소 정보(owner/repo)가 필요합니다. 예: 'K-Le-PaaS/test01 재시작해줘'"
        }

    deployment_name = f"{owner}-{repo}-deploy".lower()

    try:
        apps_v1 = get_apps_v1_api()

        # Deployment 존재 확인
        try:
            deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                return {
                    "status": "error",
                    "owner": owner,
                    "repo": repo,
                    "deployment": deployment_name,
                    "namespace": namespace,
                    "message": f"Deployment '{deployment_name}'을 찾을 수 없습니다. 저장소 정보를 확인해주세요."
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
            "owner": owner,
            "repo": repo,
            "namespace": namespace,
            "restart_method": "kubectl rollout restart"
        }

    except ApiException as e:
        if e.status == 404:
            return {
                "status": "error",
                "owner": owner,
                "repo": repo,
                "deployment": deployment_name,
                "namespace": namespace,
                "message": f"Deployment '{deployment_name}'을 찾을 수 없습니다. 저장소 정보를 확인해주세요."
            }
        return {
            "status": "error",
            "owner": owner,
            "repo": repo,
            "deployment": deployment_name,
            "namespace": namespace,
            "message": f"Kubernetes API 오류: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "owner": owner,
            "repo": repo,
            "deployment": deployment_name,
            "namespace": namespace,
            "message": f"재시작 실패: {str(e)}"
        }


async def _execute_scale(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deployment 스케일링 (scale 명령어)
    NCP SourceCommit 매니페스트 기반 스케일링
    예: "K-Le-PaaS/test01을 3개로 늘려줘", "test01 스케일 5로"
    """
    from .rollback import scale_deployment
    from ..database import get_db

    owner = args.get("owner") or args.get("github_owner", "")
    repo = args.get("repo") or args.get("github_repo", "")
    replicas = args.get("replicas", 1)
    user_id = args.get("user_id", "nlp_user")

    # Validation
    if not owner or not repo:
        return {
            "status": "error",
            "message": "GitHub 저장소 정보가 필요합니다 (예: K-Le-PaaS/test01을 3개로 늘려줘)"
        }

    try:
        # 데이터베이스 세션 생성
        db = next(get_db())

        try:
            # scale_deployment 호출
            result = await scale_deployment(
                owner=owner,
                repo=repo,
                replicas=replicas,
                db=db,
                user_id=user_id
            )

            return {
                "status": "success",
                "message": f"{owner}/{repo}의 레플리카를 {result['old_replicas']}개에서 {replicas}개로 변경했습니다.",
                "data": result
            }

        finally:
            db.close()

    except HTTPException as e:
        return {
            "status": "error",
            "message": e.detail
        }
    except Exception as e:
        logger.error(f"Scaling failed: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": f"스케일링 실패: {str(e)}"
        }


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

    # 데이터베이스 세션 생성
    db = next(get_db())

    try:
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
    finally:
        # 데이터베이스 세션 정리
        db.close()


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
    클러스터 전체 현황 보고서 조회 (overview 명령어)
    예: "클러스터 전체 현황 보여줘", "클러스터 상태 보고서", "전체 리소스 상태 확인"
    
    모든 네임스페이스의 Deployment, Pod, Service를 조회하여 보고서 형식으로 제공
    """
    try:
        apps_v1 = get_apps_v1_api()
        core_v1 = get_core_v1_api()
        
        # 클러스터 정보 (노드 조회)
        try:
            nodes = core_v1.list_node()
            cluster_nodes = []
            for node in nodes.items:
                # Node Ready 상태 확인
                ready_status = "NotReady"
                if node.status.conditions:
                    for condition in node.status.conditions:
                        if condition.type == "Ready" and condition.status == "True":
                            ready_status = "Ready"
                            break
                
                cluster_nodes.append({
                    "name": node.metadata.name,
                    "status": ready_status
                })
        except Exception as e:
            logger.error(f"Failed to get nodes: {e}")
            cluster_nodes = []
        
        # 클러스터 이름 추출 (kubectl config current-context)
        cluster_name = "Unknown Cluster"
        try:
            # kubeconfig 파일 경로 가져오기
            kubeconfig_path = os.getenv('NKS')  # 환경 변수에서 kubeconfig 경로 가져오기
            if kubeconfig_path:
                # kubectl config current-context --kubeconfig $NKS 실행
                result = subprocess.run(
                    ['kubectl', 'config', 'current-context', '--kubeconfig', kubeconfig_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    context_name = result.stdout.strip()
                    # UUID 형식 제거 (예: "nks_kr_contest-cluster-27_69b2edb8-2975-4cb4-9dcb-68e3902a68ec" -> "nks_kr_contest-cluster")
                    
                    # 1. 표준 UUID 패턴: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                    # 2. 마지막 underscore 뒤의 UUID 부분 제거
                    # 3. 하이픈과 숫자로 구성된 끝 부분 제거
                    
                    # 표준 UUID 형식 제거 (예: 69b2edb8-2975-4cb4-9dcb-68e3902a68ec)
                    uuid_pattern = r'_[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$'
                    cluster_name = re.sub(uuid_pattern, '', context_name)
                    
                    # 혹시 남아있을 수 있는 숫자로 끝나는 패턴 제거 (예: -27)
                    cluster_name = re.sub(r'-\d+$', '', cluster_name)
                    
                    # 하이픈으로 끝나면 제거
                    cluster_name = cluster_name.rstrip('-')
                    cluster_name = cluster_name.rstrip('_')
            else:
                # 환경 변수가 없으면 일반 kubectl 사용
                result = subprocess.run(
                    ['kubectl', 'config', 'current-context'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    context_name = result.stdout.strip()
                    # UUID 형식 제거
                    # 표준 UUID 형식 제거 (예: 69b2edb8-2975-4cb4-9dcb-68e3902a68ec)
                    uuid_pattern = r'_[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$'
                    cluster_name = re.sub(uuid_pattern, '', context_name)
                    
                    # 혹시 남아있을 수 있는 숫자로 끝나는 패턴 제거 (예: -27)
                    cluster_name = re.sub(r'-\d+$', '', cluster_name)
                    
                    # 하이픈 또는 underscore로 끝나면 제거
                    cluster_name = cluster_name.rstrip('-')
                    cluster_name = cluster_name.rstrip('_')
        except Exception as e:
            logger.warning(f"Failed to get cluster name: {e}")
            cluster_name = "K-Le-PaaS Cluster"  # 기본값
        
        # 모든 네임스페이스 조회
        namespaces = core_v1.list_namespace()
        namespace_list = [ns.metadata.name for ns in namespaces.items]
        
        # 모든 네임스페이스의 리소스 수집
        all_deployments = []
        all_pods = []
        all_services = []
        
        # Critical Issues 수집
        deployment_warnings = []  # Ready 비율이 100% 미만
        pending_pods = []  # Pending 상태
        failed_pods = []  # Failed/CrashLoopBackOff 상태
        high_restart_pods = []  # 재시작 10회 이상
        
        # 네임스페이스별 워크로드 집계
        workloads_by_namespace = {}
        
        # 외부 서비스 목록
        load_balancer_services = []
        node_port_services = []
        
        for namespace_name in namespace_list:
            workloads_by_namespace[namespace_name] = {
                "deployments": 0,
                "pods": 0
            }
            
            # Deployments 조회
            try:
                deployments = apps_v1.list_namespaced_deployment(namespace=namespace_name)
                for deployment in deployments.items:
                    ready_count = deployment.status.ready_replicas or 0
                    desired_count = deployment.spec.replicas
                    
                    deployment_data = {
                        "name": deployment.metadata.name,
                        "namespace": namespace_name,
                        "ready": f"{ready_count}/{desired_count}",
                        "status": "Running" if ready_count == desired_count else "Pending"
                    }
                    
                    all_deployments.append(deployment_data)
                    workloads_by_namespace[namespace_name]["deployments"] += 1
                    
                    # Critical: Ready 비율이 100% 미만
                    if ready_count < desired_count:
                        deployment_warnings.append({
                            "namespace": namespace_name,
                            "name": deployment.metadata.name,
                            "ready": f"{ready_count}/{desired_count}"
                        })
            except ApiException:
                pass  # 네임스페이스에 접근 권한이 없을 수 있음
            
            # Pods 조회
            try:
                pods = core_v1.list_namespaced_pod(namespace=namespace_name)
                for pod in pods.items:
                    # Pod 상태 정보 추출
                    phase = pod.status.phase
                    restart_count = 0
                    if pod.status.container_statuses:
                        for container_status in pod.status.container_statuses:
                            restart_count += container_status.restart_count
                    
                    pod_data = {
                        "name": pod.metadata.name,
                        "namespace": namespace_name,
                        "phase": phase,
                        "restarts": restart_count,
                        "ready": "0/1",
                        "age": None
                    }
                    
                    # Ready 상태 계산
                    if pod.status.container_statuses:
                        ready_count = sum(1 for cs in pod.status.container_statuses if cs.ready)
                        total_count = len(pod.status.container_statuses)
                        pod_data["ready"] = f"{ready_count}/{total_count}"
                    
                    # Age 계산
                    if pod.metadata.creation_timestamp:
                        now = datetime.now(timezone.utc)
                        age = now - pod.metadata.creation_timestamp
                        pod_data["age"] = str(age).split('.')[0]
                    
                    all_pods.append(pod_data)
                    workloads_by_namespace[namespace_name]["pods"] += 1
                    
                    # Critical: Pending/Failed Pod
                    if phase == "Pending":
                        pending_pods.append({
                            "namespace": namespace_name,
                            "name": pod.metadata.name,
                            "status": phase
                        })
                    elif phase in ["Failed", "CrashLoopBackOff"] or any(
                        cs.state.waiting and cs.state.waiting.reason == "CrashLoopBackOff"
                        for cs in (pod.status.container_statuses or [])
                    ):
                        failed_pods.append({
                            "namespace": namespace_name,
                            "name": pod.metadata.name,
                            "status": phase
                        })
                    
                    # Warning: 높은 재시작 횟수 (10회 이상)
                    if restart_count >= 10:
                        high_restart_pods.append({
                            "namespace": namespace_name,
                            "name": pod.metadata.name,
                            "restarts": restart_count
                        })
            except ApiException:
                pass  # 네임스페이스에 접근 권한이 없을 수 있음
            
            # Services 조회
            try:
                services = core_v1.list_namespaced_service(namespace=namespace_name)
                for service in services.items:
                    service_type = service.spec.type
                    
                    service_data = {
                        "name": service.metadata.name,
                        "namespace": namespace_name,
                        "type": service_type,
                        "cluster_ip": service.spec.cluster_ip
                    }
                    
                    all_services.append(service_data)
                    
                    # 외부 서비스 분류
                    if service_type == "LoadBalancer":
                        load_balancer_services.append({
                            "name": service.metadata.name,
                            "namespace": namespace_name
                        })
                    elif service_type == "NodePort":
                        node_port_services.append({
                            "name": service.metadata.name,
                            "namespace": namespace_name
                        })
            except ApiException:
                pass  # 네임스페이스에 접근 권한이 없을 수 있음
        
        # 요약 통계
        summary = {
            "cluster_name": cluster_name,
            "total_nodes": len(cluster_nodes),
            "total_namespaces": len(namespace_list),
            "total_deployments": len(all_deployments),
            "total_pods": len(all_pods),
            "total_services": len(all_services),
            "running_pods": len([p for p in all_pods if p["phase"] == "Running"]),
            "critical_deployment_issues": len(deployment_warnings),
            "pending_pod_issues": len(pending_pods),
            "failed_pod_issues": len(failed_pods),
            "high_restart_issues": len(high_restart_pods)
        }
        
        return {
            "status": "success",
            "cluster_info": {
                "name": cluster_name,
                "total_nodes": len(cluster_nodes),
                "nodes": cluster_nodes
            },
            "namespaces": namespace_list,
            "critical_issues": {
                "deployment_warnings": deployment_warnings,
                "pending_pods": pending_pods,
                "failed_pods": failed_pods
            },
            "warnings": {
                "high_restart_pods": high_restart_pods
            },
            "workloads_by_namespace": workloads_by_namespace,
            "external_services": {
                "load_balancer": load_balancer_services,
                "node_port": node_port_services
            },
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Failed to get overview: {e}")
        return {
            "status": "error",
            "message": f"클러스터 현황 조회 실패: {str(e)}"
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
            # Age 계산
            age = "알 수 없음"
            if ingress.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age_delta = now - ingress.metadata.creation_timestamp
                age = str(age_delta).split('.')[0]  # 초 단위 제거
            
            ingress_info = {
                "name": ingress.metadata.name,
                "namespace": ingress.metadata.namespace,
                "class": ingress.spec.ingress_class_name if hasattr(ingress.spec, 'ingress_class_name') else "",
                "age": age,
                "hosts": [],
                "addresses": [],
                "urls": [],
                "services": [],
                "paths": []
            }
            
            # TLS 설정 확인
            tls_hosts = set()
            if ingress.spec.tls:
                for tls in ingress.spec.tls:
                    if tls.hosts:
                        tls_hosts.update(tls.hosts)
            
            # Ingress 호스트 정보
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.host:
                        ingress_info["hosts"].append(rule.host)
                        # URL 생성 (HTTPS 또는 HTTP)
                        protocol = "https" if rule.host in tls_hosts else "http"
                        url = f"{protocol}://{rule.host}"
                        ingress_info["urls"].append(url)
                        
                        # Path와 Backend 정보 수집
                        if rule.http and rule.http.paths:
                            for path in rule.http.paths:
                                # 경로 정보
                                path_info = {
                                    "path": path.path if hasattr(path, 'path') else "/",
                                    "service_name": None,
                                    "port": None
                                }
                                
                                # 서비스 정보
                                if hasattr(path.backend, 'service') and path.backend.service:
                                    if hasattr(path.backend.service, 'name'):
                                        path_info["service_name"] = path.backend.service.name
                                    if hasattr(path.backend.service, 'port'):
                                        if hasattr(path.backend.service.port, 'number'):
                                            path_info["port"] = path.backend.service.port.number
                                        elif hasattr(path.backend.service.port, 'name'):
                                            path_info["port"] = path.backend.service.port.name
                                
                                ingress_info["paths"].append(path_info)
                                if path_info["service_name"]:
                                    ingress_info["services"].append(path_info["service_name"])
            
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


async def _execute_list_namespaced_endpoints(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    네임스페이스의 모든 서비스 엔드포인트 목록 조회 (list_endpoints 명령어)
    예: "엔드포인트 목록 보여줘", "default 네임스페이스 모든 접속 주소 확인"
    
    Service와 연결된 Ingress 도메인을 포함하여 모든 접속 주소를 제공합니다.
    """
    namespace = args.get("namespace", "default")
    
    try:
        core_v1 = get_core_v1_api()
        networking_v1 = get_networking_v1_api()
        
        # 1. 네임스페이스의 모든 Service 조회
        services = core_v1.list_namespaced_service(namespace=namespace)
        
        # 2. 네임스페이스의 모든 Ingress 조회
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        # 3. Service별 Ingress 매핑 생성
        service_to_ingress = {}
        for ingress in ingresses.items:
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            if hasattr(path.backend.service, 'name'):
                                service_name = path.backend.service.name
                                if service_name not in service_to_ingress:
                                    service_to_ingress[service_name] = []
                                
                                domain = f"https://{rule.host}" if rule.host else None
                                if domain:
                                    service_to_ingress[service_name].append({
                                        "domain": domain,
                                        "path": path.path,
                                        "ingress_name": ingress.metadata.name
                                    })
        
        # 4. Endpoint 정보 구성
        endpoint_list = []
        for service in services.items:
            service_name = service.metadata.name
            
            # 기본 Service 정보
            endpoint_info = {
                "service_name": service_name,
                "service_type": service.spec.type,
                "cluster_ip": service.spec.cluster_ip,
                "ports": [],
                "ingress_domains": [],
                "external_access": None,
                "service_endpoint": None
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
                    endpoint_info["ports"].append(port_info)
                
                # 서비스 엔드포인트 생성 (첫 번째 포트 사용)
                endpoint_info["service_endpoint"] = f"http://{service_name}:{service.spec.ports[0].port}"
            
            # Ingress 도메인 정보
            if service_name in service_to_ingress:
                endpoint_info["ingress_domains"] = service_to_ingress[service_name]
            
            # LoadBalancer 외부 IP 정보
            if service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
                for lb_ingress in service.status.load_balancer.ingress:
                    external_ip = lb_ingress.ip or lb_ingress.hostname
                    if external_ip:
                        endpoint_info["external_access"] = {
                            "type": "LoadBalancer",
                            "address": external_ip,
                            "ports": [{"port": p.port, "protocol": p.protocol or "TCP"} 
                                     for p in service.spec.ports] if service.spec.ports else []
                        }
            
            endpoint_list.append(endpoint_info)
        
        # 요약 통계
        summary = {
            "total_services": len(endpoint_list),
            "services_with_ingress": len([e for e in endpoint_list if e["ingress_domains"]]),
            "services_with_external": len([e for e in endpoint_list if e["external_access"]])
        }
        
        return {
            "status": "success",
            "message": f"'{namespace}' 네임스페이스 엔드포인트 목록 조회 완료",
            "namespace": namespace,
            "summary": summary,
            "endpoints": endpoint_list
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
            "message": f"Kubernetes API 오류: {e.reason}"
        }
    except Exception as e:
        return {
            "status": "error",
            "namespace": namespace,
            "message": f"엔드포인트 목록 조회 실패: {str(e)}"
        }


async def _execute_get_rollback_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    롤백 목록 조회 (list_rollback 명령어)
    예: "K-Le-PaaS/test01 롤백 목록 보여줘", "배포 이력 확인"
    """
    owner = args.get("owner")
    repo = args.get("repo")
    
    if not owner or not repo:
        return {"status": "error", "message": "프로젝트 정보가 필요합니다. 예: 'K-Le-PaaS/test01 롤백 목록'"}
    
    try:
        from ..database import SessionLocal
        from .rollback import get_rollback_list
        
        db = SessionLocal()
        try:
            result = await get_rollback_list(owner, repo, db, limit=10)
            
            if not result.get("current_state"):
                return {
                    "status": "success",
                    "message": f"{owner}/{repo} 프로젝트에 배포 이력이 없습니다.",
                    "data": result
                }
            
            # 사용자 친화적인 메시지 구성
            current = result["current_state"]
            current_msg = f"현재: {current['commit_sha_short']} - {current['commit_message'][:50]}"
            if current["is_rollback"]:
                current_msg += " (롤백됨)"
            
            available_count = result["total_available"]
            rollback_count = result["total_rollbacks"]
            
            message = f"{owner}/{repo} 롤백 목록을 조회했습니다.\n"
            message += f"{current_msg}\n"
            message += f"롤백 가능한 버전: {available_count}개, 최근 롤백: {rollback_count}개"
            
            return {
                "status": "success",
                "message": message,
                "data": result
            }
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"롤백 목록 조회 실패: {str(e)}", exc_info=True)
        return {"status": "error", "message": f"롤백 목록 조회 실패: {str(e)}"}


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


