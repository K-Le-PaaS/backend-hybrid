"""
파이프라인 사용자 URL 관리 서비스

배포된 애플리케이션의 사용자 접근 URL을 관리합니다.
인그레스 매니페스트에서 URL을 추출하고 DB에 저장/조회합니다.
"""

import logging
import yaml
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from ..models.deployment_url import DeploymentUrl

logger = logging.getLogger(__name__)


def generate_service_url(repo_name: str, domain: str = "klepaas.app") -> str:
    """
    레포지토리 이름으로부터 서비스 URL을 생성합니다.

    Args:
        repo_name: 레포지토리 이름 (예: "test01", "k-le-paas-test02")
        domain: 도메인 (기본값: "klepaas.app")

    Returns:
        서비스 URL (예: "https://test01.klepaas.app")
    """
    # 레포지토리 이름을 소문자로 변환
    repo_part = repo_name.lower()

    # URL 생성 (HTTPS 프로토콜 포함)
    url = f"https://{repo_part}.{domain}"

    logger.info(f"Generated service URL: {url} from repo: {repo_name}")
    return url


def extract_url_from_ingress_yaml(ingress_content: str) -> Optional[str]:
    """
    인그레스 YAML 내용에서 URL을 추출합니다.

    Args:
        ingress_content: 인그레스 YAML 파일 내용

    Returns:
        추출된 URL (HTTPS 포함), 실패 시 None
    """
    try:
        # YAML 파싱
        ingress_data = yaml.safe_load(ingress_content)

        # spec.rules[0].host에서 호스트 추출
        if ingress_data and 'spec' in ingress_data:
            spec = ingress_data['spec']

            # rules에서 host 추출
            if 'rules' in spec and len(spec['rules']) > 0:
                host = spec['rules'][0].get('host')
                if host:
                    url = f"https://{host}"
                    logger.info(f"Extracted URL from ingress: {url}")
                    return url

            # 또는 tls.hosts에서 추출
            if 'tls' in spec and len(spec['tls']) > 0:
                tls_hosts = spec['tls'][0].get('hosts', [])
                if len(tls_hosts) > 0:
                    host = tls_hosts[0]
                    url = f"https://{host}"
                    logger.info(f"Extracted URL from ingress TLS: {url}")
                    return url

        logger.warning("Could not extract URL from ingress YAML")
        return None

    except yaml.YAMLError as e:
        logger.error(f"Failed to parse ingress YAML: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error extracting URL from ingress: {e}")
        return None


def extract_url_from_ingress_file(ingress_file_path: Path) -> Optional[str]:
    """
    인그레스 YAML 파일에서 URL을 추출합니다.

    Args:
        ingress_file_path: 인그레스 YAML 파일 경로

    Returns:
        추출된 URL (HTTPS 포함), 실패 시 None
    """
    try:
        with open(ingress_file_path, 'r', encoding='utf-8') as f:
            ingress_content = f.read()
        return extract_url_from_ingress_yaml(ingress_content)
    except FileNotFoundError:
        logger.error(f"Ingress file not found: {ingress_file_path}")
        return None
    except Exception as e:
        logger.error(f"Failed to read ingress file {ingress_file_path}: {e}")
        return None


def upsert_deployment_url(
    db: Session,
    user_id: str,
    github_owner: str,
    github_repo: str,
    url: str,
    is_user_modified: bool = False
) -> DeploymentUrl:
    """
    배포 URL을 저장하거나 업데이트합니다.

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        github_owner: GitHub 저장소 소유자
        github_repo: GitHub 저장소 이름
        url: 배포 URL
        is_user_modified: 사용자가 직접 수정했는지 여부

    Returns:
        저장/업데이트된 DeploymentUrl 객체
    """
    try:
        # 기존 레코드 조회
        existing = db.query(DeploymentUrl).filter(
            DeploymentUrl.user_id == user_id,
            DeploymentUrl.github_owner == github_owner,
            DeploymentUrl.github_repo == github_repo
        ).first()

        if existing:
            # 기존 레코드 업데이트
            existing.url = url
            existing.is_user_modified = is_user_modified
            existing.updated_at = datetime.now(timezone.utc)

            logger.info(
                f"Updated deployment URL for {github_owner}/{github_repo}: {url}"
            )
        else:
            # 새 레코드 생성
            existing = DeploymentUrl(
                user_id=user_id,
                github_owner=github_owner,
                github_repo=github_repo,
                url=url,
                is_user_modified=is_user_modified
            )
            db.add(existing)

            logger.info(
                f"Created deployment URL for {github_owner}/{github_repo}: {url}"
            )

        db.commit()
        db.refresh(existing)

        return existing

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to upsert deployment URL: {e}")
        raise


