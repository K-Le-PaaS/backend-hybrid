"""
Deployment rollback service for NCP SourceBuild/SourceDeploy

Rollback now uses manifest update approach instead of environment variables.
The run_sourcedeploy function will automatically update the manifest with the
specified image tag during the mirroring process.
"""

from typing import Dict, Any, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import structlog

from ..models.deployment_history import DeploymentHistory
from ..core.config import get_settings
from .ncp_pipeline import run_sourcebuild, _generate_ncr_image_name, _verify_ncr_manifest_exists
from .user_project_integration import get_integration
from .deployment_history import get_deployment_history_service

logger = structlog.get_logger(__name__)


async def diagnose_rollback_readiness(
    owner: str,
    repo: str,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Diagnose if a repository is ready for rollback operations.

    Returns detailed status including:
    - Project integration status
    - Deployment history availability
    - NCR image availability

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        db: Database session
        user_id: Current user ID

    Returns:
        Diagnostic information with readiness status
    """
    diagnosis = {
        "ready": False,
        "owner": owner,
        "repo": repo,
        "issues": [],
        "warnings": []
    }

    # Check 1: Project integration
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        diagnosis["issues"].append("No project integration found. Set up the project first.")
        return diagnosis

    if not integ.build_project_id:
        diagnosis["issues"].append("Build project ID not configured.")

    if not integ.deploy_project_id:
        diagnosis["issues"].append("Deploy project ID not configured.")

    # Check 2: Deployment history
    recent_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).limit(5).all()

    if not recent_deployments:
        diagnosis["issues"].append("No deployment history found. Deploy the application first.")
        return diagnosis

    diagnosis["deployment_count"] = len(recent_deployments)
    diagnosis["latest_deployment"] = {
        "commit_sha": recent_deployments[0].github_commit_sha,
        "deployed_at": recent_deployments[0].deployed_at.isoformat() if recent_deployments[0].deployed_at else None
    }

    # Check 3: NCR images availability (check latest deployment)
    if recent_deployments:
        latest = recent_deployments[0]
        image_name = _generate_ncr_image_name(owner, repo)
        image_url = f"{get_settings().ncp_container_registry_url}/{image_name}:{latest.github_commit_sha}"

        verified = await _verify_ncr_manifest_exists(image_url)
        if not verified.get("exists"):
            diagnosis["warnings"].append(
                f"Latest deployment image not found in NCR (HTTP {verified.get('code')}). "
                "Rollback will trigger rebuild."
            )

    # Final readiness
    diagnosis["ready"] = len(diagnosis["issues"]) == 0

    return diagnosis


async def rollback_to_commit(
    owner: str,
    repo: str,
    target_commit_sha: str,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Rollback deployment to a specific commit SHA.

    This is for advanced users who know the exact commit they want to rollback to.

    Process:
    1. Find successful deployment record for target commit
    2. Verify NCR image exists for that commit
    3. Rebuild if image doesn't exist (optional)
    4. Deploy the rollback image to production
    5. Record rollback in deployment history

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        target_commit_sha: Exact commit SHA to rollback to
        db: Database session
        user_id: Current user ID

    Returns:
        Rollback result with build status, deploy status, and metadata
    """
    logger.info(f"Starting rollback for {owner}/{repo} to commit {target_commit_sha[:7]}")

    # 1. Get integration first for better error messages
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        logger.error(f"No project integration found for {owner}/{repo} (user_id: {user_id})")
        raise HTTPException(
            status_code=404,
            detail=(
                f"프로젝트 통합 정보를 찾을 수 없습니다: {owner}/{repo}\n"
                f"롤백을 하려면 먼저 프로젝트를 배포하여 통합 정보를 생성해야 합니다.\n"
                f"해결 방법:\n"
                f"1. POST /api/v1/deployments 엔드포인트를 사용하여 최초 배포를 실행하세요.\n"
                f"2. 또는 프로젝트 설정 API를 사용하여 NCP SourceBuild/SourceDeploy 프로젝트 ID를 등록하세요.\n"
                f"사용자 ID: {user_id}, 저장소: {owner}/{repo}"
            )
        )

    logger.info(f"Project integration found: build_project_id={integ.build_project_id}, deploy_project_id={integ.deploy_project_id}")

    if not integ.build_project_id:
        logger.error(f"Build project ID not configured for {owner}/{repo}")
        raise HTTPException(
            status_code=400,
            detail=f"Build project ID not configured for {owner}/{repo}. Please complete project setup."
        )

    if not integ.deploy_project_id:
        logger.error(f"Deploy project ID not configured for {owner}/{repo}")
        raise HTTPException(
            status_code=400,
            detail=f"Deploy project ID not configured for {owner}/{repo}. Please complete project setup."
        )

    # 2. Find deployment history for target commit (support both full and short SHA)
    history = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).filter(
        # Support both full SHA and short SHA (7+ characters)
        (DeploymentHistory.github_commit_sha == target_commit_sha) |
        (DeploymentHistory.github_commit_sha.like(f"{target_commit_sha}%"))
    ).first()

    if not history:
        # Check if ANY deployment exists for debugging
        any_deployment = db.query(DeploymentHistory).filter(
            DeploymentHistory.github_owner == owner,
            DeploymentHistory.github_repo == repo
        ).first()

        if not any_deployment:
            logger.error(f"No deployment history at all for {owner}/{repo}")
            raise HTTPException(
                status_code=404,
                detail=f"No deployment history found for {owner}/{repo}. Deploy the application first before attempting rollback."
            )
        else:
            logger.error(f"No successful deployment found for commit {target_commit_sha[:7]}")
            raise HTTPException(
                status_code=404,
                detail=f"No successful deployment found for commit {target_commit_sha[:7]}. Cannot rollback to undeployed commit."
            )

    logger.info(f"Found deployment history: deployed_at={history.deployed_at}, image={history.image_name}")

    # 3. For rollback, skip NCR image verification and rebuild
    # Rationale: If deployment history exists, the image was already built and exists in NCR
    # NCR verification may fail due to permission issues (403), causing unnecessary rebuilds
    logger.info(f"Rollback to commit {target_commit_sha[:7]}: skipping NCR verification and rebuild")
    logger.info("Image exists in NCR from previous deployment, reusing existing image")

    # Commit the read transaction to avoid SQLite lock issues
    # This allows run_sourcedeploy to start a new transaction for INSERT operations
    db.commit()
    logger.info("Database transaction committed after queries, ready for deployment")

    # 4. Skip rebuild for rollback - reuse existing image from NCR
    build_result = None

    # 5. Deploy with specific rollback tag
    # Manifest will be updated during mirror_and_update_manifest in run_sourcedeploy
    if not integ.deploy_project_id:
        raise HTTPException(
            status_code=404,
            detail=f"No deploy project found for {owner}/{repo}"
        )

    from .ncp_pipeline import run_sourcedeploy
    deploy_result = await run_sourcedeploy(
        deploy_project_id=integ.deploy_project_id,
        stage_name="production",
        scenario_name="deploy-app",
        sc_project_id=integ.sc_project_id,
        db=db,
        user_id=user_id,
        owner=owner,
        repo=repo,
        tag=target_commit_sha,  # Pass specific commit SHA as tag for rollback
        is_rollback=True  # Mark this as a rollback deployment
    )

    # 7. Rollback history is automatically recorded by run_sourcedeploy() with is_rollback=True
    # No need for duplicate recording here - ncp_pipeline.py already handles it
    
    # 롤백 완료 후 데이터베이스 트랜잭션 확실히 커밋
    try:
        db.commit()
        logger.info("Rollback database transaction committed successfully")
    except Exception as e:
        logger.error(f"Failed to commit rollback transaction: {str(e)}")
        db.rollback()
    
    logger.info(
        "rollback_deployment_initiated",
        owner=owner,
        repo=repo,
        target_commit=target_commit_sha[:7],
        deploy_history_id=deploy_result.get("deploy_history_id")
    )

    return {
        "status": "success",
        "action": "rollback",
        "target_commit": target_commit_sha,
        "target_commit_short": target_commit_sha[:7],
        "image": history.image_name,  # Use image from deployment history
        "build_result": build_result,
        "deploy_result": deploy_result,
        "rebuilt": build_result is not None,
        "previous_deployment": {
            "deployed_at": history.deployed_at,
            "deployed_by": getattr(history, 'deployed_by', None),
            "image": history.image_name
        }
    }


