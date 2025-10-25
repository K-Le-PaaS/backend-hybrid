"""
클라우드 리소스 비용 추정

NCP, GCP 등 클라우드 리소스의 예상 비용을 계산합니다.
실제 가격 정보는 API나 설정 파일에서 조회할 수 있도록 구현되어 있습니다.
"""

from typing import Dict, Any, Optional
import structlog
from sqlalchemy.orm import Session

from ..models.deployment_history import DeploymentHistory

logger = structlog.get_logger(__name__)


class CostEstimator:
    """클라우드 리소스 비용 추정기"""

    # NCP 가격표 (2025년 기준, 실제 NCP 가격 정보)
    # 서버 스펙별 시간당/월간 가격 (원화)
    NCP_PRICING = {
        "server_specs": {
            "c2-g3": {
                "name": "c2-g3 (2vCPU, 4GB)",
                "vcpu": 2,
                "memory_gb": 4,
                "storage_gb": 0,
                "price_hourly": 92,
                "price_monthly": 66240
            },
            "c2-g3a": {
                "name": "c2-g3a (2vCPU, 4GB)",
                "vcpu": 2,
                "memory_gb": 4,
                "storage_gb": 0,
                "price_hourly": 92,
                "price_monthly": 66240
            },
            "c4-g3": {
                "name": "c4-g3 (4vCPU, 8GB)",
                "vcpu": 4,
                "memory_gb": 8,
                "storage_gb": 0,
                "price_hourly": 192,
                "price_monthly": 138240
            },
            "c4-g3a": {
                "name": "c4-g3a (4vCPU, 8GB)",
                "vcpu": 4,
                "memory_gb": 8,
                "storage_gb": 0,
                "price_hourly": 192,
                "price_monthly": 138240
            },
            "c8-g3": {
                "name": "c8-g3 (8vCPU, 16GB)",
                "vcpu": 8,
                "memory_gb": 16,
                "storage_gb": 0,
                "price_hourly": 392,
                "price_monthly": 282240
            },
            "c8-g3a": {
                "name": "c8-g3a (8vCPU, 16GB)",
                "vcpu": 8,
                "memory_gb": 16,
                "storage_gb": 0,
                "price_hourly": 392,
                "price_monthly": 282240
            },
            "c16-g3": {
                "name": "c16-g3 (16vCPU, 32GB)",
                "vcpu": 16,
                "memory_gb": 32,
                "storage_gb": 0,
                "price_hourly": 792,
                "price_monthly": 570240
            },
            "c16-g3a": {
                "name": "c16-g3a (16vCPU, 32GB)",
                "vcpu": 16,
                "memory_gb": 32,
                "storage_gb": 0,
                "price_hourly": 792,
                "price_monthly": 570240
            },
            "c32-g3": {
                "name": "c32-g3 (32vCPU, 64GB)",
                "vcpu": 32,
                "memory_gb": 64,
                "storage_gb": 0,
                "price_hourly": 1592,
                "price_monthly": 1146240
            },
            "c32-g3a": {
                "name": "c32-g3a (32vCPU, 64GB)",
                "vcpu": 32,
                "memory_gb": 64,
                "storage_gb": 0,
                "price_hourly": 1592,
                "price_monthly": 1146240
            },
            "c48-g3": {
                "name": "c48-g3 (48vCPU, 96GB)",
                "vcpu": 48,
                "memory_gb": 96,
                "storage_gb": 0,
                "price_hourly": 2392,
                "price_monthly": 1722240
            },
            "c48-g3a": {
                "name": "c48-g3a (48vCPU, 96GB)",
                "vcpu": 48,
                "memory_gb": 96,
                "storage_gb": 0,
                "price_hourly": 2392,
                "price_monthly": 1722240
            },
            "c64-g3": {
                "name": "c64-g3 (64vCPU, 128GB)",
                "vcpu": 64,
                "memory_gb": 128,
                "storage_gb": 0,
                "price_hourly": 3192,
                "price_monthly": 2298240
            },
            "c64-g3a": {
                "name": "c64-g3a (64vCPU, 128GB)",
                "vcpu": 64,
                "memory_gb": 128,
                "storage_gb": 0,
                "price_hourly": 3192,
                "price_monthly": 2298240
            }
        },
        "network": {
            "public_ip": {
                "price_hourly": 5.6,
                "price_monthly": 4032  # 30일 기준
            },
            "outbound_traffic": {
                "internet": {
                    "0_20gb": 0,      # 20GB 이하
                    "20gb_5tb": 100,  # 20GB 초과 ~ 5TB 이하
                    "5tb_10tb": 90,   # 5TB 초과 ~ 10TB 이하
                    "10tb_30tb": 80,  # 10TB 초과 ~ 30TB 이하
                    "30tb_over": 70   # 30TB 초과
                },
                "public_ip_cross_zone": 10,  # 다른 존/같은 존 공인 IP
                "private_same_zone": 0,      # 같은 존 비공인 IP
                "private_cross_zone": 10     # 다른 존 비공인 IP
            },
            "inbound_traffic": 0  # 인바운드 트래픽 무료
        },
        "ncr_storage": {
            "price_per_gb_monthly": 100  # GB당 월
        },
        "ncp_sourcedeploy": {
            "build_per_minute": 10,  # 빌드 분당
            "deploy_per_run": 1000   # 배포당
        },
        "load_balancer": {
            "price_monthly": 15000  # 월
        }
    }

    # GCP 가격표 (참고용, 실제로는 API 조회)
    GCP_PRICING = {
        "gke_node": {
            "n1_standard_2": {
                "name": "n1-standard-2 (2vCPU, 7.5GB)",
                "vcpu": 2,
                "memory_gb": 7.5,
                "price_monthly": 60000
            }
        }
    }

    def __init__(self, provider: str = "NCP"):
        """
        Args:
            provider: 클라우드 제공자 ("NCP" 또는 "GCP")
        """
        self.provider = provider

    async def estimate_scaling_cost(
        self,
        current_replicas: int,
        target_replicas: int,
        node_spec: str = "c2-g3a",
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        스케일링 비용 추정 (레플리카 수 변경)

        Args:
            current_replicas: 현재 레플리카 수
            target_replicas: 목표 레플리카 수
            node_spec: 노드 스펙 (예: "c2-g3a", "c4-g3")
            db: 데이터베이스 세션 (선택)

        Returns:
            비용 추정 결과
        """
        if self.provider == "NCP":
            # 노드 스펙 검증
            if node_spec not in self.NCP_PRICING["server_specs"]:
                available_specs = list(self.NCP_PRICING["server_specs"].keys())
                raise ValueError(f"지원하지 않는 노드 스펙입니다. 사용 가능한 스펙: {available_specs}")
            
            pricing = self.NCP_PRICING["server_specs"][node_spec]
        else:
            pricing = self.GCP_PRICING["gke_node"]["n1_standard_2"]

        unit_price = pricing["price_monthly"]
        current_cost = current_replicas * unit_price
        target_cost = target_replicas * unit_price
        additional_cost = target_cost - current_cost

        estimate = {
            "provider": self.provider,
            "resource_type": "Worker Node",
            "node_spec": node_spec,
            "node_type": pricing["name"],
            "current": current_replicas,
            "target": target_replicas,
            "change": target_replicas - current_replicas,
            "unit_price": unit_price,
            "current_monthly_cost": current_cost,
            "target_monthly_cost": target_cost,
            "additional_cost": additional_cost,
            "total_monthly": target_cost,
            "currency": "KRW",
            "period": "monthly"
        }

        logger.info(
            "scaling_cost_estimated",
            current=current_replicas,
            target=target_replicas,
            node_spec=node_spec,
            additional_cost=additional_cost
        )

        return estimate

    async def estimate_deployment_cost(
        self,
        owner: str,
        repo: str,
        estimated_build_time: int = 5,  # 분
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        배포 비용 추정

        Args:
            owner: GitHub 저장소 소유자
            repo: GitHub 저장소 이름
            estimated_build_time: 예상 빌드 시간 (분)
            db: 데이터베이스 세션 (선택)

        Returns:
            비용 추정 결과
        """
        # 이전 배포 히스토리에서 평균 빌드 시간 조회
        if db:
            avg_build_time = await self._get_average_build_time(
                owner, repo, db
            )
            if avg_build_time:
                estimated_build_time = avg_build_time

        if self.provider == "NCP":
            pricing = self.NCP_PRICING["ncp_sourcedeploy"]
        else:
            # GCP는 Cloud Build 가격
            pricing = {"build_per_minute": 15, "deploy_per_run": 0}

        build_cost = estimated_build_time * pricing["build_per_minute"]
        deploy_cost = pricing["deploy_per_run"]
        total_cost = build_cost + deploy_cost

        estimate = {
            "provider": self.provider,
            "resource_type": "Deployment",
            "project": f"{owner}/{repo}",
            "estimated_build_time": estimated_build_time,
            "build_cost": build_cost,
            "deploy_cost": deploy_cost,
            "total_cost": total_cost,
            "currency": "KRW",
            "breakdown": {
                "build": f"{estimated_build_time}분 × {pricing['build_per_minute']}원/분 = {build_cost}원",
                "deploy": f"{deploy_cost}원"
            }
        }

        logger.info(
            "deployment_cost_estimated",
            project=f"{owner}/{repo}",
            build_time=estimated_build_time,
            total_cost=total_cost
        )

        return estimate

    async def get_current_node_cost(
        self,
        node_spec: str,
        node_count: int = 1,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        현재 노드 비용 조회 (케이스 1: 현재 내가 쓰는 노드 비용은?)

        Args:
            node_spec: 노드 스펙 (예: "s2-g2-h50", "s4-g2-h100")
            node_count: 노드 개수
            namespace: 네임스페이스

        Returns:
            현재 노드 비용 정보
        """
        if self.provider != "NCP":
            raise ValueError("현재 NCP만 지원됩니다")

        # 노드 스펙 검증
        if node_spec not in self.NCP_PRICING["server_specs"]:
            available_specs = list(self.NCP_PRICING["server_specs"].keys())
            raise ValueError(f"지원하지 않는 노드 스펙입니다. 사용 가능한 스펙: {available_specs}")

        spec_info = self.NCP_PRICING["server_specs"][node_spec]
        
        # 현재 비용 계산
        current_monthly_cost = node_count * spec_info["price_monthly"]
        current_hourly_cost = node_count * spec_info["price_hourly"]

        result = {
            "provider": self.provider,
            "analysis_type": "current_cost",
            "namespace": namespace,
            "node_spec": node_spec,
            "node_count": node_count,
            "spec_details": {
                "name": spec_info["name"],
                "vcpu": spec_info["vcpu"],
                "memory_gb": spec_info["memory_gb"],
                "storage_gb": spec_info["storage_gb"]
            },
            "costs": {
                "hourly": current_hourly_cost,
                "monthly": current_monthly_cost,
                "currency": "KRW"
            },
            "breakdown": {
                "per_node_hourly": spec_info["price_hourly"],
                "per_node_monthly": spec_info["price_monthly"],
                "total_nodes": node_count
            }
        }

        logger.info(
            "current_node_cost_calculated",
            node_spec=node_spec,
            node_count=node_count,
            monthly_cost=current_monthly_cost
        )

        return result

    async def estimate_scaling_cost_with_specs(
        self,
        current_node_spec: str,
        current_node_count: int,
        target_node_spec: str,
        target_node_count: int,
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        노드 스펙과 개수를 모두 고려한 스케일링 비용 계산

        Args:
            current_node_spec: 현재 노드 스펙
            current_node_count: 현재 노드 개수
            target_node_spec: 목표 노드 스펙
            target_node_count: 목표 노드 개수
            namespace: 네임스페이스

        Returns:
            스케일링 비용 정보
        """
        if self.provider != "NCP":
            raise ValueError("현재 NCP만 지원됩니다")

        # 현재 노드 스펙 검증
        if current_node_spec not in self.NCP_PRICING["server_specs"]:
            available_specs = list(self.NCP_PRICING["server_specs"].keys())
            raise ValueError(f"지원하지 않는 현재 노드 스펙입니다. 사용 가능한 스펙: {available_specs}")

        # 목표 노드 스펙 검증
        if target_node_spec not in self.NCP_PRICING["server_specs"]:
            available_specs = list(self.NCP_PRICING["server_specs"].keys())
            raise ValueError(f"지원하지 않는 목표 노드 스펙입니다. 사용 가능한 스펙: {available_specs}")

        current_spec_info = self.NCP_PRICING["server_specs"][current_node_spec]
        target_spec_info = self.NCP_PRICING["server_specs"][target_node_spec]
        
        # 비용 계산
        current_monthly_cost = current_node_count * current_spec_info["price_monthly"]
        target_monthly_cost = target_node_count * target_spec_info["price_monthly"]
        additional_cost = target_monthly_cost - current_monthly_cost
        change_count = target_node_count - current_node_count

        result = {
            "provider": self.provider,
            "analysis_type": "scaling_cost",
            "namespace": namespace,
            "current_node_spec": current_node_spec,
            "target_node_spec": target_node_spec,
            "scaling": {
                "current_count": current_node_count,
                "target_count": target_node_count,
                "change_count": change_count,
                "change_type": "증가" if change_count > 0 else "감소" if change_count < 0 else "변화 없음"
            },
            "costs": {
                "current_monthly": current_monthly_cost,
                "target_monthly": target_monthly_cost,
                "additional_cost": additional_cost,
                "currency": "KRW"
            },
            "spec_details": {
                "current": {
                    "name": current_spec_info["name"],
                    "vcpu": current_spec_info["vcpu"],
                    "memory_gb": current_spec_info["memory_gb"],
                    "storage_gb": current_spec_info["storage_gb"],
                    "price_per_node_monthly": current_spec_info["price_monthly"]
                },
                "target": {
                    "name": target_spec_info["name"],
                    "vcpu": target_spec_info["vcpu"],
                    "memory_gb": target_spec_info["memory_gb"],
                    "storage_gb": target_spec_info["storage_gb"],
                    "price_per_node_monthly": target_spec_info["price_monthly"]
                }
            },
            "breakdown": {
                "per_node_monthly": target_spec_info["price_monthly"],
                "total_change_cost": additional_cost,
                "monthly_savings": abs(additional_cost) if additional_cost < 0 else 0
            }
        }

        logger.info(
            "scaling_cost_calculated",
            current_spec=current_node_spec,
            current_count=current_node_count,
            target_spec=target_node_spec,
            target_count=target_node_count,
            additional_cost=additional_cost
        )

        return result

    async def estimate_network_cost(
        self,
        public_ip_count: int = 1,
        outbound_traffic_gb: float = 0,
        traffic_type: str = "internet",
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        네트워크 비용 계산 (케이스 3: 네트워크 비용은 얼마나 나올까?)

        Args:
            public_ip_count: Public IP 개수
            outbound_traffic_gb: 아웃바운드 트래픽 (GB)
            traffic_type: 트래픽 타입 ("internet", "public_ip_cross_zone", "private_same_zone", "private_cross_zone")
            namespace: 네임스페이스

        Returns:
            네트워크 비용 정보
        """
        if self.provider != "NCP":
            raise ValueError("현재 NCP만 지원됩니다")

        network_pricing = self.NCP_PRICING["network"]
        
        # Public IP 비용 계산
        public_ip_monthly_cost = public_ip_count * network_pricing["public_ip"]["price_monthly"]
        public_ip_hourly_cost = public_ip_count * network_pricing["public_ip"]["price_hourly"]

        # 트래픽 비용 계산
        traffic_cost = 0
        traffic_breakdown = {}

        if traffic_type == "internet":
            # 인터넷 트래픽 비용 계산
            if outbound_traffic_gb <= 20:
                traffic_cost = 0
                traffic_breakdown["free_tier"] = f"20GB 이하 무료 (사용량: {outbound_traffic_gb}GB)"
            elif outbound_traffic_gb <= 5000:  # 5TB
                traffic_cost = outbound_traffic_gb * network_pricing["outbound_traffic"]["internet"]["20gb_5tb"]
                traffic_breakdown["tier_1"] = f"20GB 초과 ~ 5TB 이하: {outbound_traffic_gb}GB × 100원 = {traffic_cost:,}원"
            elif outbound_traffic_gb <= 10000:  # 10TB
                traffic_cost = outbound_traffic_gb * network_pricing["outbound_traffic"]["internet"]["5tb_10tb"]
                traffic_breakdown["tier_2"] = f"5TB 초과 ~ 10TB 이하: {outbound_traffic_gb}GB × 90원 = {traffic_cost:,}원"
            elif outbound_traffic_gb <= 30000:  # 30TB
                traffic_cost = outbound_traffic_gb * network_pricing["outbound_traffic"]["internet"]["10tb_30tb"]
                traffic_breakdown["tier_3"] = f"10TB 초과 ~ 30TB 이하: {outbound_traffic_gb}GB × 80원 = {traffic_cost:,}원"
            else:
                traffic_cost = outbound_traffic_gb * network_pricing["outbound_traffic"]["internet"]["30tb_over"]
                traffic_breakdown["tier_4"] = f"30TB 초과: {outbound_traffic_gb}GB × 70원 = {traffic_cost:,}원"
        else:
            # 다른 트래픽 타입
            price_per_gb = network_pricing["outbound_traffic"][traffic_type]
            traffic_cost = outbound_traffic_gb * price_per_gb
            traffic_breakdown[traffic_type] = f"{traffic_type}: {outbound_traffic_gb}GB × {price_per_gb}원 = {traffic_cost:,}원"

        # 총 네트워크 비용
        total_monthly_cost = public_ip_monthly_cost + traffic_cost
        total_hourly_cost = public_ip_hourly_cost

        result = {
            "provider": self.provider,
            "analysis_type": "network_cost",
            "namespace": namespace,
            "network_components": {
                "public_ip": {
                    "count": public_ip_count,
                    "monthly_cost": public_ip_monthly_cost,
                    "hourly_cost": public_ip_hourly_cost,
                    "price_per_ip_monthly": network_pricing["public_ip"]["price_monthly"]
                },
                "traffic": {
                    "type": traffic_type,
                    "outbound_gb": outbound_traffic_gb,
                    "cost": traffic_cost,
                    "breakdown": traffic_breakdown
                }
            },
            "costs": {
                "public_ip_monthly": public_ip_monthly_cost,
                "traffic_cost": traffic_cost,
                "total_monthly": total_monthly_cost,
                "total_hourly": total_hourly_cost,
                "currency": "KRW"
            },
            "summary": {
                "inbound_traffic_cost": 0,  # 인바운드 무료
                "outbound_traffic_cost": traffic_cost,
                "public_ip_cost": public_ip_monthly_cost
            }
        }

        logger.info(
            "network_cost_calculated",
            public_ip_count=public_ip_count,
            traffic_gb=outbound_traffic_gb,
            total_cost=total_monthly_cost
        )

        return result

    async def estimate_storage_cost(
        self,
        storage_gb: float,
        operation: str = "add"  # "add" or "remove"
    ) -> Dict[str, Any]:
        """
        스토리지 비용 추정

        Args:
            storage_gb: 스토리지 용량 (GB)
            operation: 작업 타입 ("add" 또는 "remove")

        Returns:
            비용 추정 결과
        """
        if self.provider == "NCP":
            price_per_gb = self.NCP_PRICING["ncr_storage"]["price_per_gb_monthly"]
        else:
            price_per_gb = 150  # GCP GCR 가격 (예시)

        monthly_cost = storage_gb * price_per_gb

        if operation == "remove":
            monthly_cost = -monthly_cost

        estimate = {
            "provider": self.provider,
            "resource_type": "Container Registry Storage",
            "storage_gb": storage_gb,
            "operation": operation,
            "unit_price": price_per_gb,
            "monthly_cost": monthly_cost,
            "currency": "KRW",
            "period": "monthly"
        }

        return estimate

    async def estimate_deletion_savings(
        self,
        resource_type: str,
        resource_count: int = 1
    ) -> Dict[str, Any]:
        """
        리소스 삭제 시 절감 비용 추정

        Args:
            resource_type: 리소스 타입 ("deployment", "service", "load_balancer")
            resource_count: 리소스 개수

        Returns:
            비용 절감 추정 결과
        """
        monthly_savings = 0

        if resource_type == "deployment":
            # 배포 삭제 시 노드 비용 절감 (가정: standard 노드)
            if self.provider == "NCP":
                pricing = self.NCP_PRICING["nks_worker_node"]["standard"]
                monthly_savings = resource_count * pricing["price_monthly"]

        elif resource_type == "load_balancer":
            if self.provider == "NCP":
                monthly_savings = resource_count * self.NCP_PRICING["load_balancer"]["price_monthly"]

        estimate = {
            "provider": self.provider,
            "resource_type": resource_type,
            "resource_count": resource_count,
            "monthly_savings": monthly_savings,
            "annual_savings": monthly_savings * 12,
            "currency": "KRW",
            "note": "실제 절감액은 리소스 사용량에 따라 다를 수 있습니다."
        }

        logger.info(
            "deletion_savings_estimated",
            resource_type=resource_type,
            count=resource_count,
            monthly_savings=monthly_savings
        )

        return estimate

    async def _get_average_build_time(
        self,
        owner: str,
        repo: str,
        db: Session
    ) -> Optional[int]:
        """
        이전 배포의 평균 빌드 시간 조회

        Args:
            owner: GitHub 저장소 소유자
            repo: GitHub 저장소 이름
            db: 데이터베이스 세션

        Returns:
            평균 빌드 시간 (분) 또는 None
        """
        try:
            # 최근 10개 성공한 배포의 duration 조회
            recent_deployments = db.query(DeploymentHistory).filter(
                DeploymentHistory.github_owner == owner,
                DeploymentHistory.github_repo == repo,
                DeploymentHistory.status == "success",
                DeploymentHistory.total_duration.isnot(None)
            ).order_by(
                DeploymentHistory.created_at.desc()
            ).limit(10).all()

            if not recent_deployments:
                return None

            # 평균 계산 (초 → 분)
            total_seconds = sum(
                d.total_duration for d in recent_deployments
            )
            avg_seconds = total_seconds / len(recent_deployments)
            avg_minutes = int(avg_seconds / 60)

            return max(1, avg_minutes)  # 최소 1분

        except Exception as e:
            logger.warning(
                "failed_to_get_average_build_time",
                owner=owner,
                repo=repo,
                error=str(e)
            )
            return None

    def get_cost_comparison(
        self,
        current_estimate: Dict[str, Any],
        target_estimate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        현재 비용과 목표 비용 비교

        Args:
            current_estimate: 현재 비용 추정
            target_estimate: 목표 비용 추정

        Returns:
            비교 결과
        """
        current_cost = current_estimate.get("total_monthly", 0)
        target_cost = target_estimate.get("total_monthly", 0)
        difference = target_cost - current_cost
        percentage_change = (
            (difference / current_cost * 100)
            if current_cost > 0
            else 0
        )

        return {
            "current_cost": current_cost,
            "target_cost": target_cost,
            "difference": difference,
            "percentage_change": round(percentage_change, 2),
            "impact": "증가" if difference > 0 else "감소" if difference < 0 else "변화 없음",
            "currency": "KRW"
        }
