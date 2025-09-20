"""
배포 히스토리 서비스

K-Le-PaaS의 배포 이력을 영구 저장하고 관리하는 서비스입니다.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import structlog
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from ..models.deployment_history import (
    DeploymentHistoryModel,
    DeploymentHistoryCreate,
    DeploymentHistoryResponse,
    DeploymentHistoryQuery,
    DeploymentHistoryStats,
    ImageTagType,
    DeploymentStatus
)
from ..core.config import get_settings

logger = structlog.get_logger(__name__)


class DeploymentHistoryService:
    """배포 히스토리 관리 서비스"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.settings = get_settings()

    def _extract_image_tag(self, image: str) -> tuple[Optional[str], ImageTagType]:
        """이미지에서 태그를 추출하고 타입을 판단합니다."""
        if not image or ':' not in image:
            return None, ImageTagType.CUSTOM
        
        tag = image.split(':')[-1]
        
        # SHA 패턴 (40자리 hex)
        if re.match(r'^[a-f0-9]{40}$', tag):
            return tag, ImageTagType.SHA
        
        # SemVer 패턴 (v1.0.0, 1.0.0, 1.0.0-alpha.1 등)
        if re.match(r'^v?\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$', tag):
            return tag, ImageTagType.SEMVER
        
        # Branch 패턴 (main, develop, feature/xxx 등)
        if re.match(r'^[a-zA-Z0-9._/-]+$', tag) and not re.match(r'^\d+\.\d+', tag):
            return tag, ImageTagType.BRANCH
        
        return tag, ImageTagType.CUSTOM

    async def create_deployment_record(
        self,
        app_name: str,
        environment: str,
        image: str,
        replicas: int = 2,
        namespace: Optional[str] = None,
        deployed_by: Optional[str] = None,
        deployment_reason: Optional[str] = None,
        git_commit_sha: Optional[str] = None,
        git_branch: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """새로운 배포 기록을 생성합니다."""
        try:
            # 이미지 태그 추출
            image_tag, tag_type = self._extract_image_tag(image)
            
            # 배포 기록 생성
            deployment_data = DeploymentHistoryCreate(
                app_name=app_name,
                environment=environment,
                image=image,
                image_tag=image_tag,
                image_tag_type=tag_type,
                replicas=replicas,
                namespace=namespace,
                status=DeploymentStatus.PENDING,
                progress=0,
                deployed_by=deployed_by,
                deployment_reason=deployment_reason,
                git_commit_sha=git_commit_sha,
                git_branch=git_branch,
                extra_metadata=extra_metadata
            )
            
            # 데이터베이스에 저장
            deployment_record = DeploymentHistoryModel(
                app_name=deployment_data.app_name,
                environment=deployment_data.environment,
                image=deployment_data.image,
                image_tag=deployment_data.image_tag,
                image_tag_type=deployment_data.image_tag_type.value,
                replicas=deployment_data.replicas,
                namespace=deployment_data.namespace,
                status=deployment_data.status.value,
                progress=deployment_data.progress,
                deployed_by=deployment_data.deployed_by,
                deployment_reason=deployment_data.deployment_reason,
                git_commit_sha=deployment_data.git_commit_sha,
                git_branch=deployment_data.git_branch,
                extra_metadata=deployment_data.extra_metadata,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            self.db.add(deployment_record)
            self.db.commit()
            self.db.refresh(deployment_record)
            
            logger.info(
                "deployment_record_created",
                deployment_id=deployment_record.id,
                app_name=app_name,
                environment=environment,
                image=image,
                image_tag=image_tag,
                tag_type=tag_type.value
            )
            
            return deployment_record.id
            
        except Exception as e:
            logger.error(
                "deployment_record_creation_failed",
                error=str(e),
                app_name=app_name,
                environment=environment,
                image=image
            )
            raise

    async def update_deployment_status(
        self,
        deployment_id: int,
        status: DeploymentStatus,
        progress: Optional[int] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """배포 상태를 업데이트합니다."""
        try:
            deployment = self.db.query(DeploymentHistoryModel).filter(
                DeploymentHistoryModel.id == deployment_id
            ).first()
            
            if not deployment:
                logger.warning("deployment_not_found", deployment_id=deployment_id)
                return False
            
            # 상태 업데이트
            deployment.status = status.value
            if progress is not None:
                deployment.progress = progress
            
            # 배포 완료 시간 설정
            if status == DeploymentStatus.SUCCESS:
                deployment.deployed_at = datetime.now(timezone.utc)
            elif status == DeploymentStatus.FAILED:
                deployment.updated_at = datetime.now(timezone.utc)
            
            # 추가 메타데이터 업데이트
            if extra_metadata:
                if deployment.extra_metadata:
                    deployment.extra_metadata.update(extra_metadata)
                else:
                    deployment.extra_metadata = extra_metadata
            
            deployment.updated_at = datetime.now(timezone.utc)
            
            self.db.commit()
            
            logger.info(
                "deployment_status_updated",
                deployment_id=deployment_id,
                status=status.value,
                progress=progress
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "deployment_status_update_failed",
                error=str(e),
                deployment_id=deployment_id,
                status=status.value
            )
            raise

    async def create_rollback_record(
        self,
        app_name: str,
        environment: str,
        target_image: str,
        rolled_back_from: int,
        rollback_reason: Optional[str] = None,
        deployed_by: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """롤백 기록을 생성합니다."""
        try:
            # 이미지 태그 추출
            image_tag, tag_type = self._extract_image_tag(target_image)
            
            # 롤백 기록 생성
            rollback_data = DeploymentHistoryCreate(
                app_name=app_name,
                environment=environment,
                image=target_image,
                image_tag=image_tag,
                image_tag_type=tag_type,
                replicas=2,  # 기본값
                status=DeploymentStatus.PENDING,
                progress=0,
                deployed_by=deployed_by,
                is_rollback=True,
                rolled_back_from=rolled_back_from,
                rollback_reason=rollback_reason,
                extra_metadata=extra_metadata
            )
            
            # 데이터베이스에 저장
            rollback_record = DeploymentHistoryModel(
                app_name=rollback_data.app_name,
                environment=rollback_data.environment,
                image=rollback_data.image,
                image_tag=rollback_data.image_tag,
                image_tag_type=rollback_data.image_tag_type.value,
                replicas=rollback_data.replicas,
                status=rollback_data.status.value,
                progress=rollback_data.progress,
                deployed_by=rollback_data.deployed_by,
                is_rollback=rollback_data.is_rollback,
                rolled_back_from=rollback_data.rolled_back_from,
                rollback_reason=rollback_data.rollback_reason,
                extra_metadata=rollback_data.extra_metadata,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            
            self.db.add(rollback_record)
            self.db.commit()
            self.db.refresh(rollback_record)
            
            # 원본 배포 기록에 롤백 정보 업데이트
            original_deployment = self.db.query(DeploymentHistoryModel).filter(
                DeploymentHistoryModel.id == rolled_back_from
            ).first()
            
            if original_deployment:
                original_deployment.status = DeploymentStatus.ROLLED_BACK.value
                original_deployment.rolled_back_at = datetime.now(timezone.utc)
                self.db.commit()
            
            logger.info(
                "rollback_record_created",
                rollback_id=rollback_record.id,
                app_name=app_name,
                environment=environment,
                target_image=target_image,
                rolled_back_from=rolled_back_from
            )
            
            return rollback_record.id
            
        except Exception as e:
            logger.error(
                "rollback_record_creation_failed",
                error=str(e),
                app_name=app_name,
                environment=environment,
                target_image=target_image
            )
            raise

    async def get_recent_versions(
        self,
        app_name: str,
        environment: str,
        limit: int = 3
    ) -> List[DeploymentHistoryResponse]:
        """최근 배포 버전들을 조회합니다."""
        try:
            deployments = (
                self.db.query(DeploymentHistoryModel)
                .filter(
                    and_(
                        DeploymentHistoryModel.app_name == app_name,
                        DeploymentHistoryModel.environment == environment
                    )
                )
                .order_by(desc(DeploymentHistoryModel.created_at))
                .limit(limit)
                .all()
            )
            
            return [
                DeploymentHistoryResponse(
                    id=deployment.id,
                    app_name=deployment.app_name,
                    environment=deployment.environment,
                    image=deployment.image,
                    image_tag=deployment.image_tag,
                    image_tag_type=deployment.image_tag_type,
                    replicas=deployment.replicas,
                    namespace=deployment.namespace,
                    status=deployment.status,
                    progress=deployment.progress,
                    deployed_by=deployment.deployed_by,
                    deployment_reason=deployment.deployment_reason,
                    git_commit_sha=deployment.git_commit_sha,
                    git_branch=deployment.git_branch,
                    is_rollback=deployment.is_rollback,
                    rolled_back_from=deployment.rolled_back_from,
                    rollback_reason=deployment.rollback_reason,
                    deployment_name=deployment.deployment_name,
                    service_name=deployment.service_name,
                    configmap_name=deployment.configmap_name,
                    extra_metadata=deployment.extra_metadata,
                    created_at=deployment.created_at,
                    updated_at=deployment.updated_at,
                    deployed_at=deployment.deployed_at,
                    rolled_back_at=deployment.rolled_back_at
                )
                for deployment in deployments
            ]
            
        except Exception as e:
            logger.error(
                "recent_versions_query_failed",
                error=str(e),
                app_name=app_name,
                environment=environment
            )
            raise

    async def get_previous_version(
        self,
        app_name: str,
        environment: str
    ) -> Optional[DeploymentHistoryResponse]:
        """이전 배포 버전을 조회합니다."""
        try:
            # 최근 2개 버전 조회
            deployments = (
                self.db.query(DeploymentHistoryModel)
                .filter(
                    and_(
                        DeploymentHistoryModel.app_name == app_name,
                        DeploymentHistoryModel.environment == environment,
                        DeploymentHistoryModel.is_rollback == False  # 롤백이 아닌 배포만
                    )
                )
                .order_by(desc(DeploymentHistoryModel.created_at))
                .limit(2)
                .all()
            )
            
            if len(deployments) < 2:
                return None
            
            # 두 번째 최근 배포 (이전 버전)
            previous_deployment = deployments[1]
            
            return DeploymentHistoryResponse(
                id=previous_deployment.id,
                app_name=previous_deployment.app_name,
                environment=previous_deployment.environment,
                image=previous_deployment.image,
                image_tag=previous_deployment.image_tag,
                image_tag_type=previous_deployment.image_tag_type,
                replicas=previous_deployment.replicas,
                namespace=previous_deployment.namespace,
                status=previous_deployment.status,
                progress=previous_deployment.progress,
                deployed_by=previous_deployment.deployed_by,
                deployment_reason=previous_deployment.deployment_reason,
                git_commit_sha=previous_deployment.git_commit_sha,
                git_branch=previous_deployment.git_branch,
                is_rollback=previous_deployment.is_rollback,
                rolled_back_from=previous_deployment.rolled_back_from,
                rollback_reason=previous_deployment.rollback_reason,
                deployment_name=previous_deployment.deployment_name,
                service_name=previous_deployment.service_name,
                configmap_name=previous_deployment.configmap_name,
                extra_metadata=previous_deployment.extra_metadata,
                created_at=previous_deployment.created_at,
                updated_at=previous_deployment.updated_at,
                deployed_at=previous_deployment.deployed_at,
                rolled_back_at=previous_deployment.rolled_back_at
            )
            
        except Exception as e:
            logger.error(
                "previous_version_query_failed",
                error=str(e),
                app_name=app_name,
                environment=environment
            )
            raise

    async def query_deployments(self, query: DeploymentHistoryQuery) -> List[DeploymentHistoryResponse]:
        """배포 히스토리를 조회합니다."""
        try:
            # 기본 쿼리
            db_query = self.db.query(DeploymentHistoryModel)
            
            # 필터 적용
            if query.app_name:
                db_query = db_query.filter(DeploymentHistoryModel.app_name == query.app_name)
            
            if query.environment:
                db_query = db_query.filter(DeploymentHistoryModel.environment == query.environment)
            
            if query.status:
                db_query = db_query.filter(DeploymentHistoryModel.status == query.status.value)
            
            if query.image_tag_type:
                db_query = db_query.filter(DeploymentHistoryModel.image_tag_type == query.image_tag_type.value)
            
            if query.is_rollback is not None:
                db_query = db_query.filter(DeploymentHistoryModel.is_rollback == query.is_rollback)
            
            if query.start_time:
                db_query = db_query.filter(DeploymentHistoryModel.created_at >= query.start_time)
            
            if query.end_time:
                db_query = db_query.filter(DeploymentHistoryModel.created_at <= query.end_time)
            
            # 정렬 및 페이징
            db_query = db_query.order_by(desc(DeploymentHistoryModel.created_at))
            db_query = db_query.offset(query.offset).limit(query.limit)
            
            # 결과 조회
            deployments = db_query.all()
            
            return [
                DeploymentHistoryResponse(
                    id=deployment.id,
                    app_name=deployment.app_name,
                    environment=deployment.environment,
                    image=deployment.image,
                    image_tag=deployment.image_tag,
                    image_tag_type=deployment.image_tag_type,
                    replicas=deployment.replicas,
                    namespace=deployment.namespace,
                    status=deployment.status,
                    progress=deployment.progress,
                    deployed_by=deployment.deployed_by,
                    deployment_reason=deployment.deployment_reason,
                    git_commit_sha=deployment.git_commit_sha,
                    git_branch=deployment.git_branch,
                    is_rollback=deployment.is_rollback,
                    rolled_back_from=deployment.rolled_back_from,
                    rollback_reason=deployment.rollback_reason,
                    deployment_name=deployment.deployment_name,
                    service_name=deployment.service_name,
                    configmap_name=deployment.configmap_name,
                    extra_metadata=deployment.extra_metadata,
                    created_at=deployment.created_at,
                    updated_at=deployment.updated_at,
                    deployed_at=deployment.deployed_at,
                    rolled_back_at=deployment.rolled_back_at
                )
                for deployment in deployments
            ]
            
        except Exception as e:
            logger.error("deployment_query_failed", error=str(e), query=query.model_dump())
            raise

    async def get_deployment_stats(
        self,
        app_name: Optional[str] = None,
        environment: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> DeploymentHistoryStats:
        """배포 통계를 조회합니다."""
        try:
            # 기본 쿼리
            base_query = self.db.query(DeploymentHistoryModel)
            
            if app_name:
                base_query = base_query.filter(DeploymentHistoryModel.app_name == app_name)
            
            if environment:
                base_query = base_query.filter(DeploymentHistoryModel.environment == environment)
            
            if start_time:
                base_query = base_query.filter(DeploymentHistoryModel.created_at >= start_time)
            
            if end_time:
                base_query = base_query.filter(DeploymentHistoryModel.created_at <= end_time)
            
            # 전체 통계
            total_deployments = base_query.count()
            successful_deployments = base_query.filter(
                DeploymentHistoryModel.status == DeploymentStatus.SUCCESS.value
            ).count()
            failed_deployments = base_query.filter(
                DeploymentStatus.FAILED.value
            ).count()
            rollback_count = base_query.filter(
                DeploymentHistoryModel.is_rollback == True
            ).count()
            
            # 성공률 계산
            success_rate = (successful_deployments / total_deployments * 100) if total_deployments > 0 else 0.0
            
            # 평균 배포 시간 계산
            successful_deployments_with_time = base_query.filter(
                and_(
                    DeploymentHistoryModel.status == DeploymentStatus.SUCCESS.value,
                    DeploymentHistoryModel.deployed_at.isnot(None)
                )
            ).all()
            
            if successful_deployments_with_time:
                total_time = sum(
                    (deployment.deployed_at - deployment.created_at).total_seconds()
                    for deployment in successful_deployments_with_time
                )
                average_deployment_time = total_time / len(successful_deployments_with_time)
            else:
                average_deployment_time = None
            
            # 최근 배포 조회
            recent_deployments = (
                base_query
                .order_by(desc(DeploymentHistoryModel.created_at))
                .limit(5)
                .all()
            )
            
            recent_deployments_response = [
                DeploymentHistoryResponse(
                    id=deployment.id,
                    app_name=deployment.app_name,
                    environment=deployment.environment,
                    image=deployment.image,
                    image_tag=deployment.image_tag,
                    image_tag_type=deployment.image_tag_type,
                    replicas=deployment.replicas,
                    namespace=deployment.namespace,
                    status=deployment.status,
                    progress=deployment.progress,
                    deployed_by=deployment.deployed_by,
                    deployment_reason=deployment.deployment_reason,
                    git_commit_sha=deployment.git_commit_sha,
                    git_branch=deployment.git_branch,
                    is_rollback=deployment.is_rollback,
                    rolled_back_from=deployment.rolled_back_from,
                    rollback_reason=deployment.rollback_reason,
                    deployment_name=deployment.deployment_name,
                    service_name=deployment.service_name,
                    configmap_name=deployment.configmap_name,
                    extra_metadata=deployment.extra_metadata,
                    created_at=deployment.created_at,
                    updated_at=deployment.updated_at,
                    deployed_at=deployment.deployed_at,
                    rolled_back_at=deployment.rolled_back_at
                )
                for deployment in recent_deployments
            ]
            
            # 이미지 태그 타입별 통계
            tag_type_stats = {}
            tag_type_results = (
                base_query
                .with_entities(
                    DeploymentHistoryModel.image_tag_type,
                    func.count(DeploymentHistoryModel.id)
                )
                .group_by(DeploymentHistoryModel.image_tag_type)
                .all()
            )
            for tag_type, count in tag_type_results:
                tag_type_stats[tag_type] = count
            
            # 환경별 통계
            environment_stats = {}
            environment_results = (
                base_query
                .with_entities(
                    DeploymentHistoryModel.environment,
                    func.count(DeploymentHistoryModel.id)
                )
                .group_by(DeploymentHistoryModel.environment)
                .all()
            )
            for env, count in environment_results:
                environment_stats[env] = count
            
            return DeploymentHistoryStats(
                total_deployments=total_deployments,
                successful_deployments=successful_deployments,
                failed_deployments=failed_deployments,
                rollback_count=rollback_count,
                success_rate=success_rate,
                average_deployment_time=average_deployment_time,
                recent_deployments=recent_deployments_response,
                image_tag_type_stats=tag_type_stats,
                environment_stats=environment_stats
            )
            
        except Exception as e:
            logger.error("deployment_stats_failed", error=str(e))
            raise


# 전역 서비스 인스턴스 (의존성 주입용)
deployment_history_service: Optional[DeploymentHistoryService] = None


def get_deployment_history_service() -> DeploymentHistoryService:
    """배포 히스토리 서비스 인스턴스를 반환합니다."""
    if deployment_history_service is None:
        raise RuntimeError("DeploymentHistoryService not initialized")
    return deployment_history_service


def init_deployment_history_service(db_session: Session) -> None:
    """배포 히스토리 서비스를 초기화합니다."""
    global deployment_history_service
    deployment_history_service = DeploymentHistoryService(db_session)