async def rollback_to_previous(
    owner: str,
    repo: str,
    steps_back: int,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Rollback to N-th previous successful deployment.

    This is for general users who want to rollback without knowing exact commit SHA.

    Process:
    1. Get the most recent successful deployment (including rollbacks) as current version
    2. Get recent successful original deployments (excluding rollbacks)
    3. Find current version's original commit in history
    4. Select N-th previous deployment from current
    5. Call rollback_to_commit with that commit SHA

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        steps_back: How many deployments to go back (1 = previous, 2 = 2 deployments ago, etc.)
        db: Database session
        user_id: Current user ID

    Returns:
        Rollback result
    """
    logger.info(f"Starting rollback to previous deployment: {owner}/{repo}, steps_back={steps_back}")

    # 1. Get the most recent successful deployment (including rollbacks) to determine current version
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).first()

    if not current_deployment:
        logger.error(f"No deployment history found for {owner}/{repo}")
        raise HTTPException(
            status_code=404,
            detail=(
                f"배포 이력을 찾을 수 없습니다: {owner}/{repo}\n"
                f"롤백을 하려면 먼저 배포 이력이 있어야 합니다.\n"
                f"해결 방법:\n"
                f"1. POST /api/v1/deployments 엔드포인트를 사용하여 최초 배포를 실행하세요.\n"
                f"2. 배포가 성공적으로 완료되면 배포 이력이 자동으로 기록됩니다.\n"
                f"저장소: {owner}/{repo}"
            )
        )

    current_commit_sha = current_deployment.github_commit_sha
    logger.info(f"Current deployment: commit={current_commit_sha[:7]}, is_rollback={current_deployment.is_rollback}")

    # 2. Get all successful ORIGINAL deployments (excluding rollbacks) to build version timeline
    original_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False  # Exclude rollbacks from timeline
    ).order_by(
        DeploymentHistory.created_at.desc()  # Newest first
    ).all()

    if not original_deployments:
        logger.error(f"No original deployment history found for {owner}/{repo}")
        raise HTTPException(
            status_code=404,
            detail=f"원본 배포 이력을 찾을 수 없습니다: {owner}/{repo}"
        )

    logger.info(f"Found {len(original_deployments)} original deployment(s) for {owner}/{repo}")

    # DEBUG: Print all original deployments for debugging
    logger.info("=== ORIGINAL DEPLOYMENTS TIMELINE ===")
    for idx, dep in enumerate(original_deployments):
        logger.info(f"  [{idx}] commit={dep.github_commit_sha[:7]}, created_at={dep.created_at}")
    logger.info("=====================================")

    # 3. Find current commit in original deployment timeline
    # Compare using first 7 characters (short SHA) for robustness
    current_index = None
    current_commit_short = current_commit_sha[:7] if current_commit_sha else ""

    for idx, dep in enumerate(original_deployments):
        dep_commit_short = dep.github_commit_sha[:7] if dep.github_commit_sha else ""
        if dep_commit_short == current_commit_short:
            current_index = idx
            logger.info(f"FOUND: Current commit {current_commit_short} matches index {current_index} in original timeline")
            break

    if current_index is None:
        logger.warning(f"WARNING: Current commit {current_commit_short} not found in original deployments, using index 0")
        current_index = 0

    # 4. Calculate target index (current + steps_back)
    target_index = current_index + steps_back
    logger.info(f"CALCULATION: current_index={current_index} + steps_back={steps_back} = target_index={target_index}")

    if target_index >= len(original_deployments):
        available = len(original_deployments) - current_index - 1
        logger.error(f"Not enough deployment history: available={available}, requested={steps_back}")
        raise HTTPException(
            status_code=400,
            detail=(
                f"배포 이력이 부족합니다.\n"
                f"현재 버전({current_commit_sha[:7]})에서 {available}개의 이전 버전만 사용 가능하지만, "
                f"{steps_back}단계 이전으로 롤백을 요청했습니다.\n"
                f"사용 가능한 롤백 범위: 1~{available}단계"
            )
        )

    # 5. Get target deployment
    target_deployment = original_deployments[target_index]
    logger.info(
        f"TARGET SELECTED: "
        f"commit={target_deployment.github_commit_sha[:7]} (full: {target_deployment.github_commit_sha}), "
        f"deployed_at={target_deployment.deployed_at}, "
        f"index={target_index}"
    )

    # 6. Check if target is too old (safety check)
    from ..models.deployment_history import get_kst_now
    if target_deployment.deployed_at and target_deployment.deployed_at < get_kst_now() - timedelta(days=30):
        raise HTTPException(
            status_code=400,
            detail=f"30일 이상 된 배포로는 롤백할 수 없습니다 (target: {target_deployment.deployed_at})"
        )

    # Commit the read transaction to avoid SQLite lock issues
    db.commit()
    logger.info("Database transaction committed after deployment history query")

    # 7. Call commit-based rollback
    return await rollback_to_commit(
        owner=owner,
        repo=repo,
        target_commit_sha=target_deployment.github_commit_sha,
        db=db,
        user_id=user_id
    )


async def get_rollback_candidates(
    owner: str,
    repo: str,
    db: Session,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Get list of deployments that can be rolled back to.

    Returns recent successful deployments with their metadata.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        db: Database session
        limit: Maximum number of candidates to return

    Returns:
        List of rollback candidates with metadata
    """
    deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False
    ).order_by(
        DeploymentHistory.created_at.desc()  # Use created_at instead of deployed_at
    ).limit(limit).all()

    candidates = []
    for idx, dep in enumerate(deployments):
        # Check if NCR image still exists
        image_name = _generate_ncr_image_name(owner, repo)
        image_url = f"klepaas-test.kr.ncr.ntruss.com/{image_name}:{dep.github_commit_sha}"

        # Don't await verification for listing (too slow), just construct URL
        candidates.append({
            "steps_back": idx,
            "commit_sha": dep.github_commit_sha,
            "commit_sha_short": dep.github_commit_sha[:7] if dep.github_commit_sha else "unknown",
            "deployed_at": dep.deployed_at.isoformat() if dep.deployed_at else None,
            "deployed_by": getattr(dep, 'deployed_by', None),
            "image": image_url,
            "can_rollback": True,  # Assume true, verify on actual rollback
            "is_current": idx == 0,
            "deployment_reason": getattr(dep, 'deployment_reason', None)
        })

    return {
        "owner": owner,
        "repo": repo,
        "total_candidates": len(candidates),
        "candidates": candidates
    }


