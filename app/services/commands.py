from __future__ import annotations

import re
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
    # URL 변경 관련 필드
    new_domain: str = Field(default="")        # 변경할 새로운 도메인
    # 비용 분석 관련 필드
    analysis_type: str = Field(default="usage")  # usage, optimization, forecast


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

    elif command == "list_rollback":
        # 롤백 목록 조회 명령어
        if not req.github_owner or not req.github_repo:
            raise ValueError(
                "[ERROR] 프로젝트 정보가 필요합니다\n\n"
                "[사용법] 올바른 사용법:\n"
                "• K-Le-PaaS/test01 롤백 목록 보여줘\n"
                "• owner/repo 롤백 목록\n"
                "• 리포지토리명 롤백 목록\n\n"
                "[팁] GitHub 저장소의 owner/repo 형식으로 입력해주세요"
            )
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

    elif command in ("change_url", "change_domain"):
        # 도메인 변경은 대화형 엔드포인트 필요
        raise ValueError(
            "🔄 [도메인 변경 요청]\n\n"
            "도메인 변경은 대화형 방식으로 진행됩니다.\n"
            "아래 엔드포인트를 사용해주세요:\n\n"
            "📍 엔드포인트: POST /api/v1/nlp/conversation\n"
            "📝 요청 본문:\n"
            "{\n"
            '  "command": "' + (req.github_repo or "도메인 바꿔줘") + ' 도메인 바꿔줘",\n'
            '  "session_id": null\n'
            "}\n\n"
            "💡 대화형 플로우:\n"
            "1️⃣ 서비스 선택 (또는 자동 인식)\n"
            "2️⃣ 새 도메인 입력\n"
            "3️⃣ 검증 및 중복 체크\n"
            "4️⃣ 최종 확인\n"
            "5️⃣ 도메인 변경 완료\n\n"
            "ℹ️ 서비스 이름을 함께 말씀하시면 더 빠릅니다!\n"
            "예: 'test02 도메인 바꿔줘'"
        )

    elif command == "unknown":
        # unknown 명령어에 대한 처리
        return CommandPlan(
            tool="unknown",
            args={
                "command": req.command,
                "message": "명령어를 이해할 수 없습니다. 올바른 형식으로 다시 입력해주세요."
            },
        )

    else:
        raise ValueError(
            "[ERROR] 명령을 해석할 수 없습니다\n\n"
            "[지원 명령어] 지원하는 명령어:\n"
            "• 롤백: K-Le-PaaS/test01 롤백 목록 보여줘\n"
            "• 배포: K-Le-PaaS/test01 배포해줘\n"
            "• Pod 관리: pod 목록 보여줘, nginx-pod 로그 보여줘\n"
            "• 서비스 관리: service 목록 보여줘\n"
            "• 비용 분석: 비용 분석해줘\n"
            "• 도메인 변경: /api/v1/nlp/conversation 엔드포인트 사용\n\n"
            "[팁] 구체적인 리소스 이름과 함께 명령어를 입력해주세요"
        )


