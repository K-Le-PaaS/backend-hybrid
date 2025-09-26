from __future__ import annotations

import base64
from typing import Any, Dict, Optional

import httpx

from .github_app import github_app_auth


DEFAULT_CI_YAML = """
name: CI

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run build --if-present
      - run: npm test --if-present
""".strip()


async def create_or_update_workflow(
    *,
    owner: str,
    repo: str,
    installation_id: str,
    branch: str | None = None,
    path: str = ".github/workflows/ci.yml",
    yaml_content: str | None = None,
    commit_message: str = "chore: add or update CI workflow",
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create or update a workflow file in the target repository using a GitHub App installation token.

    If the default branch is protected, pass a feature branch via `branch` and open a PR separately.
    """
    # 1차 시도 토큰
    token = await github_app_auth.get_installation_token(installation_id)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "K-Le-PaaS/1.0",
    }

    content_to_write = (yaml_content or DEFAULT_CI_YAML).encode("utf-8")
    b64_content = base64.b64encode(content_to_write).decode("utf-8")

    file_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    async with httpx.AsyncClient(timeout=20) as client:
        # Check if file exists to retrieve SHA
        sha: Optional[str] = None
        get_params = {"ref": branch} if branch else None
        get_resp = await client.get(file_url, headers=headers, params=get_params)
        if get_resp.status_code == 200:
            data = get_resp.json()
            sha = data.get("sha")
        elif get_resp.status_code not in (404,):
            return {"status": "error", "step": "get", "code": get_resp.status_code, "body": get_resp.text}

        payload: Dict[str, Any] = {
            "message": commit_message,
            "content": b64_content,
        }
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch
        if author_name and author_email:
            payload["committer"] = {"name": author_name, "email": author_email}
            payload["author"] = {"name": author_name, "email": author_email}

        put_resp = await client.put(file_url, headers=headers, json=payload)
        if put_resp.status_code not in (200, 201):
            # 권한 변경 후 오래된 토큰으로 발생하는 403 케이스를 1회 자동 갱신 재시도
            if put_resp.status_code in (401, 403):
                token2 = await github_app_auth.get_installation_token(installation_id, force_refresh=True)
                headers["Authorization"] = f"Bearer {token2}"
                put_resp = await client.put(file_url, headers=headers, json=payload)
                if put_resp.status_code in (200, 201):
                    result = put_resp.json()
                    return {
                        "status": "success",
                        "action": "updated" if sha else "created",
                        "path": path,
                        "branch": branch,
                        "commit": (result.get("commit") or {}).get("sha"),
                        "content": (result.get("content") or {}).get("sha"),
                    }
            return {"status": "error", "step": "put", "code": put_resp.status_code, "body": put_resp.text}

        result = put_resp.json()
        return {
            "status": "success",
            "action": "updated" if sha else "created",
            "path": path,
            "branch": branch,
            "commit": (result.get("commit") or {}).get("sha"),
            "content": (result.get("content") or {}).get("sha"),
        }