async def get_rollback_list(
    owner: str,
    repo: str,
    db: Session,
    limit: int = 10
) -> Dict[str, Any]:
    """
    롤백 목록 조회 내부 로직
    """
    # 1. 현재 배포 상태 조회 (가장 최근 성공한 배포, 롤백 포함)
    # 롤백 완료 직후에는 deployed_at이 None일 수 있으므로 created_at 우선으로 조회
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.created_at.desc()  # created_at 우선으로 정렬
    ).first()
    
    # 롤백 완료 직후 deployed_at이 아직 설정되지 않은 경우를 위해
    # running 상태의 롤백 배포도 고려
    if not current_deployment:
        current_deployment = db.query(DeploymentHistory).filter(
            DeploymentHistory.github_owner == owner,
            DeploymentHistory.github_repo == repo,
            DeploymentHistory.status == "running",
            DeploymentHistory.is_rollback == True
        ).order_by(
            DeploymentHistory.created_at.desc()
        ).first()
    
    # 마지막 시도: 최근 배포 이력 (상태 무관)
    if not current_deployment:
        current_deployment = db.query(DeploymentHistory).filter(
            DeploymentHistory.github_owner == owner,
            DeploymentHistory.github_repo == repo
        ).order_by(
            DeploymentHistory.created_at.desc()
        ).first()
    
    current_state = None
    if current_deployment:
        try:
            logger.info(f"get_rollback_list - Found current_deployment: id={current_deployment.id}, "
                       f"commit={current_deployment.github_commit_sha}, "
                       f"status={current_deployment.status}, "
                       f"is_rollback={current_deployment.is_rollback}, "
                       f"deployed_at={current_deployment.deployed_at}")

            current_state = {
                "commit_sha": current_deployment.github_commit_sha or "",
                "commit_sha_short": current_deployment.github_commit_sha[:7] if current_deployment.github_commit_sha else "unknown",
                "commit_message": current_deployment.github_commit_message or "메시지 없음",
                "deployed_at": current_deployment.deployed_at.isoformat() if current_deployment.deployed_at else None,
                "is_rollback": current_deployment.is_rollback or False,
                "deployment_id": current_deployment.id
            }
            logger.info(f"get_rollback_list - Created current_state: {current_state}")
        except Exception as e:
            logger.error(f"Error processing current deployment: {str(e)}", exc_info=True)
            current_state = None
    else:
        logger.warning(f"get_rollback_list - No current_deployment found for {owner}/{repo}")
    
    # 2. 롤백 가능한 버전 목록 (원본 배포만, is_rollback=False)
    original_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).limit(limit).all()
    
    available_versions = []
    current_commit_short = current_deployment.github_commit_sha[:7] if current_deployment and current_deployment.github_commit_sha else ""
    
    for idx, dep in enumerate(original_deployments):
        try:
            dep_commit_short = dep.github_commit_sha[:7] if dep.github_commit_sha else ""
            is_current = (dep_commit_short == current_commit_short)
            
            available_versions.append({
                "steps_back": idx,
                "commit_sha": dep.github_commit_sha or "",
                "commit_sha_short": dep_commit_short,
                "commit_message": dep.github_commit_message or "메시지 없음",
                "deployed_at": dep.deployed_at.isoformat() if dep.deployed_at else None,
                "is_current": is_current
            })
        except Exception as e:
            logger.error(f"Error processing deployment {idx}: {str(e)}")
            continue
    
    # 3. 최근 롤백 히스토리 (is_rollback=True, 최대 5개)
    recent_rollbacks = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == True
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).limit(5).all()
    
    rollback_history = []
    for rb in recent_rollbacks:
        try:
            rollback_history.append({
                "commit_sha_short": rb.github_commit_sha[:7] if rb.github_commit_sha else "unknown",
                "commit_message": rb.github_commit_message or "메시지 없음",
                "rolled_back_at": rb.deployed_at.isoformat() if rb.deployed_at else None,
                "rollback_from_id": rb.rollback_from_id
            })
        except Exception as e:
            logger.error(f"Error processing rollback history: {str(e)}")
            continue
    
    return {
        "owner": owner,
        "repo": repo,
        "current_state": current_state,
        "available_versions": available_versions,
        "total_available": len(available_versions),
        "rollback_history": rollback_history,
        "total_rollbacks": len(rollback_history)
    }