def get_deployment_url(
    db: Session,
    user_id: str,
    github_owner: str,
    github_repo: str
) -> Optional[DeploymentUrl]:
    """
    저장된 배포 URL을 조회합니다.

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        github_owner: GitHub 저장소 소유자
        github_repo: GitHub 저장소 이름

    Returns:
        DeploymentUrl 객체, 없으면 None
    """
    try:
        deployment_url = db.query(DeploymentUrl).filter(
            DeploymentUrl.user_id == user_id,
            DeploymentUrl.github_owner == github_owner,
            DeploymentUrl.github_repo == github_repo
        ).first()

        return deployment_url

    except Exception as e:
        logger.error(f"Failed to get deployment URL: {e}")
        return None


def get_all_deployment_urls_for_user(
    db: Session,
    user_id: str
) -> list[DeploymentUrl]:
    """
    사용자의 모든 배포 URL을 조회합니다.

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID

    Returns:
        DeploymentUrl 객체 리스트
    """
    try:
        deployment_urls = db.query(DeploymentUrl).filter(
            DeploymentUrl.user_id == user_id
        ).order_by(DeploymentUrl.updated_at.desc()).all()

        return deployment_urls

    except Exception as e:
        logger.error(f"Failed to get deployment URLs for user {user_id}: {e}")
        return []


def update_deployment_url_from_manifest(
    db: Session,
    user_id: str,
    github_owner: str,
    github_repo: str,
    sc_repo_name: str,
    domain: str = "klepaas.app"
) -> Optional[DeploymentUrl]:
    """
    매니페스트 정보를 기반으로 배포 URL을 생성하고 DB에 저장합니다.

    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        github_owner: GitHub 저장소 소유자
        github_repo: GitHub 저장소 이름
        sc_repo_name: SourceCommit 레포지토리 이름 (URL 생성에 사용)
        domain: 도메인 (기본값: "klepaas.app")

    Returns:
        저장된 DeploymentUrl 객체, 실패 시 None
    """
    try:
        # URL 생성
        url = generate_service_url(sc_repo_name, domain)

        # DB에 저장
        deployment_url = upsert_deployment_url(
            db=db,
            user_id=user_id,
            github_owner=github_owner,
            github_repo=github_repo,
            url=url,
            is_user_modified=False  # 자동 생성된 URL
        )

        return deployment_url

    except Exception as e:
        logger.error(f"Failed to update deployment URL from manifest: {e}")
        return None


