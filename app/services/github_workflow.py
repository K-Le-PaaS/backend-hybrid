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
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        run: |
          if [ -f package-lock.json ]; then npm ci; else npm i; fi
      - name: Lint
        run: |
          npm run lint --if-present
      - name: Test
        run: |
          npm test --if-present -- --ci --reporters=default --reporters=jest-junit
""".strip()


async def create_or_update_workflow(
    owner: str,
    repo: str,
    installation_id: str,
    path: str = ".github/workflows/ci.yml",
    yaml_content: Optional[str] = None,
    branch: Optional[str] = None,
    commit_message: str = "chore: add or update CI workflow",
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a workflow file via GitHub Contents API using installation token."""
    token = await github_app_auth.get_installation_token(installation_id)

    content_b64 = base64.b64encode((yaml_content or DEFAULT_CI_YAML).encode("utf-8")).decode("utf-8")

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    payload: Dict[str, Any] = {
        "message": commit_message,
        "content": content_b64,
    }
    if branch:
        payload["branch"] = branch
    if author_name or author_email:
        payload["committer"] = {
            "name": author_name or "K-Le-PaaS Bot",
            "email": author_email or "bot@k-le-paas.local",
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        # Check existing file to include sha for update
        get_resp = await client.get(url, headers=headers, params={"ref": branch} if branch else None)
        if get_resp.status_code == 200:
            body = get_resp.json()
            sha = body.get("sha")
            if sha:
                payload["sha"] = sha
        elif get_resp.status_code not in (404,):
            return {"status": "error", "message": f"Failed to read file: {get_resp.status_code}", "detail": get_resp.text}

        put_resp = await client.put(url, headers=headers, json=payload)
        if put_resp.status_code in (200, 201):
            data = put_resp.json()
            return {"status": "success", "path": path, "commit": data.get("commit", {}).get("sha")}
        else:
            return {"status": "error", "message": f"Failed to write file: {put_resp.status_code}", "detail": put_resp.text}