async def _execute_unknown(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unknown 명령어 처리
    """
    return {
        "status": "error",
        "message": "명령어를 이해할 수 없습니다. GitHub 저장소 정보와 함께 명령어를 입력해주세요.",
        "command": args.get("command", "unknown"),
        "suggestions": [
            "K-Le-PaaS/test01 4개로 스케일링 해줘",
            "K-Le-PaaS/test01 롤백 목록 보여줘", 
            "K-Le-PaaS/test01 상태 확인",
            "K-Le-PaaS/test01 로그 보여줘"
        ],
        "error_type": "command_not_understood"
    }


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
            "formatted": {
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
    ResponseFormatter를 사용하여 사용자 친화적인 형식으로 응답을 포맷팅합니다.
    """
    # 원본 실행 결과를 가져옵니다
    raw_result = await _execute_raw_command(plan)
    
    # ResponseFormatter를 사용하여 포맷팅
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

    if plan.tool == "change_url":
        return await _execute_change_url(plan.args)

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

    if plan.tool == "k8s_get_service":
        return await _execute_get_service(plan.args)

    if plan.tool == "k8s_get_deployment":
        return await _execute_get_deployment(plan.args)

    if plan.tool == "cost_analysis":
        return await _execute_cost_analysis(plan.args)

    if plan.tool == "unknown":
        return await _execute_unknown(plan.args)

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
    서비스 엔드포인트 조회 - Ingress 도메인 반환 (endpoint 명령어)
    서비스 이름이나 레포지토리 이름으로 Ingress 접속 주소 조회
    예: "k-le-paas-test01-svc 엔드포인트", "k-le-paas-test01 접속 주소"
    """
    name = args["name"]
    namespace = args["namespace"]
    
    try:
        networking_v1 = get_networking_v1_api()
        
        # 가능한 서비스 이름 패턴들 생성
        possible_service_names = []
        
        # 1. 입력된 이름 그대로
        possible_service_names.append(name)
        
        # 2. 레포지토리 이름인 경우 서비스 이름으로 변환
        if not name.endswith('-svc'):
            # k-le-paas-test01 -> k-le-paas-test01-svc
            possible_service_names.append(f"{name}-svc")
        
        # 3. 서비스 이름인 경우 레포지토리 이름으로도 시도
        if name.endswith('-svc'):
            # k-le-paas-test01-svc -> k-le-paas-test01
            repo_name = name[:-4]  # -svc 제거
            possible_service_names.append(repo_name)
        
        logger.info(f"Searching for Ingress with possible service names: {possible_service_names}")
        
        # 모든 네임스페이스의 Ingress 조회 (더 넓은 범위에서 검색)
        try:
            # 먼저 지정된 네임스페이스에서 검색
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
            found_ingress = _find_ingress_for_services(ingresses.items, possible_service_names, name)
            
            if found_ingress:
                return found_ingress
            
            # 지정된 네임스페이스에서 찾지 못한 경우 모든 네임스페이스에서 검색
            all_ingresses = networking_v1.list_ingress_for_all_namespaces()
            found_ingress = _find_ingress_for_services(all_ingresses.items, possible_service_names, name)
            
            if found_ingress:
                return found_ingress
            
            # 모든 패턴으로 찾지 못한 경우
            return {
                "status": "error",
                "service_name": name,
                "namespace": namespace,
                "searched_patterns": possible_service_names,
                "message": f"'{name}'에 대한 Ingress 도메인을 찾을 수 없습니다.\n\n"
                          f"🔍 **검색한 패턴:** {', '.join(possible_service_names)}\n"
                          f"📋 **확인 사항:**\n"
                          f"• 서비스가 배포되어 있는지 확인\n"
                          f"• Ingress가 설정되어 있는지 확인\n"
                          f"• 네임스페이스가 올바른지 확인"
            }
            
        except ApiException as e:
            if e.status == 404:
                return {
                    "status": "error", 
                    "service_name": name,
                    "namespace": namespace,
                    "message": f"'{name}'에 대한 Ingress를 찾을 수 없습니다. 서비스가 배포되어 있는지 확인해주세요."
                }
            raise
        
    except Exception as e:
        logger.error(f"Endpoint lookup failed: {str(e)}")
        return {
            "status": "error",
            "service_name": name,
            "namespace": namespace,
            "message": f"엔드포인트 조회 실패: {str(e)}"
        }


def _find_ingress_for_services(ingresses: list, service_names: list, original_name: str) -> Optional[Dict[str, Any]]:
    """
    Ingress 목록에서 지정된 서비스 이름들과 매칭되는 Ingress 찾기
    """
    for ingress in ingresses:
        # Ingress 규칙에서 해당 서비스를 백엔드로 사용하는지 확인
        for rule in ingress.spec.rules or []:
            for path in rule.http.paths or []:
                if hasattr(path.backend.service, 'name'):
                    backend_service_name = path.backend.service.name
                    
                    # 가능한 서비스 이름들과 매칭 확인
                    if backend_service_name in service_names:
                        host = rule.host
                        if host:
                            # HTTPS 도메인 반환
                            domain = f"https://{host}"
                            
                            # 매칭된 서비스 이름과 경로 정보 포함
                            matched_service = backend_service_name
                            path_info = path.path if path.path else "/"
                            
                            return {
                                "status": "success",
                                "original_name": original_name,
                                "matched_service": matched_service,
                                "namespace": ingress.metadata.namespace,
                                "ingress_name": ingress.metadata.name,
                                "endpoints": [domain],
                                "path": path_info,
                                "message": f"'{original_name}' → '{matched_service}' 서비스의 Ingress 도메인을 찾았습니다."
                            }
    return None


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
                "result": result,
                "owner": owner,
                "repo": repo,
                "target_commit_short": target_commit_sha[:7]
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
                "result": result,
                "owner": owner,
                "repo": repo,
                "target_commit_short": result.get("target_commit_short", "")
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
                "result": result,
                "owner": owner,
                "repo": repo,
                "target_commit_short": result.get("target_commit_short", "")
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


async def _execute_change_url(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    배포 애플리케이션의 URL(도메인) 변경
    인그레스 매니페스트의 도메인만 변경하고 빌드 없이 재배포
    예: "owner/repo의 도메인을 newapp.klepaas.app으로 변경"
    """
    from .pipeline_user_url import change_deployment_url
    from ..database import get_db

    owner = args["owner"]
    repo = args["repo"]
    new_domain = args["new_domain"]
    user_id = args.get("user_id", "nlp_user")

    # 데이터베이스 세션 생성
    db = next(get_db())

    try:
        result = await change_deployment_url(
            owner=owner,
            repo=repo,
            new_domain=new_domain,
            db=db,
            user_id=user_id
        )

        return {
            "status": "success",
            "action": "change_url",
            "message": f"{owner}/{repo}의 도메인이 {result['new_domain']}으로 변경되었습니다.",
            "result": result,
            "owner": owner,
            "repo": repo,
            "old_domain": result.get("old_domain", ""),
            "new_domain": result.get("new_domain", ""),
            "new_url": result.get("new_url", "")
        }

    except Exception as e:
        logger.error(f"URL 변경 실패: {str(e)}")
        return {
            "status": "error",
            "action": "change_url",
            "message": f"URL 변경 실패: {str(e)}",
            "owner": owner,
            "repo": repo,
            "new_domain": new_domain
        }
    finally:
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
                "up_to_date": deployment.status.updated_replicas or 0,  # 업데이트된 레플리카 수
                "available": deployment.status.available_replicas or 0,  # 사용 가능한 레플리카 수
                "age": None,  # 초기값 설정
                "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
            }
            
            # Deployment 생성 시간 계산
            if deployment.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age = now - deployment.metadata.creation_timestamp
                deployment_info["age"] = str(age).split('.')[0]  # 초 단위 제거
            else:
                deployment_info["age"] = "알 수 없음"  # creation_timestamp가 없는 경우
            
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
                "up_to_date": deployment.status.updated_replicas or 0,  # 업데이트된 레플리카 수
                "available": deployment.status.available_replicas or 0,  # 사용 가능한 레플리카 수
                "status": "Running" if deployment.status.ready_replicas == deployment.spec.replicas else "Pending"
            }
            
            # Deployment 생성 시간 계산
            if deployment.metadata.creation_timestamp:
                now = datetime.now(timezone.utc)
                age = now - deployment.metadata.creation_timestamp
                deployment_info["age"] = str(age).split('.')[0]  # 초 단위 제거
            else:
                deployment_info["age"] = "알 수 없음"  # creation_timestamp가 없는 경우
            
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

            # 디버깅 로그
            logger.info(f"_execute_get_rollback_list - result: {result}")
            logger.info(f"_execute_get_rollback_list - result type: {type(result)}")
            if result:
                logger.info(f"_execute_get_rollback_list - result.keys(): {result.keys()}")
                logger.info(f"_execute_get_rollback_list - current_state: {result.get('current_state')}")

            # 결과가 None이거나 current_state가 없는 경우 처리
            if not result or not result.get("current_state"):
                # 롤백 완료 직후일 수 있으므로 더 친화적인 메시지 제공
                return {
                    "status": "success",
                    "message": f"[INFO] **{owner}/{repo}** 프로젝트의 배포 이력을 찾을 수 없습니다.\n\n"
                              f"[상황 분석] 다음 중 하나일 수 있습니다:\n"
                              f"• 롤백이 방금 완료되어 데이터가 아직 반영되지 않음\n"
                              f"• 프로젝트가 실제로 배포된 적이 없음\n"
                              f"• GitHub 연동이 올바르게 설정되지 않음\n\n"
                              f"[해결방법]\n"
                              f"• 롤백 완료 직후라면 30초 후 다시 시도해주세요\n"
                              f"• 프로젝트를 먼저 배포한 후 롤백 목록을 조회해주세요\n\n"
                              f"[사용법] 올바른 사용법:\n"
                              f"• K-Le-PaaS/test01 롤백 목록 보여줘\n"
                              f"• owner/repo 롤백 목록",
                    "data": result or {}
                }
            
            # 사용자 친화적인 메시지 구성
            current = result.get("current_state", {})
            if not current:
                return {
                    "status": "success",
                    "message": f"❌ **{owner}/{repo}** 프로젝트에 배포 이력이 없습니다.\n\n"
                              f"🔍 **확인 사항:**\n"
                              f"• 프로젝트가 실제로 배포된 적이 있는지 확인해주세요\n"
                              f"• GitHub 연동이 올바르게 설정되어 있는지 확인해주세요",
                    "data": result
                }
            
            current_msg = f"현재: {current.get('commit_sha_short', 'unknown')} - {current.get('commit_message', '메시지 없음')[:50]}"
            if current.get("is_rollback", False):
                current_msg += " (롤백됨)"
            
            available_count = result.get("total_available", 0)
            rollback_count = result.get("total_rollbacks", 0)
            
            message = f"✅ **{owner}/{repo}** 롤백 목록을 조회했습니다.\n\n"
            message += f"📦 **현재 상태:** {current_msg}\n"
            message += f"🔄 **롤백 가능한 버전:** {available_count}개\n"
            message += f"📋 **최근 롤백:** {rollback_count}개"
            
            return {
                "status": "success",
                "message": message,
                "data": result
            }
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"롤백 목록 조회 실패: {str(e)}", exc_info=True)
        return {
            "status": "error", 
            "message": f"❌ **{owner}/{repo}** 롤백 목록 조회 중 오류가 발생했습니다.\n\n"
                      f"🔍 **가능한 원인:**\n"
                      f"• 프로젝트가 존재하지 않습니다\n"
                      f"• 데이터베이스 연결 문제\n"
                      f"• 권한 문제\n\n"
                      f"💡 **해결 방법:**\n"
                      f"• 프로젝트 이름을 다시 확인해주세요\n"
                      f"• 잠시 후 다시 시도해주세요\n"
                      f"• 관리자에게 문의해주세요\n\n"
                      f"**기술적 오류:** {str(e)}"
        }


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