async def change_deployment_url(
    owner: str,
    repo: str,
    new_domain: str,
    db: Session,
    user_id: str
) -> dict:
    """
    배포된 애플리케이션의 접속 주소(도메인)를 변경합니다.
    
    SourceCommit의 인그레스 매니페스트에서 도메인만 변경하고,
    빌드 없이 재배포합니다. (rollback.py 패턴 참고)
    
    Process:
    1. 프로젝트 통합 정보 조회
    2. SourceCommit 저장소 클론
    3. k8s/ingress.yaml에서 도메인 변경
    4. git commit & push
    5. 재배포 (빌드 없이)
    
    Args:
        owner: GitHub 저장소 소유자
        repo: GitHub 저장소 이름
        new_domain: 새로운 도메인 (예: "newapp.klepaas.app")
        db: 데이터베이스 세션
        user_id: 사용자 ID
        
    Returns:
        변경 결과 딕셔너리
    """
    import subprocess
    import shutil
    import uuid
    from pathlib import Path
    from urllib.parse import quote
    from fastapi import HTTPException
    
    logger.info(f"Starting URL change for {owner}/{repo} to domain: {new_domain}")
    
    # 1. 프로젝트 통합 정보 조회
    from ..models.user_project_integration import UserProjectIntegration
    
    integ = db.query(UserProjectIntegration).filter(
        UserProjectIntegration.user_id == user_id,
        UserProjectIntegration.github_owner == owner,
        UserProjectIntegration.github_repo == repo
    ).first()
    
    if not integ:
        logger.error(f"No project integration found for {owner}/{repo} (user_id: {user_id})")
        raise HTTPException(
            status_code=404,
            detail=f"프로젝트 통합 정보를 찾을 수 없습니다: {owner}/{repo}"
        )
    
    if not integ.sc_project_id:
        raise HTTPException(
            status_code=400,
            detail=f"SourceCommit project ID가 설정되지 않았습니다: {owner}/{repo}"
        )
    
    if not integ.deploy_project_id:
        raise HTTPException(
            status_code=400,
            detail=f"Deploy project ID가 설정되지 않았습니다: {owner}/{repo}"
        )
    
    # 2. SourceCommit 저장소 정보 가져오기
    from ..services.ncp_pipeline import get_sourcecommit_repo_public_url
    from ..core.config import settings
    
    sc_repo_name = integ.sc_repo_name or repo
    
    try:
        sc_url = get_sourcecommit_repo_public_url(integ.sc_project_id, sc_repo_name)
    except Exception:
        sc_url = f"https://devtools.ncloud.com/{integ.sc_project_id}/{sc_repo_name}.git"
    
    # SourceCommit 인증 정보 추가
    sc_username = settings.NCP_SOURCECOMMIT_USERNAME
    sc_password = settings.NCP_SOURCECOMMIT_PASSWORD
    
    if sc_username and sc_password:
        user_encoded = quote(sc_username, safe="")
        pwd_encoded = quote(sc_password, safe="")
        sc_url = sc_url.replace("https://", f"https://{user_encoded}:{pwd_encoded}@", 1)
    
    # 3. SourceCommit 저장소 클론 및 인그레스 매니페스트 수정
    work_dir = Path("/tmp") / f"url-change-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    sc_dir = work_dir / "sc_repo"
    
    try:
        logger.info(f"Cloning SourceCommit repository: {sc_repo_name}")
        
        # 저장소 클론
        subprocess.run(
            ["git", "clone", sc_url, str(sc_dir)],
            check=True,
            capture_output=True,
            text=True
        )
        
        # main 브랜치로 체크아웃
        subprocess.run(
            ["git", "-C", str(sc_dir), "checkout", "-B", "main"],
            check=True,
            capture_output=True,
            text=True
        )
        
        # 인그레스 매니페스트 경로
        ingress_path = sc_dir / "k8s" / "ingress.yaml"
        
        if not ingress_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"인그레스 매니페스트 파일을 찾을 수 없습니다: {ingress_path}"
            )
        
        # YAML 파싱 및 도메인 변경
        import yaml
        
        with open(ingress_path, 'r', encoding='utf-8') as f:
            ingress_data = yaml.safe_load(f)
        
        old_domain = None
        
        # spec.rules에서 도메인 변경
        if 'spec' in ingress_data and 'rules' in ingress_data['spec']:
            for rule in ingress_data['spec']['rules']:
                if 'host' in rule:
                    old_domain = rule['host']
                    rule['host'] = new_domain
                    logger.info(f"Changed domain in rules: {old_domain} -> {new_domain}")
        
        # spec.tls에서 도메인 변경
        if 'spec' in ingress_data and 'tls' in ingress_data['spec']:
            for tls in ingress_data['spec']['tls']:
                if 'hosts' in tls:
                    for i, host in enumerate(tls['hosts']):
                        old_domain = old_domain or host
                        tls['hosts'][i] = new_domain
                        logger.info(f"Changed domain in TLS: {host} -> {new_domain}")
        
        if not old_domain:
            raise HTTPException(
                status_code=400,
                detail="인그레스 매니페스트에서 도메인을 찾을 수 없습니다."
            )
        
        # 변경된 YAML 저장
        with open(ingress_path, 'w', encoding='utf-8') as f:
            yaml.dump(ingress_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        logger.info(f"Updated ingress manifest with new domain: {new_domain}")
        
        # Git commit and push
        subprocess.run(
            ["git", "-C", str(sc_dir), "config", "user.email", "bot@k-le-paas.local"],
            check=True,
            capture_output=True,
            text=True
        )
        subprocess.run(
            ["git", "-C", str(sc_dir), "config", "user.name", "K-Le-PaaS Bot"],
            check=True,
            capture_output=True,
            text=True
        )
        subprocess.run(
            ["git", "-C", str(sc_dir), "add", "k8s/ingress.yaml"],
            check=True,
            capture_output=True,
            text=True
        )
        
        commit_msg = f"chore: update ingress domain to {new_domain}"
        subprocess.run(
            ["git", "-C", str(sc_dir), "commit", "-m", commit_msg],
            check=True,
            capture_output=True,
            text=True
        )
        
        # Pull and push
        subprocess.run(
            ["git", "-C", str(sc_dir), "pull", "origin", "main", "--rebase"],
            check=False,  # Pull 실패해도 계속 진행
            capture_output=True,
            text=True
        )
        
        subprocess.run(
            ["git", "-C", str(sc_dir), "push", "origin", "main"],
            check=True,
            capture_output=True,
            text=True
        )
        
        logger.info("Successfully pushed ingress changes to SourceCommit")
        
        # 데이터베이스 커밋 (롤백 패턴 참고)
        db.commit()
        
        # 4. 재배포 (빌드 없이)
        from .ncp_pipeline import run_sourcedeploy
        from ..models.deployment_history import DeploymentHistory
        
        # 최근 배포 기록에서 커밋 SHA 가져오기
        last_deployment = db.query(DeploymentHistory).filter(
            DeploymentHistory.github_owner == owner,
            DeploymentHistory.github_repo == repo,
            DeploymentHistory.status == "success"
        ).order_by(DeploymentHistory.deployed_at.desc()).first()
        
        if not last_deployment:
            logger.warning("No previous deployment found, using 'latest' tag")
            tag = "latest"
        else:
            tag = last_deployment.github_commit_sha or "latest"
        
        logger.info(f"Redeploying with tag: {tag}")
        
        # 재배포 실행
        deploy_result = await run_sourcedeploy(
            deploy_project_id=integ.deploy_project_id,
            stage_name="production",
            scenario_name="deploy-app",
            sc_project_id=integ.sc_project_id,
            db=db,
            user_id=user_id,
            owner=owner,
            repo=repo,
            tag=tag,
            is_rollback=False  # URL 변경은 롤백이 아님
        )
        
        # DB에 새 URL 저장
        new_url = f"https://{new_domain}"
        upsert_deployment_url(
            db=db,
            user_id=user_id,
            github_owner=owner,
            github_repo=repo,
            url=new_url,
            is_user_modified=True  # 사용자가 직접 변경
        )
        
        logger.info(f"URL change completed for {owner}/{repo}: {old_domain} -> {new_domain}")
        
        return {
            "status": "success",
            "action": "change_url",
            "owner": owner,
            "repo": repo,
            "old_domain": old_domain,
            "new_domain": new_domain,
            "new_url": new_url,
            "deploy_result": deploy_result,
            "message": f"도메인이 {old_domain}에서 {new_domain}으로 변경되었습니다."
        }
        
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr if hasattr(e, 'stderr') else str(e)
        logger.error(f"Git error during URL change: {error_detail}")
        raise HTTPException(
            status_code=400,
            detail=f"Git 작업 중 오류 발생: {error_detail}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during URL change: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"URL 변경 중 오류 발생: {str(e)}"
        )
    finally:
        # 임시 디렉토리 정리
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info(f"Cleaned up work directory: {work_dir}")
        except Exception:
            pass


def validate_domain_format(domain_input: str) -> dict:
    """
    도메인 형식 검증
    
    Args:
        domain_input: 사용자 입력 (예: "myapp", "my-service", "https://myapp.klepaas.app")
    
    Returns:
        {
            "valid": bool,
            "subdomain": str,  # 추출된 서브도메인 (예: "myapp")
            "full_domain": str,  # 전체 도메인 (예: "myapp.klepaas.app")
            "error": str  # 검증 실패 시 에러 메시지
        }
    """
    import re
    
    # URL에서 서브도메인 추출 (https://, http:// 제거)
    subdomain = domain_input.strip()
    subdomain = re.sub(r'^https?://', '', subdomain)
    subdomain = re.sub(r'\.klepaas\.app$', '', subdomain)
    subdomain = subdomain.lower()
    
    # 도메인 형식 검증 규칙
    # 1. 영문 소문자, 숫자, 하이픈만 허용
    # 2. 하이픈으로 시작하거나 끝날 수 없음
    # 3. 길이: 3-63자
    
    if not subdomain:
        return {
            "valid": False,
            "subdomain": "",
            "full_domain": "",
            "error": "도메인을 입력해주세요."
        }
    
    if len(subdomain) < 3:
        return {
            "valid": False,
            "subdomain": subdomain,
            "full_domain": f"{subdomain}.klepaas.app",
            "error": "도메인은 최소 3자 이상이어야 합니다."
        }
    
    if len(subdomain) > 63:
        return {
            "valid": False,
            "subdomain": subdomain,
            "full_domain": f"{subdomain}.klepaas.app",
            "error": "도메인은 최대 63자까지 허용됩니다."
        }
    
    # 영문 소문자, 숫자, 하이픈만 허용
    if not re.match(r'^[a-z0-9-]+$', subdomain):
        return {
            "valid": False,
            "subdomain": subdomain,
            "full_domain": f"{subdomain}.klepaas.app",
            "error": "도메인은 영문 소문자, 숫자, 하이픈(-)만 사용할 수 있습니다."
        }
    
    # 하이픈으로 시작하거나 끝날 수 없음
    if subdomain.startswith('-') or subdomain.endswith('-'):
        return {
            "valid": False,
            "subdomain": subdomain,
            "full_domain": f"{subdomain}.klepaas.app",
            "error": "도메인은 하이픈(-)으로 시작하거나 끝날 수 없습니다."
        }
    
    # 연속된 하이픈 금지
    if '--' in subdomain:
        return {
            "valid": False,
            "subdomain": subdomain,
            "full_domain": f"{subdomain}.klepaas.app",
            "error": "도메인에 연속된 하이픈(--)을 사용할 수 없습니다."
        }
    
    full_domain = f"{subdomain}.klepaas.app"
    
    return {
        "valid": True,
        "subdomain": subdomain,
        "full_domain": full_domain,
        "error": ""
    }


def check_domain_availability(
    db: Session,
    full_domain: str,
    exclude_user_id: Optional[str] = None,
    exclude_owner: Optional[str] = None,
    exclude_repo: Optional[str] = None
) -> dict:
    """
    도메인 중복 체크 (전체 사용자 대상)
    
    Args:
        db: 데이터베이스 세션
        full_domain: 체크할 전체 도메인 (예: "myapp.klepaas.app")
        exclude_user_id: 제외할 사용자 ID (본인 서비스는 제외)
        exclude_owner: 제외할 GitHub owner
        exclude_repo: 제외할 GitHub repo
    
    Returns:
        {
            "available": bool,
            "conflict": Optional[dict]  # 충돌하는 배포 정보
        }
    """
    try:
        full_url = f"https://{full_domain}"
        
        # 중복 도메인 조회
        query = db.query(DeploymentUrl).filter(
            DeploymentUrl.url == full_url
        )
        
        # 본인 서비스는 제외
        if exclude_user_id and exclude_owner and exclude_repo:
            query = query.filter(
                ~(
                    (DeploymentUrl.user_id == exclude_user_id) &
                    (DeploymentUrl.github_owner == exclude_owner) &
                    (DeploymentUrl.github_repo == exclude_repo)
                )
            )
        
        existing = query.first()
        
        if existing:
            return {
                "available": False,
                "conflict": {
                    "user_id": existing.user_id,
                    "github_owner": existing.github_owner,
                    "github_repo": existing.github_repo,
                    "url": existing.url
                }
            }
        
        return {
            "available": True,
            "conflict": None
        }
    
    except Exception as e:
        logger.error(f"Failed to check domain availability: {e}")
        return {
            "available": False,
            "conflict": {"error": str(e)}
        }
