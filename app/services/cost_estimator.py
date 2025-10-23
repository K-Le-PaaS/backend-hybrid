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

    # NCP 가격표 (2025년 기준, 월 단위 원화)
    # 실제 운영 환경에서는 API나 DB에서 조회
    NCP_PRICING = {
        "nks_worker_node": {
            "standard": {
                "name": "Standard (2vCPU, 4GB)",
                "vcpu": 2,
                "memory_gb": 4,
                "price_monthly": 50000
            },
            "high_cpu": {
                "name": "High CPU (4vCPU, 8GB)",
                "vcpu": 4,
                "memory_gb": 8,
                "price_monthly": 100000
            },
            "high_memory": {
                "name": "High Memory (4vCPU, 16GB)",
                "vcpu": 4,
                "memory_gb": 16,
                "price_monthly": 120000
            }
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
        node_type: str = "standard",
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        스케일링 비용 추정

        Args:
            current_replicas: 현재 레플리카 수
            target_replicas: 목표 레플리카 수
            node_type: 노드 타입 ("standard", "high_cpu", "high_memory")
            db: 데이터베이스 세션 (선택)

        Returns:
            비용 추정 결과
        """
        if self.provider == "NCP":
            pricing = self.NCP_PRICING["nks_worker_node"][node_type]
        else:
            pricing = self.GCP_PRICING["gke_node"]["n1_standard_2"]

        unit_price = pricing["price_monthly"]
        current_cost = current_replicas * unit_price
        target_cost = target_replicas * unit_price
        additional_cost = target_cost - current_cost

        estimate = {
            "provider": self.provider,
            "resource_type": "Worker Node",
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