async def scale_deployment(
    owner: str,
    repo: str,
    replicas: int,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Scale deployment by updating replicas in SourceCommit manifest and redeploying.

    Process:
    1. Get project integration and current deployment
    2. Update replicas in SourceCommit k8s/deployment.yaml (using ncp_pipeline)
    3. Trigger SourceDeploy with same image tag

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        replicas: Target number of replicas
        db: Database session
        user_id: Current user ID

    Returns:
        Scaling result with deploy status and metadata
    """
    logger.info(f"Starting scaling for {owner}/{repo} to {replicas} replicas")

    # Validation
    if replicas < 0:
        raise HTTPException(
            status_code=400,
            detail=f"레플리카 수는 0 이상이어야 합니다: {replicas}"
        )

    if replicas > 10:
        raise HTTPException(
            status_code=400,
            detail=f"레플리카 수는 최대 10개까지 가능합니다: {replicas}"
        )

    # 1. Get integration
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        logger.error(f"No project integration found for {owner}/{repo} (user_id: {user_id})")
        raise HTTPException(
            status_code=404,
            detail=(
                f"프로젝트 통합 정보를 찾을 수 없습니다: {owner}/{repo}\n"
                f"스케일링을 하려면 먼저 프로젝트를 배포하여 통합 정보를 생성해야 합니다.\n"
                f"해결 방법:\n"
                f"1. POST /api/v1/deployments 엔드포인트를 사용하여 최초 배포를 실행하세요.\n"
                f"사용자 ID: {user_id}, 저장소: {owner}/{repo}"
            )
        )

    if not integ.sc_project_id:
        raise HTTPException(
            status_code=400,
            detail=f"SourceCommit project ID not configured for {owner}/{repo}"
        )

    if not integ.deploy_project_id:
        raise HTTPException(
            status_code=400,
            detail=f"Deploy project ID not configured for {owner}/{repo}"
        )

    # 2. Get current deployment to find current image tag
    current_deployment = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success"
    ).order_by(
        DeploymentHistory.created_at.desc()
    ).first()

    if not current_deployment:
        raise HTTPException(
            status_code=404,
            detail=f"배포 이력을 찾을 수 없습니다: {owner}/{repo}. 먼저 배포를 실행하세요."
        )

    current_image_tag = current_deployment.github_commit_sha
    logger.info(f"Current deployment image tag: {current_image_tag[:7]}")

    # 3. Update manifest using deployment logic (mirror + update)
    settings = get_settings()
    from .ncp_pipeline import mirror_and_update_manifest, run_sourcedeploy, _generate_ncr_image_name

    # Get GitHub token for mirror operation
    from .github_app import github_app_auth
    github_token, _ = await github_app_auth.get_installation_token_for_repo(owner, repo, db)
    github_repo_url = f"https://github.com/{owner}/{repo}.git"

    # Generate image repo URL
    image_name = _generate_ncr_image_name(owner, repo)
    image_repo = f"{settings.ncp_container_registry_url}/{image_name}"
    actual_sc_repo_name = integ.sc_repo_name or repo

    logger.info(
        f"Scaling: Updating manifest with replicas={replicas}, "
        f"image_tag={current_image_tag[:7]}, sc_repo={actual_sc_repo_name}"
    )

    # Mirror GitHub to SourceCommit and update manifest (image + replicas)
    mirror_result = mirror_and_update_manifest(
        github_repo_url=github_repo_url,
        installation_or_access_token=github_token,
        sc_project_id=integ.sc_project_id,
        sc_repo_name=actual_sc_repo_name,
        image_repo=image_repo,
        image_tag=current_image_tag,  # Keep same image
        sc_endpoint=settings.ncp_sourcecommit_endpoint,
        replicas=replicas  # Update replicas
    )

    old_replicas = mirror_result.get("old_replicas", 1)
    logger.info(f"Manifest updated via mirror_and_update_manifest")

    # Commit DB transaction before triggering deploy
    db.commit()
    logger.info("Database transaction committed, ready for deployment")

    # 4. Trigger SourceDeploy with same image tag
    # Skip mirror since we already updated the manifest above

    deploy_result = await run_sourcedeploy(
        deploy_project_id=integ.deploy_project_id,
        stage_name="production",
        scenario_name="deploy-app",
        sc_project_id=integ.sc_project_id,
        db=db,
        user_id=user_id,
        owner=owner,
        repo=repo,
        tag=current_image_tag,  # Use same image, just update replicas
        is_rollback=False,  # This is scaling, not rollback
        skip_mirror=True  # Skip mirror since manifest was already updated above
    )

    logger.info(
        "scaling_deployment_completed",
        owner=owner,
        repo=repo,
        replicas=replicas,
        old_replicas=old_replicas,
        deploy_history_id=deploy_result.get("deploy_history_id")
    )

    return {
        "status": "success",
        "action": "scale",
        "owner": owner,
        "repo": repo,
        "old_replicas": old_replicas,
        "new_replicas": replicas,
        "image_tag": current_image_tag[:7],
        "deploy_result": deploy_result,
        "message": f"Deployment scaled from {old_replicas} to {replicas} replicas"
    }
