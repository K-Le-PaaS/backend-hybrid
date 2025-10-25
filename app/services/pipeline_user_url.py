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
