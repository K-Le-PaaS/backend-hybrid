"""
NLP Response Formatter

자연어 명령어의 응답을 사용자 친화적인 형식으로 변환하는 서비스입니다.
각 명령어 타입별로 최적화된 UI 렌더링을 위한 구조화된 데이터를 제공합니다.
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger(__name__)


class ResponseFormatter:
    """자연어 명령어 응답 포맷터"""
    
    def __init__(self):
        self.logger = logger.bind(service="response_formatter")
    
    def format_by_command(self, command: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        명령어 타입에 따라 적절한 포맷팅 메서드를 호출합니다.
        
        Args:
            command: 실행된 명령어 (예: "k8s_list_pods", "rollback_deployment")
            raw_data: 원본 응답 데이터
            
        Returns:
            포맷된 응답 데이터
        """
        try:
            # 명령어 매핑
            command_mapping = {
                "k8s_list_pods": self.format_list_pods,
                "k8s_get_status": self.format_status,
                "k8s_get_logs": self.format_logs,
                "k8s_get_endpoints": self.format_endpoint,
                "k8s_list_deployments": self.format_list_deployments,
                "k8s_list_services": self.format_list_services,
                "k8s_list_ingresses": self.format_list_ingresses,
                "k8s_list_namespaces": self.format_list_namespaces,
                "k8s_get_service": self.format_get_service,
                "k8s_get_deployment": self.format_get_deployment,
                "k8s_overview": self.format_overview,
                "k8s_get_overview": self.format_overview,  # overview 명령어 추가
                "k8s_list_all_deployments": self.format_list_deployments,  # 전체 deployment 목록
                "k8s_list_all_services": self.format_list_services,  # 전체 service 목록
                "k8s_list_all_ingresses": self.format_list_ingresses,  # 전체 ingress 목록
                "rollback_deployment": self.format_rollback_list,
                "get_rollback_list": self.format_rollback_list,  # 롤백 목록 조회 명령어 추가
                "scale": self.format_scale,
                "deploy_application": self.format_deploy,
                "deploy_github_repository": self.format_deploy_github_repository,  # GitHub 저장소 배포 명령어 추가
                "k8s_restart_deployment": self.format_restart,
                "cost_analysis": self.format_cost_analysis,
            }
            
            formatter = command_mapping.get(command)
            if not formatter:
                self.logger.warning(f"Unknown command: {command}")
                return self.format_unknown(command, raw_data)
            
            return formatter(raw_data)
            
        except Exception as e:
            self.logger.error(f"Error formatting command {command}: {str(e)}")
            return self.format_error(command, str(e))
    
    def format_list_pods(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Pod 목록을 테이블 형식으로 포맷"""
        try:
            pods = raw_data.get("pods", [])
            namespace = raw_data.get("namespace", "default")
            total_pods = len(pods)
            
            # 상태별 통계 계산
            running = sum(1 for pod in pods if pod.get("phase") == "Running")
            pending = sum(1 for pod in pods if pod.get("phase") == "Pending")
            failed = sum(1 for pod in pods if pod.get("phase") == "Failed")
            
            # 포맷된 Pod 데이터
            formatted_pods = []
            for pod in pods:
                formatted_pods.append({
                    "name": pod.get("name", ""),
                    "status": pod.get("phase", "Unknown"),
                    "ready": pod.get("ready", "0/0"),
                    "restarts": pod.get("restarts", 0),
                    "age": self._format_age(pod.get("age", "")),
                    "node": pod.get("node", ""),
                    "namespace": pod.get("namespace", namespace)
                })
            
            return {
                "type": "list_pods",
                "summary": f"{namespace} 네임스페이스에 {total_pods}개의 Pod가 있습니다. (실행 중: {running}, 대기: {pending}, 실패: {failed})",
                "data": {
                    "formatted": formatted_pods,
                    "raw": raw_data
                },
                "metadata": {
                    "total": total_pods,
                    "namespace": namespace,
                    "running": running,
                    "pending": pending,
                    "failed": failed
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_pods: {str(e)}")
            return self.format_error("list_pods", str(e))
    
    def format_rollback_list(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """롤백 목록을 타임라인 형식으로 포맷"""
        try:
            data = raw_data.get("data", {})
            owner = data.get("owner", "")
            repo = data.get("repo", "")
            current_state = data.get("current_state", {})
            available_versions = data.get("available_versions", [])
            rollback_history = data.get("rollback_history", [])
            
            # 현재 상태 포맷
            current_formatted = {
                "commit": current_state.get("commit_sha_short", ""),
                "message": current_state.get("commit_message", ""),
                "date": self._format_datetime(current_state.get("deployed_at", "")),
                "is_rollback": current_state.get("is_rollback", False),
                "deployment_id": current_state.get("deployment_id")
            }
            
            # 사용 가능한 버전들 포맷 (현재 버전 제외)
            versions_formatted = []
            for version in available_versions:
                # 현재 버전이 아닌 것만 롤백 가능한 버전으로 표시
                if not version.get("is_current", False):
                    versions_formatted.append({
                        "steps_back": version.get("steps_back", 0),
                        "commit": version.get("commit_sha_short", ""),
                        "message": version.get("commit_message", ""),
                        "date": self._format_datetime(version.get("deployed_at", "")),
                        "can_rollback": True,
                        "is_current": False
                    })
            
            # 롤백 히스토리 포맷
            history_formatted = []
            for rollback in rollback_history:
                history_formatted.append({
                    "commit": rollback.get("commit_sha_short", ""),
                    "message": rollback.get("commit_message", ""),
                    "date": self._format_datetime(rollback.get("rolled_back_at", "")),
                    "rollback_from_id": rollback.get("rollback_from_id")
                })
            
            total_available = len(available_versions)
            total_rollbacks = len(rollback_history)
            
            return {
                "type": "list_rollback",
                "summary": f"{owner}/{repo}의 롤백 가능한 버전 {total_available}개를 찾았습니다. 최근 롤백: {total_rollbacks}개",
                "data": {
                    "formatted": {
                        "current": current_formatted,
                        "versions": versions_formatted,
                        "history": history_formatted
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "owner": owner,
                    "repo": repo,
                    "total_available": total_available,
                    "total_rollbacks": total_rollbacks
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting rollback_list: {str(e)}")
            return self.format_error("list_rollback", str(e))
    
    def format_status(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Pod 상태를 카드 형식으로 포맷"""
        try:
            pod_name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            status = raw_data.get("status", "Unknown")
            ready = raw_data.get("ready", "0/0")
            restarts = raw_data.get("restarts", 0)
            age = self._format_age(raw_data.get("age", ""))
            node = raw_data.get("node", "")
            
            return {
                "type": "status",
                "summary": f"{pod_name} Pod 상태: {status} (준비: {ready}, 재시작: {restarts}회)",
                "data": {
                    "formatted": {
                        "name": pod_name,
                        "namespace": namespace,
                        "status": status,
                        "ready": ready,
                        "restarts": restarts,
                        "age": age,
                        "node": node
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "is_healthy": status == "Running" and "1/1" in ready
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting status: {str(e)}")
            return self.format_error("status", str(e))
    
    def format_logs(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """로그를 읽기 쉬운 형식으로 포맷"""
        try:
            pod_name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            logs = raw_data.get("logs", "")
            lines = raw_data.get("lines", 0)
            
            # 로그를 줄별로 분리
            log_lines = logs.split('\n') if logs else []
            
            return {
                "type": "logs",
                "summary": f"{pod_name} Pod의 최근 {lines}줄 로그를 조회했습니다.",
                "data": {
                    "formatted": {
                        "pod_name": pod_name,
                        "namespace": namespace,
                        "lines": lines,
                        "log_lines": log_lines,
                        "total_lines": len(log_lines)
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "lines_requested": lines,
                    "lines_returned": len(log_lines)
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting logs: {str(e)}")
            return self.format_error("logs", str(e))
    
    def format_endpoint(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Service 엔드포인트 정보를 포맷"""
        try:
            service_name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            endpoints = raw_data.get("endpoints", [])
            
            formatted_endpoints = []
            for endpoint in endpoints:
                formatted_endpoints.append({
                    "type": endpoint.get("type", ""),
                    "address": endpoint.get("address", ""),
                    "port": endpoint.get("port", ""),
                    "protocol": endpoint.get("protocol", "TCP")
                })
            
            return {
                "type": "endpoint",
                "summary": f"{service_name} Service의 엔드포인트 {len(endpoints)}개를 찾았습니다.",
                "data": {
                    "formatted": {
                        "service_name": service_name,
                        "namespace": namespace,
                        "endpoints": formatted_endpoints
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "total_endpoints": len(endpoints)
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting endpoint: {str(e)}")
            return self.format_error("endpoint", str(e))
    
    def format_list_deployments(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Deployment 목록을 포맷"""
        try:
            deployments = raw_data.get("deployments", [])
            total = len(deployments)
            
            formatted_deployments = []
            for deployment in deployments:
                formatted_deployments.append({
                    "name": deployment.get("name", ""),
                    "namespace": deployment.get("namespace", ""),
                    "replicas": deployment.get("replicas", "0/0"),
                    "ready": deployment.get("ready", "0/0"),
                    "age": self._format_age(deployment.get("age", "")),
                    "image": deployment.get("image", "")
                })
            
            return {
                "type": "list_deployments",
                "summary": f"총 {total}개의 Deployment를 찾았습니다.",
                "data": {
                    "formatted": formatted_deployments,
                    "raw": raw_data
                },
                "metadata": {
                    "total": total
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_deployments: {str(e)}")
            return self.format_error("list_deployments", str(e))
    
    def format_list_services(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Service 목록을 포맷"""
        try:
            services = raw_data.get("services", [])
            total = len(services)
            
            formatted_services = []
            for service in services:
                formatted_services.append({
                    "name": service.get("name", ""),
                    "namespace": service.get("namespace", ""),
                    "type": service.get("type", ""),
                    "cluster_ip": service.get("cluster_ip", ""),
                    "external_ip": service.get("external_ip", ""),
                    "ports": service.get("ports", ""),
                    "age": self._format_age(service.get("age", ""))
                })
            
            return {
                "type": "list_services",
                "summary": f"총 {total}개의 Service를 찾았습니다.",
                "data": {
                    "formatted": formatted_services,
                    "raw": raw_data
                },
                "metadata": {
                    "total": total
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_services: {str(e)}")
            return self.format_error("list_services", str(e))
    
    def format_list_ingresses(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Ingress 목록을 포맷"""
        try:
            ingresses = raw_data.get("ingresses", [])
            total = len(ingresses)
            
            formatted_ingresses = []
            for ingress in ingresses:
                formatted_ingresses.append({
                    "name": ingress.get("name", ""),
                    "namespace": ingress.get("namespace", ""),
                    "class": ingress.get("class", ""),
                    "hosts": ingress.get("hosts", []),
                    "address": ingress.get("address", ""),
                    "age": self._format_age(ingress.get("age", ""))
                })
            
            return {
                "type": "list_ingresses",
                "summary": f"총 {total}개의 Ingress를 찾았습니다.",
                "data": {
                    "formatted": formatted_ingresses,
                    "raw": raw_data
                },
                "metadata": {
                    "total": total
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_ingresses: {str(e)}")
            return self.format_error("list_ingresses", str(e))
    
    def format_list_namespaces(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Namespace 목록을 포맷"""
        try:
            namespaces = raw_data.get("namespaces", [])
            total = len(namespaces)
            
            formatted_namespaces = []
            for namespace in namespaces:
                formatted_namespaces.append({
                    "name": namespace.get("name", ""),
                    "status": namespace.get("status", ""),
                    "age": self._format_age(namespace.get("age", ""))
                })
            
            return {
                "type": "list_namespaces",
                "summary": f"총 {total}개의 Namespace를 찾았습니다.",
                "data": {
                    "formatted": formatted_namespaces,
                    "raw": raw_data
                },
                "metadata": {
                    "total": total
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_namespaces: {str(e)}")
            return self.format_error("list_namespaces", str(e))
    
    def format_get_service(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Service 상세 정보를 포맷"""
        try:
            service_name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            
            return {
                "type": "get_service",
                "summary": f"{service_name} Service의 상세 정보를 조회했습니다.",
                "data": {
                    "formatted": raw_data,
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting get_service: {str(e)}")
            return self.format_error("get_service", str(e))
    
    def format_get_deployment(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Deployment 상세 정보를 포맷"""
        try:
            deployment_name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            
            return {
                "type": "get_deployment",
                "summary": f"{deployment_name} Deployment의 상세 정보를 조회했습니다.",
                "data": {
                    "formatted": raw_data,
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting get_deployment: {str(e)}")
            return self.format_error("get_deployment", str(e))
    
    def format_overview(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """통합 대시보드 데이터를 포맷"""
        try:
            namespace = raw_data.get("namespace", "default")
            deployments = raw_data.get("deployments", [])
            pods = raw_data.get("pods", [])
            services = raw_data.get("services", [])
            
            return {
                "type": "overview",
                "summary": f"{namespace} 네임스페이스 현황: Deployment {len(deployments)}개, Pod {len(pods)}개, Service {len(services)}개",
                "data": {
                    "formatted": {
                        "namespace": namespace,
                        "deployments": deployments,
                        "pods": pods,
                        "services": services
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "deployment_count": len(deployments),
                    "pod_count": len(pods),
                    "service_count": len(services)
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting overview: {str(e)}")
            return self.format_error("overview", str(e))
    
    def format_scale(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """스케일링 결과를 포맷"""
        try:
            owner = raw_data.get("owner", "")
            repo = raw_data.get("repo", "")
            replicas = raw_data.get("replicas", 0)
            
            return {
                "type": "scale",
                "summary": f"{owner}/{repo}을(를) {replicas}개로 스케일링했습니다.",
                "data": {
                    "formatted": {
                        "owner": owner,
                        "repo": repo,
                        "replicas": replicas
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "owner": owner,
                    "repo": repo,
                    "replicas": replicas
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting scale: {str(e)}")
            return self.format_error("scale", str(e))
    
    def format_deploy(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """배포 결과를 포맷"""
        try:
            app_name = raw_data.get("app_name", "")
            environment = raw_data.get("environment", "")
            
            return {
                "type": "deploy",
                "summary": f"{app_name}을(를) {environment} 환경에 배포했습니다.",
                "data": {
                    "formatted": raw_data,
                    "raw": raw_data
                },
                "metadata": {
                    "app_name": app_name,
                    "environment": environment
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting deploy: {str(e)}")
            return self.format_error("deploy", str(e))
    
    def format_deploy_github_repository(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """GitHub 저장소 배포 결과를 포맷"""
        try:
            # raw_data는 이미 formatted 구조를 가지고 있음
            formatted_data = raw_data.get("formatted", raw_data)
            message = formatted_data.get("message", "")
            repository = formatted_data.get("repository", "")
            branch = formatted_data.get("branch", "")
            commit = formatted_data.get("commit", {})
            deployment_status = formatted_data.get("deployment_status", "")
            
            return {
                "type": "deploy_github_repository",
                "summary": message,
                "data": {
                    "formatted": {
                        "status": formatted_data.get("status", "success"),
                        "message": message,
                        "repository": repository,
                        "branch": branch,
                        "commit": commit,
                        "deployment_status": deployment_status
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "repository": repository,
                    "branch": branch,
                    "commit_sha": commit.get("sha", ""),
                    "author": commit.get("author", "")
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting deploy_github_repository: {str(e)}")
            return self.format_error("deploy_github_repository", str(e))
    
    def format_restart(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """재시작 결과를 포맷"""
        try:
            name = raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            
            return {
                "type": "restart",
                "summary": f"{name}을(를) 재시작했습니다.",
                "data": {
                    "formatted": raw_data,
                    "raw": raw_data
                },
                "metadata": {
                    "name": name,
                    "namespace": namespace
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting restart: {str(e)}")
            return self.format_error("restart", str(e))
    
    def format_cost_analysis(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """비용 분석 결과를 포맷"""
        try:
            current_cost = raw_data.get("current_cost", 0)
            optimizations = raw_data.get("optimizations", [])
            
            return {
                "type": "cost_analysis",
                "summary": f"현재 월 예상 비용은 ₩{current_cost:,}입니다. {len(optimizations)}개의 최적화 제안이 있습니다.",
                "data": {
                    "formatted": {
                        "current_cost": current_cost,
                        "optimizations": optimizations
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "current_cost": current_cost,
                    "optimization_count": len(optimizations)
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting cost_analysis: {str(e)}")
            return self.format_error("cost_analysis", str(e))
    
    def format_unknown(self, command: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """알 수 없는 명령어 포맷"""
        return {
            "type": "unknown",
            "summary": f"알 수 없는 명령어 '{command}'의 결과입니다.",
            "data": {
                "formatted": raw_data,
                "raw": raw_data
            },
            "metadata": {
                "command": command
            }
        }
    
    def format_error(self, command: str, error_message: str) -> Dict[str, Any]:
        """에러 응답 포맷"""
        return {
            "type": "error",
            "summary": f"명령어 '{command}' 실행 중 오류가 발생했습니다: {error_message}",
            "data": {
                "formatted": {
                    "error": error_message,
                    "command": command
                },
                "raw": {}
            },
            "metadata": {
                "command": command,
                "has_error": True
            }
        }
    
    def _format_age(self, age_str: str) -> str:
        """Kubernetes age 문자열을 한국어로 포맷"""
        if not age_str:
            return "알 수 없음"
        
        # 이미 포맷된 경우 그대로 반환
        if "일" in age_str or "시간" in age_str or "분" in age_str:
            return age_str
        
        # 간단한 변환 (실제로는 더 정교한 파싱이 필요)
        return age_str
    
    def _format_datetime(self, datetime_str: str) -> str:
        """ISO datetime을 한국어 형식으로 포맷"""
        if not datetime_str:
            return "알 수 없음"
        
        try:
            # ISO 형식 파싱
            dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            # 한국 시간으로 변환
            kst = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return kst.strftime("%Y-%m-%d %H:%M")
        except:
            return datetime_str
