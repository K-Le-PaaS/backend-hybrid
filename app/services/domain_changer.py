"""
도메인 변경 서비스

NCP SourceCommit의 인그레스 매니페스트를 수정하여 사용자 도메인을 변경합니다.
rollback.py의 scale_deployment 패턴을 참고하여 구현.
"""

import logging
import subprocess
import shutil
import yaml
from pathlib import Path
from typing import Dict, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException
from urllib.parse import quote

from ..core.config import get_settings
from ..models.deployment_history import DeploymentHistory
from .pipeline_user_url import upsert_deployment_url, is_domain_available, extract_url_from_ingress_yaml

logger = logging.getLogger(__name__)


def get_integration(db: Session, user_id: str, owner: str, repo: str):
    """프로젝트 integration 조회"""
    from ..models.user_project_integration import UserProjectIntegration

    return db.query(UserProjectIntegration).filter(
        UserProjectIntegration.user_id == user_id,
        UserProjectIntegration.github_owner == owner,
        UserProjectIntegration.github_repo == repo
    ).first()


async def change_domain(
    owner: str,
    repo: str,
    new_domain: str,
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    도메인 변경 (rollback.py의 scale_deployment 패턴)

    작업 흐름:
    1. 프로젝트 integration 확인
    2. 도메인 중복 체크
    3. SourceCommit ingress.yaml 수정 (mirror_to_sourcecommit 패턴)
    4. SourceDeploy 트리거 (기존 이미지로 재배포)
    5. deployment_url DB 갱신
    """
    logger.info(f"Starting domain change for {owner}/{repo} to {new_domain}")

    # 1. 도메인 형식 정규화
    if "." not in new_domain:
        new_domain = f"{new_domain}.klepaas.app"

    # 도메인 검증
    if len(new_domain) > 255:
        raise HTTPException(
            status_code=400,
            detail=f"도메인이 너무 깁니다 (최대 255자): {new_domain}"
        )

    # 2. 도메인 중복 체크
    if not is_domain_available(db, new_domain, exclude_owner=owner, exclude_repo=repo):
        raise HTTPException(
            status_code=409,
            detail=f"도메인 '{new_domain}'은 이미 사용 중입니다. 다른 도메인을 선택해주세요."
        )

    # 3. Get integration (rollback.py 패턴)
    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
    if not integ:
        logger.error(f"No project integration found for {owner}/{repo} (user_id: {user_id})")
        raise HTTPException(
            status_code=404,
            detail=(
                f"프로젝트 통합 정보를 찾을 수 없습니다: {owner}/{repo}\n"
                f"도메인을 변경하려면 먼저 프로젝트를 배포하여 통합 정보를 생성해야 합니다.\n"
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

    # 4. Get current deployment (rollback.py 패턴)
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

    # 5. Update ingress in SourceCommit (mirror_to_sourcecommit 패턴)
    settings = get_settings()
    actual_sc_repo_name = integ.sc_repo_name or repo

    logger.info(
        f"Domain change: Updating ingress with domain={new_domain}, "
        f"sc_repo={actual_sc_repo_name}"
    )

    # Get GitHub token (rollback.py 패턴)
    from .github_app import github_app_auth
    github_token, _ = await github_app_auth.get_installation_token_for_repo(owner, repo, db)

    # Update ingress.yaml in SourceCommit
    old_domain = _update_ingress_in_sourcecommit(
        sc_project_id=integ.sc_project_id,
        sc_repo_name=actual_sc_repo_name,
        new_domain=new_domain,
        sc_username=settings.ncp_sourcecommit_username,
        sc_password=settings.ncp_sourcecommit_password
    )

    logger.info(f"Ingress updated: {old_domain} → {new_domain}")

    # Commit DB transaction before triggering deploy (rollback.py 패턴)
    db.commit()
    logger.info("Database transaction committed, ready for deployment")

    # 6. Trigger SourceDeploy (rollback.py 패턴)
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
        tag=current_image_tag,  # Use same image
        is_rollback=False,
        skip_mirror=True  # Skip mirror since ingress was already updated
    )

    # 7. Update deployment_url DB
    upsert_deployment_url(
        db=db,
        user_id=user_id,
        github_owner=owner,
        github_repo=repo,
        url=f"https://{new_domain}",
        is_user_modified=True  # User explicitly changed the domain
    )

    logger.info(
        "domain_change_completed",
        owner=owner,
        repo=repo,
        old_domain=old_domain,
        new_domain=new_domain,
        deploy_history_id=deploy_result.get("deploy_history_id"),
        saved_to_db=True
    )

    return {
        "status": "success",
        "action": "change_domain",
        "owner": owner,
        "repo": repo,
        "old_domain": old_domain,
        "new_domain": new_domain,
        "image_tag": current_image_tag[:7],
        "deploy_result": deploy_result,
        "message": f"도메인이 {old_domain}에서 {new_domain}으로 변경되었습니다"
    }


def _update_ingress_in_sourcecommit(
    sc_project_id: str,
    sc_repo_name: str,
    new_domain: str,
    sc_username: str,
    sc_password: str
) -> str:
    """
    SourceCommit의 k8s/ingress.yaml 수정
    ncp_pipeline.py의 mirror_to_sourcecommit 로직 참고
    """
    import uuid
    from .ncp_pipeline import get_sourcecommit_repo_public_url

    work_dir = Path("/tmp") / f"domain-change-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    sc_dir = work_dir / "sc_repo"
    old_domain = None

    try:
        # Compose SourceCommit URL (ncp_pipeline 패턴)
        try:
            resolved = get_sourcecommit_repo_public_url(sc_project_id, sc_repo_name)
        except Exception:
            resolved = None
        sc_url = resolved or f"https://zzcaypok.devtools.ncloud.com/{sc_project_id}/{sc_repo_name}.git"

        # Basic auth (ncp_pipeline 패턴)
        u_raw = (sc_username or "").strip()
        p_raw = (sc_password or "").strip()
        if u_raw or p_raw:
            user = quote(u_raw or "token", safe="")
            pwd = quote(p_raw or "x", safe="")
            sc_url = sc_url.replace("https://", f"https://{user}:{pwd}@", 1)

        logger.info(f"Cloning SourceCommit: {sc_project_id}/{sc_repo_name}")

        # Clone SourceCommit (ncp_pipeline 패턴)
        subprocess.run(
            ["git", "clone", sc_url, str(sc_dir)],
            check=True,
            capture_output=True,
            text=True
        )

        logger.info(f"Clone successful: {sc_dir}")

        # Checkout main branch (ncp_pipeline 패턴)
        try:
            subprocess.run(["git", "-C", str(sc_dir), "checkout", "main"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            # Try creating main branch if it doesn't exist
            subprocess.run(["git", "-C", str(sc_dir), "checkout", "-b", "main"], check=True, capture_output=True, text=True)

        # Update ingress.yaml
        ingress_path = sc_dir / "k8s" / "ingress.yaml"

        if not ingress_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"ingress.yaml not found in {sc_project_id}/{sc_repo_name}/k8s/"
            )

        # Read and parse ingress.yaml
        with open(ingress_path, 'r', encoding='utf-8') as f:
            ingress_content = f.read()
            ingress = yaml.safe_load(ingress_content)

        # Extract old domain
        old_domain_from_yaml = extract_url_from_ingress_yaml(ingress_content)
        if old_domain_from_yaml:
            old_domain = old_domain_from_yaml.replace("https://", "").replace("http://", "")

        logger.info(f"Current ingress domain: {old_domain}")

        # Update spec.rules[].host
        if 'spec' in ingress and 'rules' in ingress['spec']:
            for rule in ingress['spec']['rules']:
                if 'host' in rule:
                    rule['host'] = new_domain
                    logger.info(f"Updated rule host to: {new_domain}")

        # Update spec.tls[].hosts[]
        if 'spec' in ingress and 'tls' in ingress['spec']:
            for tls in ingress['spec']['tls']:
                if 'hosts' in tls:
                    tls['hosts'] = [new_domain]
                    logger.info(f"Updated TLS hosts to: {new_domain}")

        # Write updated ingress.yaml
        with open(ingress_path, 'w', encoding='utf-8') as f:
            yaml.dump(ingress, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info(f"Ingress YAML updated with new domain: {new_domain}")

        # Git commit and push (ncp_pipeline 패턴)
        subprocess.run(
            ["git", "-C", str(sc_dir), "config", "user.email", "bot@k-le-paas.local"],
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "-C", str(sc_dir), "config", "user.name", "K-Le-PaaS Bot"],
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "-C", str(sc_dir), "add", "k8s/ingress.yaml"],
            check=True, capture_output=True, text=True
        )

        commit_msg = f"chore: update domain to {new_domain}"
        subprocess.run(
            ["git", "-C", str(sc_dir), "commit", "-m", commit_msg],
            check=True, capture_output=True, text=True
        )

        # Get current branch
        branch_result = subprocess.run(
            ["git", "-C", str(sc_dir), "branch", "--show-current"],
            capture_output=True, text=True
        )
        current_branch = branch_result.stdout.strip() or "main"

        # Pull first (ncp_pipeline 패턴)
        logger.info(f"Pulling from origin/{current_branch}")
        try:
            subprocess.run(
                ["git", "-C", str(sc_dir), "pull", "origin", current_branch, "--rebase"],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Pull failed: {e.stderr[:200] if e.stderr else str(e)}")

        # Push to origin
        logger.info(f"Pushing to origin/{current_branch}")
        subprocess.run(
            ["git", "-C", str(sc_dir), "push", "origin", current_branch],
            check=True, capture_output=True, text=True
        )

        logger.info(f"Successfully pushed ingress changes to SourceCommit")

        return old_domain or "unknown"

    except subprocess.CalledProcessError as e:
        error_detail = e.stderr if hasattr(e, 'stderr') else str(e)
        logger.error(f"Git error during ingress update: {error_detail}")
        raise HTTPException(status_code=400, detail=f"Git error during ingress update: {error_detail}")
    except Exception as e:
        logger.error(f"Unexpected error during ingress update: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error during ingress update: {str(e)}")
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info(f"Cleaned up work directory: {work_dir}")
        except Exception:
            pass
