"""
NCP SourceDeploy 배포 상태 폴링 서비스

NCP SourceDeploy API로 시작한 배포의 완료 상태를 확인하고
deployment_histories를 업데이트합니다.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import structlog

from ..database import SessionLocal
from ..models.deployment_history import DeploymentHistory
from ..core.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# Import NCP API call function
from .ncp_pipeline import _call_ncp_rest_api


async def poll_deployment_status(
    deploy_history_id: int,
    deploy_project_id: str,
    stage_id: str,  # stage_name 대신 stage_id 사용
    max_wait_seconds: int = 300,  # 5분
    poll_interval: int = 10  # 10초마다 확인
) -> bool:
    """
    NCP SourceDeploy 배포 상태를 폴링하여 완료 여부를 확인합니다.

    Args:
        deploy_history_id: deployment_histories 레코드 ID
        deploy_project_id: NCP SourceDeploy 프로젝트 ID
        stage_id: 스테이지 ID (숫자)
        max_wait_seconds: 최대 대기 시간 (초)
        poll_interval: 폴링 간격 (초)

    Returns:
        배포 성공 여부
    """
    start_time = datetime.now(timezone.utc)
    elapsed = 0

    logger.info(
        "deployment_status_polling_started",
        history_id=deploy_history_id,
        deploy_project_id=deploy_project_id,
        max_wait=max_wait_seconds
    )

    try:
        # NCP SourceDeploy API Gateway (배포 API와 동일한 엔드포인트)
        base = getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com')

        while elapsed < max_wait_seconds:
            # NCP SourceDeploy 상태 조회 API (공식 문서 기준)
            # GET /api/v1/project/{projectId}/history
            # 주의: 쿼리 파라미터는 서명에 포함되지 않음 (path만 서명)
            status_path = f"/api/v1/project/{deploy_project_id}/history"

            try:
                data = await _call_ncp_rest_api('GET', base, status_path, None)

                if not isinstance(data, dict):
                    logger.warning(
                        "unexpected_status_response",
                        history_id=deploy_history_id,
                        response_type=type(data).__name__
                    )
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    continue

                # NCP Response 구조 (공식 문서): result.historyList
                result = data.get('result', {})
                history_list = result.get('historyList', [])

                # 디버그: 실제 응답 내용 로깅
                logger.info(
                    "ncp_api_response",
                    history_id=deploy_history_id,
                    history_count=len(history_list),
                    first_history=history_list[0] if history_list else None
                )

                if not history_list:
                    logger.debug(
                        "no_deployment_history_yet",
                        history_id=deploy_history_id
                    )
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    continue

                # 최신 배포 상태 확인 (첫 번째 항목)
                latest_deploy = history_list[0] if isinstance(history_list, list) else history_list
                deploy_status = latest_deploy.get('status', '').lower()
                ncp_history_id = latest_deploy.get('id')

                logger.debug(
                    "deployment_status_checked",
                    history_id=deploy_history_id,
                    ncp_status=deploy_status,
                    elapsed_seconds=int(elapsed)
                )

                # 완료 상태 확인
                if deploy_status in ['success', 'succeeded', 'complete', 'completed']:
                    # DB 업데이트
                    await _update_deployment_success(deploy_history_id)
                    logger.info(
                        "deployment_completed_successfully",
                        history_id=deploy_history_id,
                        elapsed_seconds=int(elapsed)
                    )
                    return True

                elif deploy_status in ['failed', 'error', 'cancelled']:
                    # 실패 처리
                    await _update_deployment_failed(
                        deploy_history_id,
                        error_message=f"NCP deployment failed: {deploy_status}"
                    )
                    logger.error(
                        "deployment_failed",
                        history_id=deploy_history_id,
                        ncp_status=deploy_status
                    )
                    return False

                # 아직 진행 중
                elif deploy_status in ['running', 'deploying', 'in_progress', 'pending']:
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    continue

                else:
                    logger.warning(
                        "unknown_deployment_status",
                        history_id=deploy_history_id,
                        ncp_status=deploy_status
                    )
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    continue

            except Exception as e:
                logger.error(
                    "deployment_status_check_error",
                    history_id=deploy_history_id,
                    error=str(e)
                )
                await asyncio.sleep(poll_interval)
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                continue

        # 타임아웃
        logger.warning(
            "deployment_status_polling_timeout",
            history_id=deploy_history_id,
            elapsed_seconds=int(elapsed)
        )
        return False

    except Exception as e:
        logger.error(
            "deployment_status_polling_failed",
            history_id=deploy_history_id,
            error=str(e)
        )
        return False


async def _update_deployment_success(deploy_history_id: int) -> None:
    """배포 성공 시 DB 업데이트"""
    db = SessionLocal()
    try:
        history = db.query(DeploymentHistory).filter(
            DeploymentHistory.id == deploy_history_id
        ).first()

        if not history:
            logger.error(
                "deployment_history_not_found",
                history_id=deploy_history_id
            )
            return

        from ..models.deployment_history import get_kst_now
        now = get_kst_now()
        history.status = "success"
        history.sourcedeploy_status = "success"
        history.deployed_at = now
        history.completed_at = now

        # duration 계산 (timezone-naive로 계산)
        if history.started_at:
            delta = now - history.started_at
            history.total_duration = int(delta.total_seconds())

        db.commit()

        logger.info(
            "deployment_history_updated_success",
            history_id=deploy_history_id,
            duration_seconds=history.total_duration
        )

    except Exception as e:
        db.rollback()
        logger.error(
            "deployment_history_update_failed",
            history_id=deploy_history_id,
            error=str(e)
        )
    finally:
        db.close()


async def _update_deployment_failed(
    deploy_history_id: int,
    error_message: str
) -> None:
    """배포 실패 시 DB 업데이트"""
    db = SessionLocal()
    try:
        history = db.query(DeploymentHistory).filter(
            DeploymentHistory.id == deploy_history_id
        ).first()

        if not history:
            logger.error(
                "deployment_history_not_found",
                history_id=deploy_history_id
            )
            return

        from ..models.deployment_history import get_kst_now
        now = get_kst_now()
        history.status = "failed"
        history.sourcedeploy_status = "failed"
        history.completed_at = now
        history.error_message = error_message
        history.error_stage = "sourcedeploy"

        # duration 계산 (timezone-naive로 계산)
        if history.started_at:
            delta = now - history.started_at
            history.total_duration = int(delta.total_seconds())

        db.commit()

        logger.info(
            "deployment_history_updated_failed",
            history_id=deploy_history_id,
            error=error_message
        )

    except Exception as e:
        db.rollback()
        logger.error(
            "deployment_history_update_failed",
            history_id=deploy_history_id,
            error=str(e)
        )
    finally:
        db.close()
