"""
NLP Response Formatter

자연어 명령어의 응답을 사용자 친화적인 형식으로 변환하는 서비스입니다.
각 명령어 타입별로 최적화된 UI 렌더링을 위한 구조화된 데이터를 제공합니다.
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone, timedelta
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
                "k8s_list_namespaced_endpoints": self.format_list_namespaced_endpoints,  # 네임스페이스 엔드포인트 목록
                "rollback_deployment": self.format_rollback_list,
                "get_rollback_list": self.format_rollback_list,  # 롤백 목록 조회 명령어 추가
                "scale": self.format_scale,
                "deploy_application": self.format_deploy,
                "deploy_github_repository": self.format_deploy,  # GitHub 레포지토리 배포
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
            
            # 포맷된 Pod 데이터 (나이 순으로 정렬)
            formatted_pods = []
            for pod in pods:
                formatted_pods.append({
                    "name": pod.get("name", ""),
                    "status": pod.get("phase", "Unknown"),
                    "ready": pod.get("ready", "0/0"),
                    "restarts": pod.get("restarts", 0),
                    "age": self._format_age(pod.get("age", "")),
                    "node": pod.get("node", ""),
                    "namespace": pod.get("namespace", namespace),
                    "_age_seconds": self._parse_age_to_seconds(pod.get("age", ""))  # 정렬용
                })
            
            # 나이 순으로 정렬 (오래된 것부터)
            formatted_pods.sort(key=lambda x: x["_age_seconds"], reverse=True)
            
            # 정렬용 필드 제거
            for pod in formatted_pods:
                del pod["_age_seconds"]
            
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
            service_name = raw_data.get("service_name") or raw_data.get("name", "")
            namespace = raw_data.get("namespace", "default")
            status = raw_data.get("status", "success")
            
            # 에러 상태인 경우
            if status == "error":
                return {
                    "type": "endpoint",
                    "summary": raw_data.get("message", "엔드포인트 조회 실패"),
                    "data": {
                        "formatted": {
                            "service_name": service_name,
                            "namespace": namespace,
                            "status": "error",
                            "message": raw_data.get("message", "")
                        },
                        "raw": raw_data
                    },
                    "metadata": {
                        "namespace": namespace,
                        "status": "error"
                    }
                }
            
            # 서비스 정보
            service_type = raw_data.get("service_type", "ClusterIP")
            cluster_ip = raw_data.get("cluster_ip", "None")
            ports = raw_data.get("ports", [])
            
            # 포트 문자열로 변환
            port_str = ", ".join([f"{p['port']}/{p['protocol']}" for p in ports]) if ports else "None"
            
            # 인그리스 정보
            ingress_name = raw_data.get("ingress_name", "")
            ingress_domain = raw_data.get("ingress_domain")
            ingress_path = raw_data.get("ingress_path", "")
            ingress_port = raw_data.get("ingress_port")
            has_tls = raw_data.get("ingress_has_tls", False)
            
            # 서비스 엔드포인트
            service_endpoint = raw_data.get("service_endpoint")
            
            # 접속 가능한 URL
            accessible_url = raw_data.get("accessible_url")
            
            return {
                "type": "endpoint",
                "summary": f"{service_name} 서비스의 엔드포인트 정보를 조회했습니다.",
                "data": {
                    "formatted": {
                        "service_name": service_name,
                        "service_type": service_type,
                        "cluster_ip": cluster_ip,
                        "ports": port_str,
                        "namespace": namespace,
                        "ingress_name": ingress_name,
                        "ingress_domain": ingress_domain,
                        "ingress_path": ingress_path or "/",
                        "ingress_port": ingress_port,
                        "ingress_has_tls": has_tls,
                        "service_endpoint": service_endpoint,
                        "accessible_url": accessible_url,
                        "message": raw_data.get("message", "")
                    },
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "status": "success"
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
    
    def format_list_namespaced_endpoints(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """네임스페이스별 엔드포인트 목록을 포맷"""
        try:
            namespace = raw_data.get("namespace", "default")
            endpoints = raw_data.get("endpoints", [])
            summary_data = raw_data.get("summary", {})
            
            formatted_endpoints = []
            for endpoint in endpoints:
                # Ingress 도메인 정보 포맷팅
                ingress_domains = []
                for domain_info in endpoint.get("ingress_domains", []):
                    ingress_domains.append({
                        "domain": domain_info.get("domain", ""),
                        "path": domain_info.get("path", "/"),
                        "ingress_name": domain_info.get("ingress_name", "")
                    })
                
                # Port 정보 포맷팅
                ports = []
                for port in endpoint.get("ports", []):
                    port_info = {
                        "port": port.get("port", ""),
                        "target_port": port.get("target_port", ""),
                        "protocol": port.get("protocol", "TCP")
                    }
                    if port.get("node_port"):
                        port_info["node_port"] = port.get("node_port")
                    ports.append(port_info)
                
                # External access 정보
                external_access = None
                if endpoint.get("external_access"):
                    ext = endpoint.get("external_access")
                    external_access = {
                        "type": ext.get("type", "LoadBalancer"),
                        "address": ext.get("address", ""),
                        "ports": ext.get("ports", [])
                    }
                
                formatted_endpoints.append({
                    "service_name": endpoint.get("service_name", ""),
                    "service_type": endpoint.get("service_type", ""),
                    "cluster_ip": endpoint.get("cluster_ip", ""),
                    "ports": ports,
                    "service_endpoint": endpoint.get("service_endpoint", ""),
                    "ingress_domains": ingress_domains,
                    "external_access": external_access
                })
            
            total_services = summary_data.get("total_services", len(formatted_endpoints))
            services_with_ingress = summary_data.get("services_with_ingress", 0)
            services_with_external = summary_data.get("services_with_external", 0)
            
            return {
                "type": "list_endpoints",
                "summary": f"'{namespace}' 네임스페이스에 {total_services}개의 Service가 있습니다. Ingress 설정: {services_with_ingress}개, 외부 접근: {services_with_external}개",
                "data": {
                    "formatted": formatted_endpoints,
                    "raw": raw_data
                },
                "metadata": {
                    "namespace": namespace,
                    "total_services": total_services,
                    "services_with_ingress": services_with_ingress,
                    "services_with_external": services_with_external
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting list_namespaced_endpoints: {str(e)}")
            return self.format_error("list_endpoints", str(e))
    
    def format_list_ingresses(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Ingress 목록을 포맷"""
        try:
            ingresses = raw_data.get("ingresses", [])
            total = len(ingresses)
            
            formatted_ingresses = []
            for ingress in ingresses:
                # TLS 여부 확인 (urls가 https로 시작하는지)
                has_tls = False
                urls = ingress.get("urls", [])
                if urls and any(url.startswith("https://") for url in urls):
                    has_tls = True
                
                # 첫 번째 path 정보 가져오기
                paths = ingress.get("paths", [])
                first_path = paths[0] if paths else {}
                services = ingress.get("services", [])
                
                # addresses는 배열이므로 첫 번째 값 사용
                addresses = ingress.get("addresses", [])
                address = addresses[0] if addresses else ""
                
                formatted_ingresses.append({
                    "name": ingress.get("name", ""),
                    "namespace": ingress.get("namespace", ""),
                    "class": ingress.get("class", ""),
                    "hosts": ingress.get("hosts", []),
                    "urls": urls,
                    "has_tls": has_tls,
                    "service_name": first_path.get("service_name") or (services[0] if services else ""),
                    "port": first_path.get("port"),
                    "path": first_path.get("path", "/"),
                    "address": address,
                    "ports": ingress.get("ports", ""),
                    "age": ingress.get("age", "알 수 없음")
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
        """스케일링 결과를 상세 테이블 형식으로 포맷"""
        try:
            # 디버깅을 위한 로그
            self.logger.info(f"format_scale 호출됨 - raw_data: {raw_data}")
            
            # k8s_result에서 실제 스케일링 결과 추출 (이제 원시 결과)
            k8s_result = raw_data.get("k8s_result", {})
            entities = raw_data.get("entities", {})
            
            self.logger.info(f"k8s_result: {k8s_result}")
            self.logger.info(f"entities: {entities}")
            
            # 스케일링 실행 결과에서 정보 추출
            owner = k8s_result.get("owner", "")
            repo = k8s_result.get("repo", "")
            old_replicas = k8s_result.get("old_replicas", 0)
            new_replicas = k8s_result.get("new_replicas", 0)
            status = k8s_result.get("status", "unknown")
            message = k8s_result.get("message", "")
            
            # 저장소 정보가 없으면 entities에서 추출 (실패 시에도 사용자 입력 정보 사용)
            if not owner or not repo:
                owner = entities.get("github_owner", "")
                repo = entities.get("github_repo", "")
                self.logger.info(f"entities에서 추출한 저장소 정보: {owner}/{repo}")
            
            # replicas 정보가 없으면 entities에서 추출 (실패 시에도 사용자 입력 정보 사용)
            if new_replicas == 0:
                new_replicas = entities.get("replicas", 0)
                self.logger.info(f"entities에서 추출한 replicas: {new_replicas}")
            
            # old_replicas가 없으면 기본값 1 사용 (실패 시에도 의미있는 값 표시)
            if old_replicas == 0:
                old_replicas = 1  # 기본값
                self.logger.info(f"기본값으로 설정한 old_replicas: {old_replicas}")
            
            # 최종 데이터 검증
            self.logger.info(f"최종 추출된 데이터 - owner: {owner}, repo: {repo}, old_replicas: {old_replicas}, new_replicas: {new_replicas}, status: {status}")
            
            # 스케일링 상세 정보 구성
            # 현재 시간을 한국 시간(KST)으로 생성
            kst_timezone = timezone(timedelta(hours=9))
            now_kst = datetime.now(kst_timezone)

            scaling_details = {
                "repository": f"{owner}/{repo}",
                "old_replicas": old_replicas,
                "new_replicas": new_replicas,
                "change": f"{old_replicas} → {new_replicas}",
                "status": "성공" if status == "success" else "실패",
                "timestamp": self._format_datetime(now_kst.isoformat()),
                "action": "스케일링"
            }
            
            # 배포 정보 추출 (있는 경우)
            deploy_result = k8s_result.get("deploy_result", {})
            if deploy_result:
                scaling_details.update({
                    "deploy_project_id": deploy_result.get("deploy_project_id", ""),
                    "stage_id": deploy_result.get("stage_id", ""),
                    "scenario_id": deploy_result.get("scenario_id", ""),
                    "service_url": deploy_result.get("service_url", ""),
                    "image_tag": k8s_result.get("image_tag", "")
                })
            
            # 요약 메시지
            if status == "success":
                summary = f"{owner}/{repo}을(를) {old_replicas}개에서 {new_replicas}개로 스케일링했습니다."
            else:
                summary = f"{owner}/{repo} 스케일링이 실패했습니다."
            
            return {
                "type": "scale",
                "summary": summary,
                "data": {
                    "formatted": scaling_details,
                    "raw": raw_data
                },
                "metadata": {
                    "owner": owner,
                    "repo": repo,
                    "old_replicas": old_replicas,
                    "new_replicas": new_replicas,
                    "status": status
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error formatting scale: {str(e)}")
            return self.format_error("scale", str(e))
    
    def format_deploy(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """배포 결과를 포맷"""
        try:
            # 레포지토리 정보 추출
            repository = raw_data.get("repository", "")
            branch = raw_data.get("branch", "main")

            # 커밋 정보 추출 및 구조화
            commit_info = raw_data.get("commit", {})
            if isinstance(commit_info, dict):
                commit = {
                    "sha": commit_info.get("sha", "unknown"),
                    "message": commit_info.get("message", "커밋 정보 없음"),
                    "author": commit_info.get("author", "Unknown"),
                    "url": commit_info.get("url", "")
                }
            else:
                commit = {
                    "sha": "unknown",
                    "message": "커밋 정보 없음",
                    "author": "Unknown",
                    "url": ""
                }

            # 배포 상태 메시지
            status = raw_data.get("status", "success")
            deployment_status = raw_data.get("deployment_status", "배포가 백그라운드에서 진행됩니다. CI/CD Pipelines 탭에서 진행 상황을 확인하세요.")

            # 메시지 생성
            if status == "success":
                message = raw_data.get("message", f"{repository} 배포를 시작했습니다")
                summary = f"✅ {repository} 배포 시작"
            else:
                message = raw_data.get("message", f"{repository} 배포 시작 중 문제가 발생했습니다")
                summary = f"⚠️ {repository} 배포 오류"

            # 포맷된 응답 구조 (프론트엔드 DeployResponseRenderer와 호환)
            formatted_data = {
                "status": status,
                "message": message,
                "repository": repository,
                "branch": branch,
                "commit": commit,
                "deployment_status": deployment_status
            }

            # 타입 결정 (deploy 또는 deploy_github_repository)
            response_type = "deploy_github_repository" if "github" in repository.lower() or raw_data.get("type") == "deploy_github_repository" else "deploy"

            return {
                "type": response_type,
                "summary": summary,
                "data": {
                    "formatted": formatted_data,
                    "raw": raw_data
                },
                "metadata": {
                    "app_name": raw_data.get("app_name", repository.split("/")[-1] if "/" in repository else repository),
                    "environment": raw_data.get("environment", "production"),
                    "repository": repository,
                    "branch": branch,
                    "status": status
                }
            }
        except Exception as e:
            self.logger.error(f"Error formatting deploy: {str(e)}")
            return self.format_error("deploy", str(e))
    
    def format_restart(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """재시작 결과를 포맷"""
        try:
            # k8s_result에서 재시작 결과 추출
            k8s_result = raw_data.get("k8s_result", raw_data)
            
            owner = k8s_result.get("owner", "")
            repo = k8s_result.get("repo", "")
            deployment = k8s_result.get("deployment", "")
            namespace = k8s_result.get("namespace", "default")
            message = k8s_result.get("message", "")
            status = k8s_result.get("status", "unknown")
            
            # owner/repo가 있으면 그 형식 사용, 없으면 deployment 이름 사용
            if owner and repo:
                display_name = f"{owner}/{repo}"
                summary = f"{display_name}을(를) 재시작했습니다."
                action_icon = "🔄"
                if status == "success":
                    summary = f"✅ {summary}"
                elif status == "error":
                    summary = f"❌ 재시작 실패: {message}"
            elif deployment:
                display_name = deployment
                summary = f"{display_name}을(를) 재시작했습니다."
                action_icon = "🔄"
                if status == "success":
                    summary = f"✅ {summary}"
                elif status == "error":
                    summary = f"❌ 재시작 실패: {message}"
            else:
                display_name = "앱"
                summary = "재시작했습니다." if status == "success" else f"재시작 실패: {message}"
                action_icon = "🔄"
            
            # 상세 정보 구성
            formatted_data = {
                "repository": display_name,
                "deployment": deployment,
                "owner": owner,
                "repo": repo,
                "namespace": namespace,
                "status": status,
                "message": message,
                "action": action_icon,
                "timestamp": k8s_result.get("timestamp", "")
            }
            
            return {
                "type": "restart",
                "summary": summary,
                "data": {
                    "formatted": formatted_data,
                    "raw": raw_data
                },
                "metadata": {
                    "owner": owner,
                    "repo": repo,
                    "deployment": deployment,
                    "namespace": namespace,
                    "status": status
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
    
    def format_unknown_command(self, command: str, suggestions: List[str] = None) -> Dict[str, Any]:
        """알 수 없는 명령어에 대한 사용자 친화적 응답 포맷"""
        if suggestions is None:
            suggestions = [
                "Pod 상태 확인: 'nginx pod 상태 확인해줘'",
                "배포 목록 조회: 'deployment 목록 보여줘'", 
                "서비스 목록 조회: 'service 목록 보여줘'",
                "로그 확인: 'frontend-app pod 로그 50줄 보여줘'",
                "스케일링: 'nginx deployment 스케일 3개로 늘려줘'",
                "롤백: 'frontend-app deployment 롤백해줘'"
            ]
        
        return {
            "type": "unknown",
            "summary": f"죄송합니다. '{command}' 명령을 이해할 수 없습니다. 아래 예시를 참고해주세요.",
            "data": {
                "formatted": {
                    "command": command,
                    "suggestions": suggestions,
                    "message": "사용 가능한 명령어 예시를 확인해보세요."
                },
                "raw": {
                    "command": command,
                    "error_type": "unknown_command"
                }
            },
            "metadata": {
                "command": command,
                "suggestion_count": len(suggestions)
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
    
    def _parse_age_to_seconds(self, age_str: str) -> int:
        """Kubernetes age 문자열을 초 단위로 변환 (정렬용)"""
        if not age_str:
            return 0
        
        import re
        
        # Kubernetes age 형식 파싱 (예: "39d10h2m58s", "13h1m5s", "1h57m30s")
        total_seconds = 0
        
        # 일 단위 (예: "39d", "11d")
        days_match = re.search(r'(\d+)d', age_str)
        if days_match:
            total_seconds += int(days_match.group(1)) * 24 * 3600
        
        # 시간 단위 (예: "10h", "13h", "1h")
        hours_match = re.search(r'(\d+)h', age_str)
        if hours_match:
            total_seconds += int(hours_match.group(1)) * 3600
        
        # 분 단위 (예: "2m", "1m", "57m")
        minutes_match = re.search(r'(\d+)m', age_str)
        if minutes_match:
            total_seconds += int(minutes_match.group(1)) * 60
        
        # 초 단위 (예: "58s", "5s", "30s")
        seconds_match = re.search(r'(\d+)s', age_str)
        if seconds_match:
            total_seconds += int(seconds_match.group(1))
        
        # 이미 포맷된 한국어 형식도 처리 (예: "39일 10시간 2분 58초")
        if "일" in age_str:
            days_kr = re.search(r'(\d+)일', age_str)
            if days_kr:
                total_seconds += int(days_kr.group(1)) * 24 * 3600
        
        if "시간" in age_str:
            hours_kr = re.search(r'(\d+)시간', age_str)
            if hours_kr:
                total_seconds += int(hours_kr.group(1)) * 3600
        
        if "분" in age_str:
            minutes_kr = re.search(r'(\d+)분', age_str)
            if minutes_kr:
                total_seconds += int(minutes_kr.group(1)) * 60
        
        if "초" in age_str:
            seconds_kr = re.search(r'(\d+)초', age_str)
            if seconds_kr:
                total_seconds += int(seconds_kr.group(1))
        
        return total_seconds

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
        """ISO datetime을 한국 시간(KST, UTC+9) 형식으로 포맷"""
        if not datetime_str:
            return "알 수 없음"

        try:
            # ISO 형식 파싱
            dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
            # 한국 시간(KST, UTC+9)으로 변환
            kst_timezone = timezone(timedelta(hours=9))
            kst = dt.astimezone(kst_timezone)
            return kst.strftime("%Y-%m-%d %H:%M")
        except:
            return datetime_str
