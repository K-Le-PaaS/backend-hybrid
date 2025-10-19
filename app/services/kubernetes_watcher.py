"""
Kubernetes Watch API 서비스

실시간으로 Kubernetes 리소스 상태 변경을 감지하고 모니터링하는 서비스입니다.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, List
from enum import Enum

import structlog
from kubernetes import client, watch
from kubernetes.client.rest import ApiException

from ..core.config import get_settings

logger = structlog.get_logger(__name__)


class WatchEventType(str, Enum):
    """Watch 이벤트 타입"""
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    ERROR = "ERROR"


class DeploymentPhase(str, Enum):
    """배포 단계"""
    PENDING = "Pending"
    PROGRESSING = "Progressing"
    COMPLETE = "Complete"
    FAILED = "Failed"


class KubernetesWatcher:
    """Kubernetes 리소스 모니터링 클래스"""

    def __init__(self):
        self.settings = get_settings()
        self.watch_instances: Dict[str, watch.Watch] = {}
        self.watch_tasks: Dict[str, asyncio.Task] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.is_running = False

        # kubeconfig 로드
        self._load_kubeconfig()

    def _load_kubeconfig(self):
        """kubeconfig 파일을 로드합니다."""
        try:
            from ..services.k8s_client import load_kube_config
            load_kube_config()
            logger.info("kubeconfig_loaded_successfully", config_file=self.settings.k8s_config_file)
        except Exception as e:
            logger.error("kubeconfig_load_failed", error=str(e))
            raise

    def _get_apps_v1_api(self):
        """AppsV1Api 클라이언트를 반환합니다."""
        return client.AppsV1Api()

    def _get_core_v1_api(self):
        """CoreV1Api 클라이언트를 반환합니다."""
        return client.CoreV1Api()

    def _calculate_deployment_progress(self, deployment: Dict[str, Any]) -> int:
        """배포 진행률을 계산합니다."""
        try:
            status = deployment.get('status', {})
            spec = deployment.get('spec', {})
            
            # 기본 정보
            desired_replicas = spec.get('replicas', 0)
            updated_replicas = status.get('updatedReplicas', 0)
            ready_replicas = status.get('readyReplicas', 0)
            available_replicas = status.get('availableReplicas', 0)
            
            if desired_replicas == 0:
                return 100
            
            # 진행률 계산 (업데이트된 파드 비율)
            progress = int((updated_replicas / desired_replicas) * 100)
            return min(100, max(0, progress))
            
        except Exception as e:
            logger.warning("deployment_progress_calculation_failed", error=str(e))
            return 0

    def _get_deployment_phase(self, deployment: Dict[str, Any]) -> DeploymentPhase:
        """배포 단계를 판단합니다."""
        try:
            status = deployment.get('status', {})
            conditions = status.get('conditions', [])
            
            # 조건 확인
            for condition in conditions:
                condition_type = condition.get('type', '')
                condition_status = condition.get('status', '')
                
                if condition_type == 'Progressing' and condition_status == 'True':
                    reason = condition.get('reason', '')
                    if reason == 'NewReplicaSetAvailable':
                        return DeploymentPhase.COMPLETE
                    elif reason == 'ReplicaSetUpdated':
                        return DeploymentPhase.PROGRESSING
                
                elif condition_type == 'Available' and condition_status == 'True':
                    return DeploymentPhase.COMPLETE
                
                elif condition_type == 'ReplicaFailure' and condition_status == 'True':
                    return DeploymentPhase.FAILED
            
            # 기본값
            return DeploymentPhase.PENDING
            
        except Exception as e:
            logger.warning("deployment_phase_detection_failed", error=str(e))
            return DeploymentPhase.PENDING

    def _extract_pod_status_info(self, pods: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pod 상태 정보를 추출합니다."""
        total_pods = len(pods)
        ready_pods = 0
        pending_pods = 0
        failed_pods = 0
        pod_reasons = []
        
        for pod in pods:
            status = pod.get('status', {})
            phase = status.get('phase', 'Unknown')
            
            if phase == 'Running':
                # Ready 조건 확인
                conditions = status.get('conditions', [])
                is_ready = any(
                    cond.get('type') == 'Ready' and cond.get('status') == 'True'
                    for cond in conditions
                )
                if is_ready:
                    ready_pods += 1
                else:
                    pending_pods += 1
            elif phase == 'Pending':
                pending_pods += 1
                # 대기 사유 확인
                container_statuses = status.get('containerStatuses', [])
                for container_status in container_statuses:
                    waiting = container_status.get('state', {}).get('waiting', {})
                    if waiting:
                        reason = waiting.get('reason', 'Unknown')
                        message = waiting.get('message', '')
                        pod_reasons.append(f"{container_status.get('name', 'unknown')}: {reason} {message}")
            elif phase == 'Failed':
                failed_pods += 1
        
        return {
            'total_pods': total_pods,
            'ready_pods': ready_pods,
            'pending_pods': pending_pods,
            'failed_pods': failed_pods,
            'pod_reasons': pod_reasons[:5]  # 최대 5개만
        }

    async def _watch_deployments_worker(
        self,
        namespace: str,
        label_selector: Optional[str] = None
    ):
        """Deployment Watch 작업자"""
        try:
            api = self._get_apps_v1_api()
            w = watch.Watch()
            
            # Watch 시작
            for event in w.stream(
                api.list_namespaced_deployment,
                namespace=namespace,
                label_selector=label_selector,
                timeout_seconds=0  # 무한 대기
            ):
                try:
                    event_type = event['type']
                    deployment = event['object']
                    
                    # 이벤트 처리
                    await self._handle_deployment_event(
                        event_type=event_type,
                        deployment=deployment,
                        namespace=namespace
                    )
                    
                except Exception as e:
                    logger.error(
                        "deployment_event_processing_failed",
                        error=str(e),
                        event_type=event.get('type', 'unknown')
                    )
                    
        except ApiException as e:
            logger.error(
                "deployment_watch_api_error",
                error=str(e),
                namespace=namespace
            )
        except Exception as e:
            logger.error(
                "deployment_watch_worker_failed",
                error=str(e),
                namespace=namespace
            )

    async def _handle_deployment_event(
        self,
        event_type: str,
        deployment: Dict[str, Any],
        namespace: str
    ):
        """Deployment 이벤트를 처리합니다."""
        try:
            # V1Deployment 객체를 딕셔너리로 변환
            if hasattr(deployment, 'to_dict'):
                deployment = deployment.to_dict()
            
            metadata = deployment.get('metadata', {})
            name = metadata.get('name', 'unknown')
            
            # 배포 정보 추출
            deployment_info = {
                'name': name,
                'namespace': namespace,
                'event_type': event_type,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'labels': metadata.get('labels', {}),
                'annotations': metadata.get('annotations', {}),
            }
            
            # 배포 상태 정보
            if event_type in [WatchEventType.ADDED, WatchEventType.MODIFIED]:
                spec = deployment.get('spec', {})
                status = deployment.get('status', {})
                
                # 진행률 계산
                progress = self._calculate_deployment_progress(deployment)
                phase = self._get_deployment_phase(deployment)
                
                # Pod 정보 수집
                try:
                    core_api = self._get_core_v1_api()
                    pods = core_api.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"app={name}"
                    )
                    pod_info = self._extract_pod_status_info(pods.items)
                except Exception as e:
                    logger.warning("pod_info_collection_failed", error=str(e))
                    pod_info = {
                        'total_pods': 0,
                        'ready_pods': 0,
                        'pending_pods': 0,
                        'failed_pods': 0,
                        'pod_reasons': []
                    }
                
                deployment_info.update({
                    'progress': progress,
                    'phase': phase.value,
                    'desired_replicas': spec.get('replicas', 0),
                    'updated_replicas': status.get('updatedReplicas', 0),
                    'ready_replicas': status.get('readyReplicas', 0),
                    'available_replicas': status.get('availableReplicas', 0),
                    'pod_info': pod_info,
                    'conditions': status.get('conditions', []),
                    'image': self._extract_deployment_image(deployment)
                })
            
            # 이벤트 핸들러 호출
            await self._notify_handlers('deployment', deployment_info)
            
            logger.debug(
                "deployment_event_processed",
                name=name,
                namespace=namespace,
                event_type=event_type,
                progress=deployment_info.get('progress', 0)
            )
            
        except Exception as e:
            logger.error(
                "deployment_event_handling_failed",
                error=str(e),
                event_type=event_type
            )

    def _extract_deployment_image(self, deployment: Dict[str, Any]) -> Optional[str]:
        """Deployment에서 이미지 정보를 추출합니다."""
        try:
            spec = deployment.get('spec', {})
            template = spec.get('template', {})
            pod_spec = template.get('spec', {})
            containers = pod_spec.get('containers', [])
            
            if containers:
                return containers[0].get('image')
            return None
            
        except Exception as e:
            logger.warning("deployment_image_extraction_failed", error=str(e))
            return None

    async def _notify_handlers(self, resource_type: str, event_data: Dict[str, Any]):
        """이벤트 핸들러들을 호출합니다."""
        handlers = self.event_handlers.get(resource_type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_data)
                else:
                    handler(event_data)
            except Exception as e:
                logger.error(
                    "event_handler_failed",
                    error=str(e),
                    resource_type=resource_type,
                    handler=str(handler)
                )

    def add_event_handler(self, resource_type: str, handler: Callable):
        """이벤트 핸들러를 추가합니다."""
        if resource_type not in self.event_handlers:
            self.event_handlers[resource_type] = []
        
        self.event_handlers[resource_type].append(handler)
        
        logger.info(
            "event_handler_added",
            resource_type=resource_type,
            handler_count=len(self.event_handlers[resource_type])
        )

    def remove_event_handler(self, resource_type: str, handler: Callable):
        """이벤트 핸들러를 제거합니다."""
        if resource_type in self.event_handlers:
            try:
                self.event_handlers[resource_type].remove(handler)
                logger.info(
                    "event_handler_removed",
                    resource_type=resource_type,
                    handler_count=len(self.event_handlers[resource_type])
                )
            except ValueError:
                logger.warning(
                    "event_handler_not_found",
                    resource_type=resource_type
                )

    async def start_watching_deployments(
        self,
        namespace: str,
        label_selector: Optional[str] = None
    ):
        """Deployment 모니터링을 시작합니다."""
        try:
            watch_key = f"deployments:{namespace}:{label_selector or 'all'}"
            
            if watch_key in self.watch_tasks:
                logger.warning("deployment_watch_already_running", watch_key=watch_key)
                return
            
            # Watch 작업 시작
            task = asyncio.create_task(
                self._watch_deployments_worker(namespace, label_selector)
            )
            self.watch_tasks[watch_key] = task
            
            self.is_running = True
            
            logger.info(
                "deployment_watch_started",
                namespace=namespace,
                label_selector=label_selector,
                watch_key=watch_key
            )
            
        except Exception as e:
            logger.error(
                "deployment_watch_start_failed",
                error=str(e),
                namespace=namespace
            )
            raise

    async def stop_watching_deployments(self, namespace: str, label_selector: Optional[str] = None):
        """Deployment 모니터링을 중지합니다."""
        try:
            watch_key = f"deployments:{namespace}:{label_selector or 'all'}"
            
            if watch_key in self.watch_tasks:
                task = self.watch_tasks[watch_key]
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
                del self.watch_tasks[watch_key]
                
                logger.info("deployment_watch_stopped", watch_key=watch_key)
            else:
                logger.warning("deployment_watch_not_found", watch_key=watch_key)
                
        except Exception as e:
            logger.error(
                "deployment_watch_stop_failed",
                error=str(e),
                namespace=namespace
            )

    async def stop_all_watches(self):
        """모든 Watch를 중지합니다."""
        try:
            for watch_key, task in self.watch_tasks.items():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            self.watch_tasks.clear()
            self.is_running = False
            
            logger.info("all_watches_stopped")
            
        except Exception as e:
            logger.error("stop_all_watches_failed", error=str(e))

    def get_watch_status(self) -> Dict[str, Any]:
        """Watch 상태를 반환합니다."""
        return {
            'is_running': self.is_running,
            'active_watches': list(self.watch_tasks.keys()),
            'event_handlers': {
                resource_type: len(handlers)
                for resource_type, handlers in self.event_handlers.items()
            }
        }


