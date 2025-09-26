import base64
import json
from typing import Optional
import logging

import httpx

from ..core.config import get_settings
from .github_app import github_app_auth


logger = logging.getLogger(__name__)


async def update_values_tag(*, owner: str, repo: str, tag: str) -> None:
    """Update image.tag in deployment-config values file to provided tag.

    Assumes a single values file per service: values/{repo}-values.yaml
    Uses a GitHub token from env KLEPAAS_DEPLOYMENT_CONFIG_TOKEN with repo write access.
    """
    settings = get_settings()
    # Prefer GitHub App installation token if configured; fallback to static PAT
    token: str | None = None
    installation_id = settings.deployment_config_installation_id
    if installation_id:
        try:
            token = await github_app_auth.get_installation_token(installation_id=installation_id, force_refresh=True)
        except Exception:
            token = None
    if not token:
        # Prefer explicit settings fields, fallback to model_extra for legacy
        token = getattr(settings, "deployment_config_token", None) or settings.model_extra.get("deployment_config_token") or None
    # Resolve deployment-config repository
    deploy_repo = getattr(settings, "deployment_config_repo", None) or settings.model_extra.get("deployment_config_repo") or "K-Le-PaaS/deployment-config"

    if not token:
        raise RuntimeError("deployment-config token not configured")

    # Prefer charts/common-chart/values; fallback to values/ for legacy layouts
    primary_path = f"charts/common-chart/values/{repo}-values.yaml"
    legacy_path = f"values/{repo}-values.yaml"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        get_url = f"https://api.github.com/repos/{deploy_repo}/contents/{primary_path}"
        r = await client.get(get_url, headers=headers)
        if r.status_code == 200:
            info = r.json()
            content_b64 = info.get("content", "")
            sha = info.get("sha")
            content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            logger.info(f"Original content before regex: {repr(content)}")
            
            # Replace tag line while preserving indentation
            import re
            pattern = r"(?m)^(\s*)tag:\s*\"?.*\"?\s*$"
            replacement = rf'\1tag: "{tag}"'
            logger.info(f"Regex pattern: {pattern}")
            logger.info(f"Replacement: {replacement}")
            
            new_content = re.sub(pattern, replacement, content)
            logger.info(f"New content after regex: {repr(new_content)}")
            
            if new_content == content:
                logger.info("No changes detected, returning early")
                return
            payload = {
                "message": f"chore({repo}): set image tag {tag}",
                "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                "sha": sha,
                "branch": "main",
            }
            pr = await client.put(get_url, headers=headers, json=payload)
            pr.raise_for_status()
            return
        elif r.status_code == 404:
            # Try legacy location if primary not found
            get_url_legacy = f"https://api.github.com/repos/{deploy_repo}/contents/{legacy_path}"
            rl = await client.get(get_url_legacy, headers=headers)
            if rl.status_code == 200:
                info = rl.json()
                content_b64 = info.get("content", "")
                sha = info.get("sha")
                content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
                logger.info(f"Legacy path - Original content: {repr(content)}")
                import re
                pattern = r"(?m)^(\s*)tag:\s*\"?.*\"?\s*$"
                replacement = rf'\1tag: "{tag}"'
                logger.info(f"Legacy path - Pattern: {pattern}, Replacement: {replacement}")
                new_content = re.sub(pattern, replacement, content)
                logger.info(f"Legacy path - New content: {repr(new_content)}")
                if new_content != content:
                    payload = {
                        "message": f"chore({repo}): set image tag {tag}",
                        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                        "sha": sha,
                        "branch": "main",
                    }
                    upl = await client.put(get_url_legacy, headers=headers, json=payload)
                    upl.raise_for_status()
                return
            # Create scaffold file content
            service = repo
            scaffold = (
                f"name: {service}\n"
                f"replicaCount: 1\n"
                f"image:\n"
                f"  repository: codingpenguinyoon1081/{service}  # TODO: 실제 레지스트리로 교체\n"
                f"  tag: \"{tag}\"\n"
                f"service:\n"
                f"  type: NodePort  # TODO: 추후 설정으로 대체\n"
                f"  port: 80        # TODO: 추후 설정으로 대체\n"
                f"  nodePort: 30080 # TODO: 추후 설정으로 대체\n"
            )
            logger.info(f"Creating scaffold YAML for {service}:{tag}", extra={"scaffold": scaffold})
            payload = {
                "message": f"chore({repo}): add values file with tag {tag}",
                "content": base64.b64encode(scaffold.encode("utf-8")).decode("ascii"),
                "branch": "main",
            }
            pr = await client.put(get_url, headers=headers, json=payload)
            pr.raise_for_status()
            return
        else:
            # Log useful diagnostics before raising
            try:
                body = r.text
            except Exception:
                body = "<unable to read body>"
            logger.error(
                "deployment_config_update_failed",
                extra={
                    "status": r.status_code,
                    "url": get_url,
                    "body": body,
                    "deploy_repo": deploy_repo,
                    "owner": owner,
                    "repo": repo,
                },
            )
            r.raise_for_status()


