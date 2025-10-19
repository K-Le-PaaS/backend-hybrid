"""
Deployment rollback service for NCP SourceBuild/SourceDeploy

Rollback now uses manifest update approach instead of environment variables.
The run_sourcedeploy function will automatically update the manifest with the
specified image tag during the mirroring process.
"""

from typing import Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from ..models.deployment_history import DeploymentHistory
from ..core.config import get_settings
from .ncp_pipeline import run_sourcebuild, _generate_ncr_image_name, _verify_ncr_manifest_exists
from .user_project_integration import get_integration
from .deployment_history import get_deployment_history_service


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
    # 1. Find deployment history for target commit
    history = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.github_commit_sha == target_commit_sha,
        DeploymentHistory.status == "success"
    ).first()

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No successful deployment found for commit {target_commit_sha[:7]}"
        )

    # 2. Check if NCR image exists for this commit
    image_name = _generate_ncr_image_name(owner, repo)
    image_url = f"{get_settings().ncp_container_registry_url}/{image_name}:{target_commit_sha}"

    verified = await _verify_ncr_manifest_exists(image_url)
    image_exists = verified.get("exists", False)

    # 3. Get integration for build/deploy project IDs
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ or not integ.build_project_id:
        raise HTTPException(
            status_code=404,
            detail=f"No build project found for {owner}/{repo}"
        )

    # 4. Rebuild if image doesn't exist in NCR
    registry = "klepaas-test.kr.ncr.ntruss.com"
    image_repo = f"{registry}/{image_name}"

    # Check if we need to rebuild (image might already exist)
    build_result = None
    if not image_exists:
        # Image doesn't exist, need to rebuild from commit
        from .ncp_pipeline import run_sourcebuild
        build_result = await run_sourcebuild(
            build_project_id=integ.build_project_id,
            image_repo=image_repo,
            commit_sha=target_commit_sha,  # Build this specific commit
            sc_project_id=integ.sc_project_id,
            sc_repo_name=integ.sc_repo_name,
            branch=integ.branch or "main"
        )

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
        tag=target_commit_sha  # Pass specific commit SHA as tag for rollback
    )

    # 7. Record rollback in deployment history
    history_service = get_deployment_history_service()
    await history_service.create_deployment_record(
        app_name=f"{owner}/{repo}",
        environment="production",
        image=image_url,
        git_commit_sha=target_commit_sha,
        deployed_by=user_id,
        deployment_reason=f"Rollback to commit {target_commit_sha[:7]}",
        is_rollback=True,
        rollback_reason=f"Manual rollback to commit {target_commit_sha[:7]}",
        extra_metadata={
            "rollback_from": "latest",
            "target_commit": target_commit_sha,
            "build_id": build_result.get("build_id") if build_result else None,
            "deploy_id": deploy_result.get("deploy_id") if deploy_result else None
        }
    )

    return {
        "status": "success",
        "action": "rollback",
        "target_commit": target_commit_sha,
        "target_commit_short": target_commit_sha[:7],
        "image": image_url,
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
    1. Get recent successful deployments (excluding rollbacks)
    2. Select N-th previous deployment
    3. Call rollback_to_commit with that commit SHA

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        steps_back: How many deployments to go back (1 = previous, 2 = 2 deployments ago, etc.)
        db: Database session
        user_id: Current user ID

    Returns:
        Rollback result
    """
    # 1. Get recent successful deployments (excluding rollbacks)
    # Use created_at for sorting if deployed_at is null
    recent_deployments = db.query(DeploymentHistory).filter(
        DeploymentHistory.github_owner == owner,
        DeploymentHistory.github_repo == repo,
        DeploymentHistory.status == "success",
        DeploymentHistory.is_rollback == False  # Exclude rollbacks
    ).order_by(
        DeploymentHistory.created_at.desc()  # Use created_at instead of deployed_at
    ).limit(steps_back + 5).all()  # Get extra for safety

    if len(recent_deployments) <= steps_back:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough deployment history. Only {len(recent_deployments) - 1} previous deployments available."
        )

    # 2. Get target deployment (current is 0, previous is 1, etc.)
    target_deployment = recent_deployments[steps_back]

    # 3. Check if target is too old (safety check)
    if target_deployment.deployed_at and target_deployment.deployed_at < datetime.utcnow() - timedelta(days=30):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot rollback to deployment older than 30 days (target: {target_deployment.deployed_at})"
        )

    # 4. Call commit-based rollback
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