# 전역 Watcher 인스턴스
kubernetes_watcher: Optional[KubernetesWatcher] = None


def get_kubernetes_watcher() -> KubernetesWatcher:
    """Kubernetes Watcher 인스턴스를 반환합니다."""
    if kubernetes_watcher is None:
        raise RuntimeError("KubernetesWatcher not initialized")
    return kubernetes_watcher


def init_kubernetes_watcher() -> None:
    """Kubernetes Watcher를 초기화합니다."""
    global kubernetes_watcher
    kubernetes_watcher = KubernetesWatcher()


async def update_deployment_history_on_success(event_data: Dict[str, Any]) -> None:
    """
    K8s Deployment 성공 시 deployment_histories의 deployed_at을 업데이트합니다.

    매칭 전략: 이미지 레포지토리+이름 (태그/다이제스트 무시) + namespace + status="running"
    """
    try:
        from datetime import datetime, timezone
        from ..database import get_db
        from ..models.deployment_history import DeploymentHistory

        # 배포 완료 여부 확인
        phase = event_data.get('phase')
        if phase != 'Complete':
            return

        # 필요한 정보 추출
        namespace = event_data.get('namespace')
        image = event_data.get('image')
        deployment_name = event_data.get('name')

        if not namespace or not image:
            logger.warning(
                "deployment_history_update_skipped_missing_info",
                namespace=namespace,
                image=image
            )
            return

        # 이미지 이름 정규화 (태그/다이제스트 제거)
        # 예: "registry/repo:tag" → "registry/repo"
        # 예: "registry/repo@sha256:..." → "registry/repo"
        def normalize_image_name(image_url: str) -> str:
            """이미지 URL에서 레포지토리+이름만 추출 (태그/다이제스트 제거)"""
            # @ 또는 : 기준으로 분리
            if '@' in image_url:
                return image_url.split('@')[0]
            elif ':' in image_url:
                return image_url.split(':')[0]
            return image_url

        normalized_k8s_image = normalize_image_name(image)

        # DB에서 매칭되는 배포 히스토리 찾기
        db = next(get_db())
        
        try:
            # 모든 running 상태의 배포 히스토리를 가져와서 이미지 이름으로 필터링
            running_histories = db.query(DeploymentHistory).filter(
                DeploymentHistory.namespace == namespace,
                DeploymentHistory.status == "running"
            ).order_by(DeploymentHistory.started_at.desc()).all()

            # 이미지 이름이 일치하는 것 찾기
            history = None
            for h in running_histories:
                if h.image_url:
                    normalized_db_image = normalize_image_name(h.image_url)
                    if normalized_db_image == normalized_k8s_image:
                        history = h
                        break

            if history:
                # deployed_at 업데이트
                now = datetime.now(timezone.utc)
                history.status = "success"
                history.sourcedeploy_status = "success"
                history.deployed_at = now
                history.completed_at = now

                # duration 계산
                if history.started_at:
                    # started_at이 timezone-naive이면 UTC timezone 추가
                    started_at = history.started_at
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    
                    delta = now - started_at
                    history.total_duration = int(delta.total_seconds())

                db.commit()

                logger.info(
                    "deployment_history_updated_on_k8s_success",
                    history_id=history.id,
                    namespace=namespace,
                    deployment_name=deployment_name,
                    k8s_image=image,
                    db_image=history.image_url,
                    normalized_image=normalized_k8s_image,
                    deployed_at=history.deployed_at.isoformat(),
                    duration_seconds=history.total_duration
                )
            else:
                logger.warning(
                    "no_matching_deployment_history_found",
                    namespace=namespace,
                    k8s_image=image,
                    normalized_k8s_image=normalized_k8s_image,
                    deployment_name=deployment_name,
                    running_histories_count=len(running_histories)
                )
        finally:
            # 세션 닫기
            db.close()

    except Exception as e:
        logger.error(
            "deployment_history_update_failed",
            error=str(e),
            event_data=event_data
        )
        # 예외 발생 시에도 세션 닫기
        try:
            if 'db' in locals():
                db.close()
        except:
            pass
