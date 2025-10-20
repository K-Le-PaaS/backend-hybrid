import subprocess
import shutil
import uuid
import time
import hmac
import hashlib
import base64
import os
from pathlib import Path
from fastapi import HTTPException
from urllib.parse import quote
import httpx
import asyncio

# Ensure ApiException symbol exists even if SDK missing
class ApiException(Exception):  # type: ignore
    pass

# NCP SDK 관련 클래스들을 임포트 (선택적)
NCP_AVAILABLE = True
# Optional APIs default to None (version-dependent availability)
SourceDeployApi = None  # type: ignore
SourcePipelineApi = None  # type: ignore
SourceBuildApi = None  # type: ignore
SourceCommitApi = None  # type: ignore
try:
    from ncloud_sdk.ncloud_client import NcloudClient  # type: ignore
    from ncloud_sdk.rest import ApiException  # type: ignore
except Exception:  # noqa: BLE001
    NCP_AVAILABLE = False
else:
    try:
        from ncloud_sdk.api.source_deploy_api import SourceDeployApi  # type: ignore
    except Exception:
        SourceDeployApi = None  # type: ignore
    try:
        from ncloud_sdk.api.source_pipeline_api import SourcePipelineApi  # type: ignore
    except Exception:
        SourcePipelineApi = None  # type: ignore
    try:
        from ncloud_sdk.api.source_build_api import SourceBuildApi  # type: ignore
    except Exception:
        SourceBuildApi = None  # type: ignore
    try:
        from ncloud_sdk.api.source_commit_api import SourceCommitApi  # type: ignore
    except Exception:
        SourceCommitApi = None  # type: ignore
    # Ensure ApiException symbol always exists for except clauses
    try:
        from ncloud_sdk.rest import ApiException  # type: ignore  # re-import to be safe
    except Exception:
        class ApiException(Exception):  # type: ignore
            pass

from ..core.config import get_settings
from ..services.user_project_integration import upsert_integration, get_integration
from ..models.deployment_history import get_kst_now
from sqlalchemy.orm import Session

# Initialize NCP client from settings (expects env vars configured)
settings = get_settings()
if NCP_AVAILABLE:
    ncloud_client = NcloudClient(
        access_key=getattr(settings, "ncp_access_key", None),
        secret_key=getattr(settings, "ncp_secret_key", None),
    )
    # Initialize SourceDeploy API if available
    if SourceDeployApi:
        sourcedeploy_api = SourceDeployApi(ncloud_client)
    else:
        sourcedeploy_api = None
else:
    ncloud_client = None
    sourcedeploy_api = None
def _dbg(tag: str, **kw: object) -> None:
    try:
        kv = " ".join([f"{k}={kw[k]}" for k in kw])
        print(f"[NCP-DEBUG][{tag}] {kv}")
    except Exception:
        pass


def _generate_ncr_image_name(owner: str, repo: str) -> str:
    """Generate NCR-compliant image name from owner and repo.

    NCR naming rules:
    - Use lower case

    Format: {owner}-{repo} with all hyphens replaced by underscores

    Examples:
        _generate_ncr_image_name("K-Le-PaaS", "test-01") -> "k-le-paas-test-01"
        _generate_ncr_image_name("myorg", "myrepo") -> "myorg-myrepo"
    """
    safe_owner = owner.lower()
    safe_repo = repo.lower()
    return f"{safe_owner}-{safe_repo}"


def get_sourcecommit_repo_public_url(project_id: str, repo_name: str) -> str | None:
    """Get the actual clone URL from SourceCommit API.

    This is critical for authentication to work properly.
    """
    try:
        # Use synchronous version of _call_ncp_rest_api
        import requests
        sc_base = getattr(settings, 'ncp_sourcecommit_endpoint', 'https://sourcecommit.apigw.ntruss.com')

        # Get headers with authentication
        headers = _get_ncp_api_headers('GET', f'/api/v1/repository/{repo_name}')

        response = requests.get(
            f"{sc_base}/api/v1/repository/{repo_name}",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get('result', {})

            # Get clone URLs
            clone_url_http = result.get('cloneUrlHttp') or result.get('clone_url_http')

            if clone_url_http:
                _dbg("SC-URL-RESOLVED", repo=repo_name, url=clone_url_http)
                return clone_url_http

        # Fallback to devtools pattern
        endpoint = getattr(settings, "ncp_sourcecommit_public_base", None) or "https://devtools.ncloud.com"
        fallback_url = f"{endpoint}/{project_id}/{repo_name}.git"
        _dbg("SC-URL-FALLBACK", repo=repo_name, url=fallback_url)
        return fallback_url

    except Exception as e:
        _dbg("SC-URL-ERROR", error=str(e)[:200])
        # Fallback
        endpoint = getattr(settings, "ncp_sourcecommit_public_base", None) or "https://devtools.ncloud.com"
        return f"{endpoint}/{project_id}/{repo_name}.git"

# --- NCP REST Signing helpers (Signature v2) ---
import asyncio
import hashlib as _hashlib
import hmac as _hmac
import time as _time

def _sign(method: str, path: str, timestamp: str, access_key: str, secret_key: str) -> str:
    message = f"{method} {path}\n{timestamp}\n{access_key}"
    signature = _hmac.new(bytes(secret_key, 'utf-8'), bytes(message, 'utf-8'), _hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def _get_ncp_api_headers(method: str, path: str) -> dict:
    ak = getattr(settings, 'ncp_access_key', None)
    sk = getattr(settings, 'ncp_secret_key', None)
    if not ak or not sk:
        raise HTTPException(status_code=500, detail='NCP access/secret key not configured')
    ts = str(int(_time.time() * 1000))
    sig = _sign(method, path, ts, ak, sk)
    return {
        'x-ncp-apigw-timestamp': ts,
        'x-ncp-iam-access-key': ak,
        'x-ncp-apigw-signature-v2': sig,
        'Content-Type': 'application/json',
        'x-ncp-region_code': getattr(settings, 'ncp_region', 'KR')
    }

async def _call_ncp_rest_api(method: str, base_url: str, path: str | list[str], json_body: dict | None = None, query_params: dict | None = None) -> dict:
    """Call NCP REST API. Accepts a single path or a list of candidate paths.
    Tries each candidate in order; returns the first successful JSON.
    """
    paths: list[str] = path if isinstance(path, list) else [path]
    last_status: int | None = None
    last_text: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in paths:
            url = base_url.rstrip('/') + p
            headers = _get_ncp_api_headers(method, p)
            if method.upper() == 'GET':
                resp = await client.request(method, url, headers=headers, params=query_params)
            else:
                resp = await client.request(method, url, headers=headers, json=json_body)
            _dbg("REST", method=method, url=url, code=resp.status_code)
            if resp.status_code < 400:
                return resp.json() if resp.text else {}
            # remember last error and continue to next candidate
            last_status = resp.status_code
            last_text = resp.text
            try:
                _dbg("REST-ERR", method=method, url=url, code=resp.status_code, text=(resp.text or "")[:500])
            except Exception:
                pass
    raise HTTPException(status_code=last_status or 500, detail=f"NCP REST error {last_status}: {last_text}")


async def update_sourcecommit_manifest(
    repo_name: str,
    image_url: str,
    branch: str = "main",
    manifest_path: str = "k8s/deployment.yaml",
    app_name: str | None = None,
    port: int = 8080,
    sc_project_id: str | None = None,

) -> dict:
    """
    Update SourceCommit repository's Kubernetes deployment manifest.

    Uses the full image URL (including tag) directly in the manifest.

    Args:
        repo_name: SourceCommit repository name
        image_url: Full container image URL with tag (e.g., "registry.com/owner/repo:v1.0.0")
        branch: Git branch to update (default: main)
        manifest_path: Path to deployment manifest (default: k8s/deployment.yaml)
        app_name: Application name for deployment (default: derived from repo_name)
        port: Container port (default: 8080)
        sc_project_id: SourceCommit project ID (not used with Git approach)

    Returns:
        Response indicating manifest was updated with specific image tag
    """
    import yaml

    # Derive app name from repo if not provided
    if not app_name:
        app_name = repo_name.lower()

    _dbg("SC-MANIFEST-UPDATE", repo=repo_name, image=image_url, app=app_name)

    # Generate manifest with full image URL (including tag)
    manifest_content = _generate_default_manifest(app_name, image_url, port)

    _dbg("SC-MANIFEST-DIRECT", repo=repo_name, image_url=image_url)

    return {
        "status": "manifest_ready",
        "repository": repo_name,
        "branch": branch,
        "manifest_path": manifest_path,
        "image_url": image_url,
        "manifest_content": manifest_content,
        "commit": {"note": f"Update manifest with image {image_url}"}
    }


def _generate_manifest_with_env_var(app_name: str, image_template: str, port: int) -> str:
    """Generate Kubernetes deployment manifest with environment variable for image tag."""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      containers:
      - name: {app_name}
        image: {image_template}
        ports:
        - containerPort: {port}
        env:
        - name: PORT
          value: "{port}"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
"""


def _generate_default_manifest(app_name: str, image_url: str, port: int) -> str:
    """Generate default Kubernetes deployment manifest."""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      imagePullSecrets:
      - name: ncp-cr
      containers:
      - name: {app_name}
        image: {image_url}
        ports:
        - containerPort: {port}
        env:
        - name: PORT
          value: "{port}"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
"""


def _generate_default_manifest(app_name: str, image_url: str, port: int) -> str:
    """Generate default Kubernetes deployment manifest."""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      imagePullSecrets:
      - name: ncp-cr
      containers:
      - name: {app_name}
        image: {image_url}
        ports:
        - containerPort: {port}
        env:
        - name: PORT
          value: "{port}"
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
"""

# --- NCR manifest verification (short backoff, bearer auth if required) ---
async def _verify_ncr_manifest_exists(image_with_tag: str) -> dict:
    try:
        if ":" not in image_with_tag:
            return {"exists": False, "code": None}
        registry_and_name, tag = image_with_tag.rsplit(":", 1)
        if "/" not in registry_and_name:
            return {"exists": False, "code": None}
        registry_host, name = registry_and_name.split("/", 1)
        url = f"https://{registry_host}/v2/{name}/manifests/{tag}"
        headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {"exists": True, "code": 200}
            if resp.status_code != 401:
                return {"exists": False, "code": resp.status_code}
            www = resp.headers.get("WWW-Authenticate") or ""
            if "Bearer" not in www:
                return {"exists": False, "code": resp.status_code}
            # parse realm/service/scope
            realm = None; service = None; scope = None
            try:
                parts = [p.strip() for p in www.split(" ", 1)[1].split(",")]
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        v = v.strip().strip('"')
                        if k.lower() == "realm": realm = v
                        elif k.lower() == "service": service = v
                        elif k.lower() == "scope": scope = v
            except Exception:
                pass
            if not scope:
                scope = f"repository:{name}:pull"
            if not realm:
                return {"exists": False, "code": 401}
            user = getattr(settings, "ncp_registry_username", None) or getattr(settings, "ncp_access_key", None)
            pwd = getattr(settings, "ncp_registry_password", None) or getattr(settings, "ncp_secret_key", None)
            params = {"scope": scope}
            if service:
                params["service"] = service
            tok = await client.get(realm, params=params, auth=(user or "", pwd or ""))
            if tok.status_code != 200:
                return {"exists": False, "code": 401}
            j = tok.json() if tok.text else {}
            token = j.get("token") or j.get("access_token")
            if not token:
                return {"exists": False, "code": 401}
            headers_auth = headers | {"Authorization": f"Bearer {token}"}
            resp2 = await client.get(url, headers=headers_auth)
            return {"exists": resp2.status_code == 200, "code": resp2.status_code}
    except Exception:
        return {"exists": False, "code": None}

# --- Resolve actual pushed image from build detail if available ---
async def _get_sourcebuild_container_image(base: str, build_project_id: str, build_id: str) -> str | None:
    paths = [
        f"/api/v1/project/{build_project_id}/build/{build_id}",
        f"/api/v1/project/{build_project_id}/history/{build_id}",
    ]
    for p in paths:
        try:
            data = await _call_ncp_rest_api('GET', base, p)
            result = data.get('result', {}) if isinstance(data, dict) else {}
            url = result.get('containerImageUrl') or result.get('image')
            if url:
                return str(url)
        except HTTPException:
            continue
        except Exception:
            continue
    # fallback: search in history list
    try:
        hist = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{build_project_id}/history")
        items = (
            (hist.get('result') or {}).get('history')
            or (hist.get('result') or {}).get('builds')
            or hist.get('history')
            or hist.get('builds')
            or []
        )
        for it in items:
            bid = it.get('buildId') or it.get('id')
            if str(bid) == str(build_id):
                url = it.get('containerImageUrl') or it.get('image')
                if url:
                    return str(url)
    except Exception:
        pass
    return None

# --- SourceCommit via REST ---
async def ensure_sourcecommit_repo(project_id: str, repo_name: str) -> dict:
    """Create SourceCommit repository if missing (REST), or return exists.
    Returns: {status: 'created'|'exists'|'error', id?: str, detail?: any}
    """
    base = getattr(settings, 'ncp_sourcecommit_endpoint', 'https://sourcecommit.apigw.ntruss.com')
    create_path = f"/api/v1/projects/{project_id}/repositories"
    body = {"name": repo_name}
    try:
        data = await _call_ncp_rest_api('POST', base, create_path, body)
        repo_id = None
        if isinstance(data, dict):
            result = data.get('result') or {}
            if isinstance(result, dict):
                repo_id = str(result.get('id') or result.get('repositoryId') or '') or None
        return {"status": "created", "id": repo_id}
    except HTTPException as e:
        msg = getattr(e, 'detail', '')
        # duplicate name → treat as exists
        if getattr(e, 'status_code', 0) == 400 and isinstance(msg, str) and ('310405' in msg or 'duplicat' in msg.lower()):
            return {"status": "exists"}
        # Some tenants return 404 when repo already present via devtools; try to HEAD public URL as best-effort
        if getattr(e, 'status_code', 0) == 404:
            return {"status": "exists"}
        return {"status": "error", "detail": msg}

# --- SourceBuild via REST ---
async def create_sourcebuild_project_rest(owner: str, repo: str, branch: str, image_repo: str, sc_project_id: str | None = None, sc_repo_name: str | None = None) -> str:
    base = getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com')
    # KR 고정
    path = "/api/v1/project"
    source_config: dict = {"branch": branch}
    if sc_project_id and sc_repo_name:
        source_config.update({"projectId": sc_project_id, "repository": sc_repo_name})
    else:
        # fallback: some tenants allow repository name only (may fail with 320610)
        source_config.update({"repository": repo})

    # Generate NCR-compliant image name: {owner}_{repo}
    # Example: K-Le-PaaS/test-01 -> k_le_paas_test_01
    ncr_image_name = _generate_ncr_image_name(owner, repo)

    # Derive registry project from image_repo
    # image_repo example: "klepaas-test.kr.ncr.ntruss.com/owner-repo"
    try:
        registry_host, _ = (image_repo or "").split("/", 1)
    except ValueError:
        registry_host = image_repo or ""
    registry_project = (registry_host or "").split(".")[0] or "klepaas-test"

    _dbg("SB-PROJECT-CREATE", owner=owner, repo=repo,
         image_name=ncr_image_name, registry=registry_project)

    # EXACT working configuration - matches the version that successfully built with Docker
    body = {
        "name": f"build-{owner}-{repo}",
        "source": {
            "type": "SourceCommit",
            "config": source_config
        },
        "env": {
            "docker": {"use": True, "id": 1},
            "compute": {"id": 1},
            "os": 1,
            "platform": {"type": "SourceBuild", "config": {"os": {"id": 1}, "runtime": {"id": 1, "version": {"id": 1}}}}
        },
        # Enable Docker build commands (matches "docker build 명령어를 사용하는 경우" checkbox)
        "cmd": {
            "pre": [],
            "build": [],
            "post": [],
            "dockerbuild": {
                "use": True,
                "dockerfile": "Dockerfile",
                "registry": registry_project,
                "image": ncr_image_name,
                "tag": "latest",
                "latest": False
            }
        },
        "cache": {
            "use": False
        },
        "builder": {"type": "Dockerfile", "config": {"path": "Dockerfile"}}
    }
    try:
        data = await _call_ncp_rest_api('POST', base, path, body)
        # guide: result.id
        result = data.get('result') if isinstance(data, dict) else None
        return str((result or {}).get('id') or data.get('id') or data.get('project_id'))
    except HTTPException as e:
        # duplicate name → try to reuse existing by lookup
        msg = getattr(e, 'detail', '')
        if getattr(e, 'status_code', 0) == 400 and isinstance(msg, str) and 'duplicat' in msg.lower():
            name = f"build-{owner}-{repo}"
            pid = await _find_sourcebuild_project_id_by_name(base, name)
            if pid:
                return pid
        # last resort: try lookup anyway before giving up
        try:
            name = f"build-{owner}-{repo}"
            pid = await _find_sourcebuild_project_id_by_name(base, name)
            if pid:
                return pid
        except Exception:
            pass
        # fallback: mark as exists-without-id so caller can proceed gracefully
        return "__EXISTS_NO_ID__"

def _extract_project_id(obj: dict) -> str | None:
    for k in ("id", "projectId", "project_id", "projectNo", "project_no"):
        v = obj.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return None

def _extract_project_name(obj: dict) -> str | None:
    for k in ("name", "projectName", "project_name"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip() != "":
            return v
    # nested project object
    prj = obj.get("project")
    if isinstance(prj, dict):
        return _extract_project_name(prj)
    return None

async def _find_sourcebuild_project_id_by_name(base: str, name: str) -> str | None:
    # Use only the working endpoint: GET /api/v1/project (no query params to avoid 401)
    try:
        data = await _call_ncp_rest_api('GET', base, ['/api/v1/project'], None)
        _dbg("SB-FIND-BY-NAME", target_name=name, response_keys=list(data.keys()) if isinstance(data, dict) else None)

        # Log full response structure for debugging
        if isinstance(data, dict):
            result = data.get('result')
            _dbg("SB-FIND-RESULT-TYPE", result_type=type(result).__name__, result_keys=list(result.keys()) if isinstance(result, dict) else None)

            # Try multiple possible structures
            items = []
            if isinstance(result, dict):
                items = result.get('project') or result.get('projectList') or result.get('projects') or result.get('items') or []
            elif isinstance(result, list):
                items = result

            _dbg("SB-FIND-ITEMS", count=len(items), names=[_extract_project_name(it) for it in items if isinstance(it, dict)])

            # If still no items, log the full result structure (first 500 chars)
            if len(items) == 0:
                import json
                _dbg("SB-FIND-EMPTY-RESULT", full_result=json.dumps(result, default=str)[:500] if result else None)

            for it in items:
                if not isinstance(it, dict):
                    continue
                it_name = _extract_project_name(it)
                if it_name and it_name.strip().lower() == name.strip().lower():
                    pid = _extract_project_id(it) or _extract_project_id(it.get('project', {}) if isinstance(it.get('project'), dict) else {})
                    if pid:
                        _dbg("SB-FIND-MATCH", name=it_name, project_id=pid)
                        return pid
            _dbg("SB-FIND-NO-MATCH", target=name, available=[_extract_project_name(it) for it in items if isinstance(it, dict)])
    except HTTPException as e:
        _dbg("SB-FIND-ERROR", error=str(e)[:200])
        return None
    return None

async def run_sourcebuild_project_rest(project_id: str) -> dict:
    base = getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com')
    # KR 고정
    path = f"/api/v1/project/{project_id}/build"
    data = await _call_ncp_rest_api('POST', base, path, {})
    result = data.get('result') if isinstance(data, dict) else None
    return {"status": "started", "projectId": project_id, "buildId": (result or {}).get('buildId') or data.get('buildId')}

async def ensure_sourcebuild_project(
    *, owner: str, repo: str, branch: str = "main", sc_project_id: str | None,
    sc_repo_name: str | None, db: Session | None = None, user_id: str | None = None
) -> str:
    """Ensure a SourceBuild project exists and return its numeric id.
    - DB-first → lookup by name → create → re-lookup on exists-without-id
    - Persist build_project_id into integration when db/user provided
    """
    base = getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com')
    name = f"build-{owner}-{repo}"
    # DB first
    if db is not None and user_id is not None:
        try:
            integ_existing = get_integration(db, user_id=user_id, owner=owner, repo=repo)
            if integ_existing and getattr(integ_existing, 'build_project_id', None):
                return str(getattr(integ_existing, 'build_project_id'))
        except Exception:
            pass
    # Find by name
    pid = await _find_sourcebuild_project_id_by_name(base, name)
    if not pid:
        # Create
        registry = getattr(settings, "ncp_container_registry_url", None) or ""
        image_repo, _ = _compose_image_repo(registry, owner, repo, build_project_id=None)
        pid = await create_sourcebuild_project_rest(
            owner=owner,
            repo=repo,
            branch=branch,
            image_repo=image_repo,
            sc_project_id=sc_project_id,
            sc_repo_name=sc_repo_name,
        )
        if str(pid).strip() == "__EXISTS_NO_ID__":
            pid = await _find_sourcebuild_project_id_by_name(base, name)
    if not pid:
        raise HTTPException(status_code=500, detail="failed to ensure SourceBuild project id")
    # persist
    if db is not None and user_id is not None:
        try:
            upsert_integration(db, user_id=user_id, owner=owner, repo=repo, build_project_id=str(pid))
        except Exception:
            pass
    return str(pid)

# --- SourceDeploy via SDK (Preferred) ---
async def create_sourcedeploy_project_sdk(name: str, manifest_text: str, nks_cluster_id: str | None) -> str:
    """Create SourceDeploy project using NCP SDK with full stage/target/scenario setup.

    This uses the SDK which handles the internal API schema correctly.
    """
    if not sourcedeploy_api:
        _dbg("SD-SDK-UNAVAILABLE", fallback="REST")
        return await create_sourcedeploy_project_rest(name, manifest_text, nks_cluster_id)

    _dbg("SD-SDK-CREATE", name=name, has_cluster=bool(nks_cluster_id))

    try:
        # Import SDK models
        from ncloud_sdk.models import (  # type: ignore
            SourceDeployProjectRequest,
            SourceDeployStageRequest,
            SourceDeployScenarioRequest,
            SourceDeployTargetRequest,
            SourceDeployManifestRequest,
        )

        # 1. Create project first (no stages)
        project_req = SourceDeployProjectRequest(name=name)
        project_resp = sourcedeploy_api.create_project(project_req)
        project_id = str(project_resp.id if hasattr(project_resp, 'id') else project_resp.project_id)
        _dbg("SD-SDK-PROJECT-CREATED", id=project_id)

        # Wait for project propagation
        await asyncio.sleep(3)

        # 2. Create stage
        stage_req = SourceDeployStageRequest(
            project_id=int(project_id),
            name="production",
            description="Production deployment stage"
        )
        stage_resp = sourcedeploy_api.create_stage(stage_req)
        stage_id = str(stage_resp.id if hasattr(stage_resp, 'id') else stage_resp.stage_id)
        _dbg("SD-SDK-STAGE-CREATED", id=stage_id)

        # Wait for stage propagation
        await asyncio.sleep(3)

        # 3. Set target (NKS cluster)
        if nks_cluster_id:
            target_req = SourceDeployTargetRequest(
                project_id=int(project_id),
                stage_id=int(stage_id),
                type="ID",
                id=nks_cluster_id
            )
            try:
                sourcedeploy_api.set_stage_target(target_req)
                _dbg("SD-SDK-TARGET-SET", stage_id=stage_id, cluster_id=nks_cluster_id)
            except ApiException as e:
                _dbg("SD-SDK-TARGET-ERR", code=e.status, msg=str(e)[:200])

        # Wait for target propagation
        await asyncio.sleep(3)

        # 4. Create scenario with inline manifest
        # Manifest should use a tag placeholder (${TAG}) so deploy can switch versions without new commits
        manifest_req = SourceDeployManifestRequest(
            type="Inline",
            files=[{
                "type": "TEXT",
                "path": "deployment.yaml",
                "content": manifest_text
            }]
        )

        scenario_req = SourceDeployScenarioRequest(
            project_id=int(project_id),
            stage_id=int(stage_id),
            name="deploy-app",
            description="Auto-generated deployment scenario",
            type="KUBERNETES",
            manifest=manifest_req
        )

        try:
            scenario_resp = sourcedeploy_api.create_scenario(scenario_req)
            scenario_id = str(scenario_resp.id if hasattr(scenario_resp, 'id') else scenario_resp.scenario_id)
            _dbg("SD-SDK-SCENARIO-CREATED", id=scenario_id)
        except ApiException as e:
            _dbg("SD-SDK-SCENARIO-ERR", code=e.status, msg=str(e)[:500])
            # Scenario creation failed but project/stage are created
            _dbg("SD-SDK-SCENARIO-MANUAL", msg="Create scenario manually in console")

        return project_id

    except ApiException as e:
        _dbg("SD-SDK-ERR", code=e.status, msg=str(e)[:500])
        # Fallback to REST
        _dbg("SD-SDK-FALLBACK", method="REST")
        return await create_sourcedeploy_project_rest(name, manifest_text, nks_cluster_id)
    except Exception as e:
        _dbg("SD-SDK-UNEXPECTED-ERR", error=str(e)[:500])
        # Fallback to REST
        return await create_sourcedeploy_project_rest(name, manifest_text, nks_cluster_id)

# --- SourceDeploy via REST (KR default) ---
async def create_sourcedeploy_project_rest(name: str, manifest_text: str, nks_cluster_id: str | None) -> str:
    base = getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com')
    path = "/api/v1/project"

    # IMPORTANT: Deploy 프로젝트 생성 시 stages/scenarios를 포함하지 않고
    # 프로젝트만 먼저 생성합니다. Stage와 Scenario는 별도로 생성해야 합니다.
    #
    # 이유: 프로젝트 생성 시 stages/scenarios를 포함하면 200 OK를 반환하지만
    # 실제로는 프로젝트가 제대로 생성되지 않아 GET /project/{id}가 404를 반환합니다.
    body = {"name": name}

    _dbg("SD-PROJECT-CREATE", name=name, body=body)
    try:
        data = await _call_ncp_rest_api('POST', base, path, body)
        result = data.get('result') if isinstance(data, dict) else None
        project_id = str((result or {}).get('id') or data.get('id'))
        _dbg("SD-PROJECT-CREATED", id=project_id, response_keys=list(data.keys()) if isinstance(data, dict) else [])

        # 프로젝트 생성 직후 propagation 대기
        await asyncio.sleep(3)

        # 프로젝트가 실제로 생성되었는지 확인
        try:
            detail = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{project_id}")
            _dbg("SD-PROJECT-VERIFIED", id=project_id, status="exists")
        except HTTPException as verify_err:
            _dbg("SD-PROJECT-VERIFY-FAILED", id=project_id, code=getattr(verify_err, 'status_code', None))
            # 404면 프로젝트 목록에서 찾기 시도
            if getattr(verify_err, 'status_code', 0) == 404:
                found_id = await _find_sourcedeploy_project_id_by_name(base, name)
                if found_id:
                    project_id = found_id
                    _dbg("SD-PROJECT-FOUND-BY-NAME", id=project_id)
                else:
                    raise HTTPException(status_code=500, detail=f"Project created but cannot be found (id={project_id})")

        return project_id
    except HTTPException as e:
        msg = getattr(e, 'detail', '')
        # duplicate name → try to find and reuse
        if getattr(e, 'status_code', 0) == 400 and isinstance(msg, str) and 'duplicat' in msg.lower():
            pid = await _find_sourcedeploy_project_id_by_name(base, name)
            if pid:
                return pid
        raise

async def _find_sourcedeploy_project_id_by_name(base: str, name: str) -> str | None:
    try:
        data = await _call_ncp_rest_api('GET', base, '/api/v1/project', None)
        items = []
        if isinstance(data, dict):
            result = data.get('result') or {}
            if isinstance(result, dict):
                items = result.get('projectList') or result.get('projects') or []
        for it in items:
            if isinstance(it, dict) and it.get('name') == name and it.get('id'):
                return str(it['id'])
    except HTTPException:
        return None
    return None

# --- SourcePipeline via REST (KR default) ---
async def create_sourcepipeline_rest(name: str, build_project_id: str, deploy_project_id: str) -> str:
    base = getattr(settings, 'ncp_sourcepipeline_endpoint', 'https://vpcsourcepipeline.apigw.ntruss.com')
    # According to guide, pipeline create path is /api/v1/project and schema uses tasks
    path = "/api/v1/project"
    # Validate/normalize project IDs
    bpid: int | None = None
    dpid: int | None = None
    try:
        bpid = int(str(build_project_id))
    except Exception:
        bpid = None
    try:
        dpid = int(str(deploy_project_id))
    except Exception:
        dpid = None
    if bpid is None or dpid is None:
        # IDs must be numeric; fail fast with actionable message
        raise HTTPException(status_code=400, detail=f"Invalid build/deploy project id (build={build_project_id}, deploy={deploy_project_id}). Ensure both IDs exist and are numeric.")
    # Try to resolve stage/scenario IDs for SourceDeploy
    stage_id: int | None = None
    scenario_id: int | None = None
    try:
        sd_base = getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com')
        sd_detail = await _call_ncp_rest_api('GET', sd_base, [f"/api/v1/project/{deploy_project_id}"])
        result = sd_detail.get('result', {}) if isinstance(sd_detail, dict) else {}
        stages = result.get('stages') or result.get('stageList') or []
        for st in stages:
            if st.get('name') == 'production' or stage_id is None:
                stage_id = st.get('id') or st.get('stageId')
                scenarios = st.get('scenarios') or st.get('scenarioList') or []
                for sc in scenarios:
                    if sc.get('name') == 'deploy-app' or scenario_id is None:
                        scenario_id = sc.get('id') or sc.get('scenarioId')
                        break
                if stage_id is not None and scenario_id is not None:
                    break
    except Exception:
        # best-effort; fall back to names if IDs cannot be resolved
        stage_id = None
        scenario_id = None
    body = {
        "name": name,
        "tasks": [
            {
                "name": "build",
                "type": "SourceBuild",
                "config": {"projectId": bpid},
                "linkedTasks": []
            },
            {
                "name": "deploy",
                "type": "SourceDeploy",
                "config": ({
                    "projectId": dpid,
                    "stageId": stage_id,
                    "scenarioId": scenario_id
                } if stage_id is not None and scenario_id is not None else {
                    "projectId": dpid,
                    "stageName": "production",
                    "scenarioName": "deploy-app"
                }),
                "linkedTasks": ["build"]
            }
        ],
        "trigger": None
    }
    data = await _call_ncp_rest_api('POST', base, path, body)
    result = data.get('result') if isinstance(data, dict) else None
    return str((result or {}).get('id') or data.get('id'))


async def ensure_sourcedeploy_project(
    *, owner: str, repo: str, manifest_text: str, nks_cluster_id: str | None, db: Session | None = None, user_id: str | None = None
) -> str:
    """Ensure a SourceDeploy project exists and return its numeric id.

    Resolution order:
    - DB first
    - find by name (deploy-{owner}-{repo})
    - create minimal project if missing, then re-lookup
    - persist to DB if provided
    """
    base = getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com')
    name = f"deploy-{owner}-{repo}"
    # DB first
    if db is not None and user_id is not None:
        try:
            integ_existing = get_integration(db, user_id=user_id, owner=owner, repo=repo)
            if integ_existing and getattr(integ_existing, 'deploy_project_id', None):
                return str(getattr(integ_existing, 'deploy_project_id'))
        except Exception:
            pass
    # Find by name
    pid = await _find_sourcedeploy_project_id_by_name(base, name)
    if not pid:
        # Create minimal project with inline deployment manifest and NKS target if provided
        # Try SDK first (preferred), falls back to REST automatically
        pid = await create_sourcedeploy_project_sdk(name, manifest_text, nks_cluster_id)
        # Re-lookup to ensure numeric id shape
        pid = pid or await _find_sourcedeploy_project_id_by_name(base, name)
    if not pid:
        raise HTTPException(status_code=500, detail="failed to ensure SourceDeploy project id")
    # persist
    if db is not None and user_id is not None:
        try:
            upsert_integration(db, user_id=user_id, owner=owner, repo=repo, deploy_project_id=str(pid))
        except Exception:
            pass
    return str(pid)

def clone_repository(repository_url: str, target_dir: str, branch: str = "main", access_token: str | None = None):
    print(f"cloning repository {repository_url} to {target_dir} on branch {branch}")
    try:
        auth_url = repository_url
        # inject token for private repos if provided (https scheme only)
        if access_token and repository_url.startswith("https://"):
            # GitHub App installation token starts with 'ghs_' → use x-access-token:{token}
            if access_token.startswith("ghs_"):
                auth_url = repository_url.replace("https://", f"https://x-access-token:{access_token}@", 1)
            else:
                # Personal token/PAT fallback
                auth_url = repository_url.replace("https://", f"https://{access_token}:x-oauth-basic@", 1)
        subprocess.run(
            ["git", "clone", "--branch", branch, auth_url, target_dir],
            check=True,
            capture_output=True,
            text=True
        )
        print("repository cloned successfully")
    except subprocess.CalledProcessError as e:
        print(f"error cloning repository {repository_url} to {target_dir} on branch {branch}: {e}")
        raise HTTPException(status_code=400, detail=f"error cloning repository {repository_url} to {target_dir} on branch {branch}: {e.stderr}")

def build_and_push_image_with_buildpack(source_dir: str, image_name: str, tag: str) -> None:
    print(f"building and pushing image {image_name} with tag {tag} from {source_dir}")
    # login to NCP registry if configured
    registry = getattr(settings, "ncp_container_registry_url", None)
    registry_user = (
        getattr(settings, "ncp_registry_username", None)
        or getattr(settings, "ncp_access_key", None)
    )
    registry_pass = (
        getattr(settings, "ncp_registry_password", None)
        or getattr(settings, "ncp_secret_key", None)
    )
    if registry and registry_user and registry_pass:
        try:
            subprocess.run(
                ["docker", "login", registry, "-u", registry_user, "-p", registry_pass],
                check=True,
                capture_output=True,
                text=True,
            )
            print("docker login succeeded")
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"docker login failed: {e.stderr}")
    command = [
        "pack", "build", image_name,
        "--builder", "paketobuildpacks/builder:base",
        "--path", str(source_dir),
        "--publish"
    ]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in iter(process.stdout.readline, ""):
            print(line, end="")
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"error building and pushing image {image_name} with tag {tag} from {source_dir}: {process.stderr}")
        print(f"image {image_name} with tag {tag} built and pushed successfully")
    except FileNotFoundError:
        print("Error: 'pack' CLI not found. Is it installed and in your PATH?")
        raise HTTPException(status_code=500, detail="Error: 'pack' CLI not found. Is it installed and in your PATH?")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"error building and pushing image {image_name} with tag {tag} from {source_dir}: {e}")


def mirror_to_sourcecommit(
    github_repo_url: str,
    installation_or_access_token: str,
    sc_project_id: str,
    sc_repo_name: str,
    sc_username: str | None = None,
    sc_password: str | None = None,
    sc_endpoint: str | None = None,
    sc_full_url: str | None = None,
    commit_sha: str | None = None,
) -> dict:
    """Clone from GitHub (with installation token if provided) and mirror push to NCP SourceCommit.

    Parameters:
    - github_repo_url: https URL of GitHub repo
    - installation_or_access_token: GitHub App installation token (preferred) or PAT
    - sc_project_id: SourceCommit project id
    - sc_repo_name: Target repository name to push to
    - sc_username/password: SourceCommit basic auth (or use token as username and 'x' as password)
    - sc_endpoint: e.g., https://sourcecommit.apigw.ntruss.com
    - commit_sha: Git commit SHA to use as image tag (default: "latest")
    """
    work_dir = Path("/tmp") / f"mirror-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    bare_dir = work_dir / "bare.git"
    try:
        # Prepare authenticated GitHub URL
        gh_url = github_repo_url
        if installation_or_access_token and github_repo_url.startswith("https://"):
            if installation_or_access_token.startswith("ghs_"):
                gh_url = github_repo_url.replace("https://", f"https://x-access-token:{installation_or_access_token}@", 1)
            else:
                gh_url = github_repo_url.replace("https://", f"https://{installation_or_access_token}:x-oauth-basic@", 1)

        # Bare clone
        subprocess.run(["git", "clone", "--mirror", gh_url, str(bare_dir)], check=True, capture_output=True, text=True)

        # Compose SourceCommit URL (prefer explicit full URL if provided)
        if sc_full_url:
            sc_url = sc_full_url
        else:
            # Try resolve via API; if not available, fall back to DevTools public URL pattern
            # Resolve clone URL via API if available
            try:
                resolved = get_sourcecommit_repo_public_url(sc_project_id, sc_repo_name)  # type: ignore
            except Exception:
                resolved = None
            sc_url = resolved or f"https://devtools.ncloud.com/{sc_project_id}/{sc_repo_name}.git"
        # Basic auth only when at least one of username/password provided (non-empty)
        u_raw = (sc_username or "").strip()
        p_raw = (sc_password or "").strip()
        if u_raw or p_raw:
            user = quote(u_raw or "token", safe="")
            pwd = quote(p_raw or "x", safe="")
            sc_url = sc_url.replace("https://", f"https://{user}:{pwd}@", 1)

        # Push only main branch (not mirror to avoid syncing master/other branches)
        try:
            # Push main branch only
            subprocess.run(["git", "-C", str(bare_dir), "push", "-f", sc_url, "main:main"], check=True, capture_output=True, text=True)
            _dbg("SC-PUSH-MAIN", status="success")
        except subprocess.CalledProcessError as e_main:
            _dbg("SC-PUSH-MAIN-ERR", err=e_main.stderr[:200] if getattr(e_main, 'stderr', None) else str(e_main))
            # Fallback: try pushing all refs if main doesn't exist
            try:
                subprocess.run(["git", "-C", str(bare_dir), "push", "--all", sc_url], check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                pass
        # Push tags
        try:
            subprocess.run(["git", "-C", str(bare_dir), "push", "--tags", sc_url], check=False, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            pass
        # Optional: auto-inject a default Kubernetes manifest into SourceCommit after mirroring
        try:
            if os.getenv("KLEPAAS_AUTOINJECT_MANIFEST_ON_LINK", "true").lower() in ("1", "true", "yes"):  # enabled by default
                _dbg("SC-INJECT-MANIFEST", repo=sc_full_url, commit_sha=commit_sha)
                inj_dir = work_dir / "inject"
                # ensure parent exists; do NOT pre-create destination for git clone
                try:
                    parent = inj_dir.parent
                    if parent and not parent.exists():
                        parent.mkdir(parents=True, exist_ok=True)
                    if inj_dir.exists():
                        shutil.rmtree(inj_dir, ignore_errors=True)
                except Exception:
                    pass
                # Wait a bit for credentials/permission propagation on DevTools Git side
                try:
                    time.sleep(5)
                except Exception:
                    pass
                # Clone SourceCommit repo (reuse auth in sc_url if present) with retry for propagation
                clone_ok = False
                for attempt in range(1, 6):
                    try:
                        # destination must NOT exist for clone
                        if inj_dir.exists():
                            shutil.rmtree(inj_dir, ignore_errors=True)
                        subprocess.run(["git", "clone", sc_url, str(inj_dir)], check=True, capture_output=True, text=True)
                        clone_ok = True
                        break
                    except subprocess.CalledProcessError as _ce:
                        _dbg("SC-INJECT-CLONE-RETRY", attempt=attempt, err=_ce.stderr[:200] if getattr(_ce, 'stderr', None) else str(_ce))
                        # clean and retry (do not recreate dest)
                        try:
                            if inj_dir.exists():
                                shutil.rmtree(inj_dir, ignore_errors=True)
                        except Exception:
                            pass
                        try:
                            time.sleep(min(5, attempt * 2))
                        except Exception:
                            pass
                if not clone_ok:
                    raise RuntimeError("clone failed after retries")
                # Select target branch: always use main
                target_branch = "main"

                # Fetch all branches from origin
                try:
                    subprocess.run(["git", "-C", str(inj_dir), "fetch", "--all"], check=True, capture_output=True, text=True)
                except Exception:
                    pass

                # Check if main branch exists on origin
                chk_main = subprocess.run(["git", "-C", str(inj_dir), "rev-parse", "--verify", "origin/main"], capture_output=True, text=True)
                main_exists = (chk_main.returncode == 0)

                if main_exists:
                    # Main branch exists - checkout tracking origin/main
                    subprocess.run(["git", "-C", str(inj_dir), "checkout", "-B", target_branch, "origin/main"], check=True, capture_output=True, text=True)
                    _dbg("SC-INJECT-CHECKOUT", branch=target_branch, source="origin/main")
                else:
                    # Main branch doesn't exist - create new orphan branch
                    subprocess.run(["git", "-C", str(inj_dir), "checkout", "--orphan", target_branch], check=True, capture_output=True, text=True)
                    # Remove all files from staging (clean slate)
                    subprocess.run(["git", "-C", str(inj_dir), "rm", "-rf", "."], check=False, capture_output=True, text=True)
                    _dbg("SC-INJECT-CHECKOUT", branch=target_branch, source="new_orphan")

                k8s_dir = inj_dir / "k8s"
                k8s_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = k8s_dir / "deployment.yaml"
                service_path = k8s_dir / "service.yaml"
                if not manifest_path.exists() or not service_path.exists():
                    repo_part_raw = Path(sc_full_url).stem if sc_full_url else (sc_repo_name or "app")
                    # Convert to lowercase for Kubernetes naming requirements
                    repo_part = repo_part_raw.lower()
                    # Build image name using lowercase only (no hyphen replacement)
                    try:
                        registry = getattr(settings, "ncp_container_registry_url", None)
                    except Exception:
                        registry = None
                    image_name_unified = repo_part
                    # Use commit SHA as tag if provided, otherwise use 'latest'
                    image_tag = commit_sha[:7] if commit_sha else "latest"
                    image_full = f"{registry}/{image_name_unified}:{image_tag}" if registry else f"{image_name_unified}:{image_tag}"
                    _dbg("SC-INJECT-IMAGE", image=image_full, commit_sha=commit_sha, image_tag=image_tag)
                    manifest = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {repo_part}-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {repo_part}
  template:
    metadata:
      labels:
        app: {repo_part}
    spec:
      imagePullSecrets:
      - name: ncp-cr
      containers:
      - name: {repo_part}
        image: {image_full}
        ports:
        - containerPort: 8080
""".strip()
                    service = f"""
apiVersion: v1
kind: Service
metadata:
  name: {repo_part}-svc
  namespace: default
spec:
  selector:
    app: {repo_part}
  ports:
  - name: http
    port: 80
    targetPort: 8080
""".strip()

                    # Write missing files only (idempotent)
                    if not manifest_path.exists():
                        manifest_path.write_text(manifest, encoding="utf-8")
                    if not service_path.exists():
                        service_path.write_text(service, encoding="utf-8")
                    # Ensure committer identity
                    subprocess.run(["git", "-C", str(inj_dir), "config", "user.email", "bot@k-le-paas.local"], check=False, capture_output=True, text=True)
                    subprocess.run(["git", "-C", str(inj_dir), "config", "user.name", "K-Le-PaaS Bot"], check=False, capture_output=True, text=True)
                    subprocess.run(["git", "-C", str(inj_dir), "add", "k8s/deployment.yaml"], check=True, capture_output=True, text=True)
                    subprocess.run(["git", "-C", str(inj_dir), "add", "k8s/service.yaml"], check=True, capture_output=True, text=True)
                    subprocess.run(["git", "-C", str(inj_dir), "commit", "-m", f"chore: add default k8s manifests with tag {image_tag}"], check=True, capture_output=True, text=True)
                    # Push to the checked out target branch explicitly
                    r2 = subprocess.run(["git", "-C", str(inj_dir), "push", "origin", f"HEAD:refs/heads/{target_branch}"], capture_output=True, text=True)
                    _dbg("SC-INJECT-PUSH-BR", br=target_branch, rc=r2.returncode, out=r2.stdout[:120])
        except Exception as _e:  # noqa: BLE001
            _dbg("SC-INJECT-MANIFEST-ERROR", err=str(_e))
        return {
            "status": "success",
            "source": github_repo_url,
            "target": sc_url.replace(user + ":" + pwd + "@", "") if (sc_username or sc_password) else sc_url,
        }
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"git error: {e.stderr}")
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass



def mirror_and_update_manifest(
    github_repo_url: str,
    installation_or_access_token: str,
    sc_project_id: str,
    sc_repo_name: str,
    image_repo: str,
    image_tag: str,
    sc_username: str | None = None,
    sc_password: str | None = None,
    sc_endpoint: str | None = None,
    sc_full_url: str | None = None,
) -> dict:
    """Mirror GitHub to SourceCommit, then update manifest with specific image tag.

    This function uses the existing mirror_to_sourcecommit to do the heavy lifting,
    then clones SourceCommit to update the manifest with actual image tag.

    Parameters:
    - github_repo_url: https URL of GitHub repo
    - installation_or_access_token: GitHub App installation token (preferred) or PAT
    - sc_project_id: SourceCommit project id
    - sc_repo_name: Target repository name to push to
    - image_repo: Container image repository (without tag) e.g., "kr.ncr.ntruss.com/owner_repo"
    - image_tag: Specific image tag to deploy e.g., "latest", "v1.2.3", commit SHA
    - sc_username/password: SourceCommit basic auth
    - sc_endpoint: e.g., https://sourcecommit.apigw.ntruss.com
    - sc_full_url: Full SourceCommit git URL (optional)

    Returns:
    - dict with status, manifest_updated flag, and deployed image
    """

    # Step 1: Use existing mirror function to sync GitHub → SourceCommit with commit SHA tag
    _dbg("MM-STEP1-MIRROR", github=github_repo_url, sc_repo=sc_repo_name, image_tag=image_tag)
    mirror_result = mirror_to_sourcecommit(
        github_repo_url=github_repo_url,
        installation_or_access_token=installation_or_access_token,
        sc_project_id=sc_project_id,
        sc_repo_name=sc_repo_name,
        sc_username=sc_username,
        sc_password=sc_password,
        sc_endpoint=sc_endpoint,
        sc_full_url=sc_full_url,
        commit_sha=image_tag  # Pass image_tag as commit SHA for manifest injection
    )
    _dbg("MM-STEP1-SUCCESS", result=mirror_result)

    # Step 2: Clone SourceCommit, update manifest with actual tag, push back
    work_dir = Path("/tmp") / f"manifest-update-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    sc_dir = work_dir / "sc_repo"

    try:
        # Compose SourceCommit URL with auth
        if sc_full_url:
            sc_url = sc_full_url
        else:
            try:
                resolved = get_sourcecommit_repo_public_url(sc_project_id, sc_repo_name)  # type: ignore
            except Exception:
                resolved = None
            sc_url = resolved or f"https://devtools.ncloud.com/{sc_project_id}/{sc_repo_name}.git"

        u_raw = (sc_username or "").strip()
        p_raw = (sc_password or "").strip()
        if u_raw or p_raw:
            user = quote(u_raw or "token", safe="")
            pwd = quote(p_raw or "x", safe="")
            sc_url = sc_url.replace("https://", f"https://{user}:{pwd}@", 1)

        _dbg("MM-STEP2-CLONE-SC", sc_url_masked=sc_url.replace(f"{user}:{pwd}@", "***@") if (u_raw or p_raw) else sc_url)

        # Clone SourceCommit
        subprocess.run(
            ["git", "clone", sc_url, str(sc_dir)],
            check=True,
            capture_output=True,
            text=True
        )

        _dbg("MM-STEP2-CLONE-SUCCESS", dir=str(sc_dir))

        # Update manifest (or create if missing)
        k8s_dir = sc_dir / "k8s"
        manifest_path = k8s_dir / "deployment.yaml"
        service_path = k8s_dir / "service.yaml"
        manifest_updated = False

        if manifest_path.exists():
            import yaml

            _dbg("MM-MANIFEST-FOUND", path=str(manifest_path))

            # Read original content for debugging
            with open(manifest_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
                _dbg("MM-MANIFEST-ORIGINAL", content_preview=original_content[:200])

            # Parse YAML
            manifest = yaml.safe_load(original_content)
            _dbg("MM-MANIFEST-PARSED", has_spec='spec' in manifest)

            # Update image in all containers
            if 'spec' in manifest and 'template' in manifest['spec']:
                spec_template = manifest['spec'].get('template', {})
                spec_spec = spec_template.get('spec', {})
                containers = spec_spec.get('containers', [])
                _dbg("MM-CONTAINERS-FOUND", count=len(containers))

                for idx, container in enumerate(containers):
                    if 'image' in container:
                        old_image = container['image']
                        new_image = f"{image_repo}:{image_tag}"
                        container['image'] = new_image
                        _dbg("MM-IMAGE-UPDATE",
                             container_idx=idx,
                             old=old_image,
                             new=new_image,
                             image_repo=image_repo,
                             image_tag=image_tag)
                        manifest_updated = True
            else:
                _dbg("MM-MANIFEST-STRUCTURE-ERROR",
                     has_spec='spec' in manifest,
                     has_template='template' in manifest.get('spec', {}))

            if manifest_updated:
                # Write updated manifest (preserve formatting)
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

                # Verify the change was written
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    updated_content = f.read()
                    _dbg("MM-MANIFEST-UPDATED", content_preview=updated_content[:200])

                # Git commit and push
                subprocess.run(
                    ["git", "-C", str(sc_dir), "config", "user.email", "bot@k-le-paas.local"],
                    check=True, capture_output=True, text=True
                )
                subprocess.run(
                    ["git", "-C", str(sc_dir), "config", "user.name", "K-Le-PaaS Bot"],
                    check=True, capture_output=True, text=True
                )
                subprocess.run(
                    ["git", "-C", str(sc_dir), "add", "k8s/deployment.yaml"],
                    check=True, capture_output=True, text=True
                )
                subprocess.run(
                    ["git", "-C", str(sc_dir), "commit", "-m", f"chore: update image tag to {image_tag}"],
                    check=True, capture_output=True, text=True
                )

                # Check current branch and push
                branch_result = subprocess.run(
                    ["git", "-C", str(sc_dir), "branch", "--show-current"],
                    capture_output=True, text=True
                )
                current_branch = branch_result.stdout.strip() or "main"
                _dbg("MM-GIT-PUSH-UPDATE", branch=current_branch)

                subprocess.run(
                    ["git", "-C", str(sc_dir), "push", "origin", current_branch],
                    check=True, capture_output=True, text=True
                )

                _dbg("MM-STEP2-PUSH-SUCCESS", image_tag=image_tag, branch=current_branch)
        else:
            # Manifest doesn't exist - create it now
            _dbg("MM-MANIFEST-NOT-FOUND", path=str(manifest_path), action="creating_now")

            k8s_dir.mkdir(parents=True, exist_ok=True)

            # Extract repo name for Kubernetes naming
            repo_part_raw = sc_repo_name or "app"
            repo_part = repo_part_raw.lower()

            # Create deployment manifest
            manifest_content = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {repo_part}-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {repo_part}
  template:
    metadata:
      labels:
        app: {repo_part}
    spec:
      imagePullSecrets:
      - name: ncp-cr
      containers:
      - name: {repo_part}
        image: {image_repo}:{image_tag}
        ports:
        - containerPort: 8080
"""

            # Create service manifest
            service_content = f"""apiVersion: v1
kind: Service
metadata:
  name: {repo_part}-svc
  namespace: default
spec:
  selector:
    app: {repo_part}
  ports:
  - name: http
    port: 80
    targetPort: 8080
"""

            # Write manifests
            manifest_path.write_text(manifest_content, encoding="utf-8")
            service_path.write_text(service_content, encoding="utf-8")
            _dbg("MM-MANIFESTS-CREATED", deployment=str(manifest_path), service=str(service_path))

            # Git commit and push
            subprocess.run(
                ["git", "-C", str(sc_dir), "config", "user.email", "bot@k-le-paas.local"],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ["git", "-C", str(sc_dir), "config", "user.name", "K-Le-PaaS Bot"],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ["git", "-C", str(sc_dir), "add", "k8s/"],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ["git", "-C", str(sc_dir), "commit", "-m", f"chore: add k8s manifests with tag {image_tag}"],
                check=True, capture_output=True, text=True
            )

            # Check current branch and push
            branch_result = subprocess.run(
                ["git", "-C", str(sc_dir), "branch", "--show-current"],
                capture_output=True, text=True
            )
            current_branch = branch_result.stdout.strip() or "main"
            _dbg("MM-GIT-PUSH", branch=current_branch)

            subprocess.run(
                ["git", "-C", str(sc_dir), "push", "origin", current_branch],
                check=True, capture_output=True, text=True
            )

            manifest_updated = True
            _dbg("MM-MANIFESTS-PUSHED", image_tag=image_tag, branch=current_branch)

        return {
            "status": "success",
            "source": github_repo_url,
            "target": sc_url.replace(f"{user}:{pwd}@", "") if (sc_username or sc_password) else sc_url,
            "manifest_updated": manifest_updated,
            "image": f"{image_repo}:{image_tag}"
        }

    except subprocess.CalledProcessError as e:
        error_detail = e.stderr if hasattr(e, 'stderr') else str(e)
        _dbg("MM-ERROR", error=error_detail[:500])
        raise HTTPException(status_code=400, detail=f"git error during manifest update: {error_detail}")
    except Exception as e:
        _dbg("MM-UNEXPECTED-ERROR", error=str(e)[:500])
        raise HTTPException(status_code=500, detail=f"Unexpected error during manifest update: {str(e)}")
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
            _dbg("MM-CLEANUP", work_dir=str(work_dir))
        except Exception:
            pass


def ensure_sourcecommit_repo(project_id: str, repo_name: str) -> dict:
    """Create SourceCommit repository if not exists using official REST path.
    Note: SourceCommit repository creation is not scoped by DevTools project id in REST.
    """
    # Prefer REST (official): POST /api/v1/repository with body {"name": repo_name}
    access_key = getattr(settings, "ncp_access_key", None)
    secret_key = getattr(settings, "ncp_secret_key", None)
    if not access_key or not secret_key:
        return {"status": "skipped", "reason": "ncp credentials missing"}

    base = getattr(settings, "ncp_sourcecommit_endpoint", "https://sourcecommit.apigw.ntruss.com")
    method = "POST"
    uri = "/api/v1/repository"
    ts = str(int(time.time() * 1000))
    msg = f"{method} {uri}\n{ts}\n{access_key}"
    sig = base64.b64encode(hmac.new(secret_key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
    url = f"{base}{uri}"
    headers = {
        "x-ncp-apigw-timestamp": ts,
        "x-ncp-iam-access-key": access_key,
        "x-ncp-apigw-signature-v2": sig,
        "Content-Type": "application/json",
        "x-ncp-region_code": getattr(settings, "ncp_region", "KR"),
    }
    body = {"name": repo_name}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            print(f"[SourceCommit] POST {url} region={headers['x-ncp-region_code']} signed='{msg}'")
            resp = client.post(url, json=body, headers=headers)
            _dbg("SC-CREATE", url=url, code=resp.status_code)
        if resp.status_code in (200, 201):
            # Some responses return {"result": true}
            try:
                j = resp.json() or {}
                if j.get("result") is True:
                    return {"status": "created"}
            except Exception:
                pass
            return {"status": "created"}
        if resp.status_code in (400, 409):
            # Duplicate or already exists
            return {"status": "exists"}
        return {
            "status": "error",
            "code": resp.status_code,
            "detail": resp.text[:500],
            "final_url": str(resp.request.url),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SourceCommit REST error: {e}")

def create_ncp_pipeline_resource(app_name: str, image_name: str) -> dict:
    print("starting to create NCP pipeline resource")
    if not NCP_AVAILABLE:
        raise HTTPException(status_code=501, detail="ncloud-sdk 미설치: 'pip install ncloud-sdk' 후 서버를 재시작하세요")
    deploy_api = SourceDeployApi(ncloud_client.api_client)
    pipeline_api = SourcePipelineApi(ncloud_client.api_client)

    try:
        print(f"Creating SourceDeploy project for {app_name} ...")
        deploy_project_name = f"k-le-paas-deploy-{app_name}"
        deploy_request = {
            "name": deploy_project_name,
            "stages": [{
                "name": "production",
                "scenarios": [{
                    "name": "deploy-app",
                    "type": "KUBERNETES",
                    "files": [{
                        "type": "TEXT",
                        "path": "deployment.yaml",
                        # 이미지를 동적으로 교체하는 Kubernetes Manifest 예시
                        "content": f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}-deployment
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      containers:
      - name: {app_name}
        image: {image_name}
        ports:
        - containerPort: 80
"""
                    }],
                    "target": {
                        "type": "ID",
                        "id": getattr(settings, "ncp_nks_cluster_id", "YOUR_NKS_CLUSTER_ID")
                    },
                    "kubeconfig": getattr(settings, "ncp_nks_kubeconfig_b64", "YOUR_NKS_KUBECONFIG_IN_BASE64")
                }]
            }]
        }
        create_deploy_project = deploy_api.create_project(**deploy_request)
        deploy_project_id = create_deploy_project.id
        print(f"SourceDeploy project {deploy_project_name} created with ID: {deploy_project_id}")

        print(f"Creating SourcePipeline for {app_name} ...")
        pipeline_name=f"k-le-paas-pipeline-{app_name}"
        pipeline_request = {
            "name": pipeline_name,
            "stages": [{
                "name":"Deploy",
                "type":"DEPLOY",
                "project_id":deploy_project_id,
                "stage_name":"production",
                "scenario_name":"deploy-app",
            }]
        }
        created_pipeline = pipeline_api.create_pipeline(**pipeline_request)
        pipeline_id = created_pipeline.id
        print(f"SourcePipeline {pipeline_name} created with ID: {pipeline_id}")

        return {
            "status": "success",
            "message": f"NCP pipeline resource created successfully for {app_name}",
            "deploy_project_id": deploy_project_id,
            "pipeline_id": pipeline_id,
            "deployed_image": image_name
        }

    except ApiException as e:
        print(f"NCP API Exception: {getattr(e, 'status', 500)} {getattr(e, 'reason', '')}\nBody: {getattr(e, 'body', '')}")
        raise HTTPException(status_code=getattr(e, "status", 500), detail=f"NCP API Exception: {getattr(e, 'status', 500)} {getattr(e, 'reason', '')}\nBody: {getattr(e, 'body', '')}")
    except Exception as e:
        print(f"Unexpected error occurred during NCP pipeline resource creation: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


async def create_split_build_deploy_pipeline(
    pipeline_name: str,
    owner: str,
    repo: str,
    branch: str = "main",
    sc_project_id: str | None = None,
    sc_repo_name: str | None = None,
    db: Session | None = None,
    user_id: str | None = None,
) -> dict:
    """Create separate SourceBuild and SourceDeploy projects, then a pipeline that runs Build -> Deploy.

    Note: Exact SDK shapes can vary by version; we use common keys and graceful 501 on unsupported calls.
    """
    # Proceed even if some optional APIs are missing; validate per feature below

    registry = getattr(settings, "ncp_container_registry_url", None)
    if not registry:
        raise HTTPException(status_code=400, detail="레지스트리 URL이 설정되지 않았습니다 (KLEPAAS_NCP_CONTAINER_REGISTRY_URL)")
    # Use lowercase only image name (no hyphen replacement)
    def _norm_part(s: str | None) -> str:
        raw = (s or "").lower()
        # Only allow [a-z0-9-], lowercased for registry compatibility
        return "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in raw) or "app"
    image_name_unified = f"{_norm_part(owner)}-{_norm_part(repo)}"
    image_repo = f"{registry}/{image_name_unified}"

    # Resolve SourceBuild project ID: DB first → lookup → create if missing
    build_project_id = None
    if db is not None and user_id is not None:
        integ_existing = get_integration(db, user_id=user_id, owner=owner, repo=repo)
        if integ_existing and getattr(integ_existing, 'build_project_id', None):
            build_project_id = getattr(integ_existing, 'build_project_id')
    if not build_project_id:
        # try find by name first
        build_project_id = await _find_sourcebuild_project_id_by_name(
            getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com'),
            f"build-{owner}-{repo}"
        ) or None
        if not build_project_id:
            # create minimal SourceBuild project
            build_project_id = await create_sourcebuild_project_rest(
                owner=owner,
                repo=repo,
                branch=branch,
                image_repo=image_repo,
                sc_project_id=sc_project_id,
                sc_repo_name=sc_repo_name,
            )
            # If creation reported exists-without-id, resolve by name again
            if str(build_project_id).strip() == "__EXISTS_NO_ID__":
                build_project_id = await _find_sourcebuild_project_id_by_name(
                    getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com'),
                    f"build-{owner}-{repo}"
                ) or None
        if build_project_id and db is not None and user_id is not None:
            upsert_integration(
                db,
                user_id=user_id,
                owner=owner,
                repo=repo,
                sc_project_id=sc_project_id,
                sc_repo_name=sc_repo_name,
                build_project_id=str(build_project_id),
                registry_url=getattr(settings, "ncp_container_registry_url", None),
                image_repository=image_repo,
                branch=branch,
            )

    # Prepare deploy manifest and cluster/kubeconfig first
    nks_cluster_id = getattr(settings, "ncp_nks_cluster_id", None)
    kubeconfig_b64 = getattr(settings, "ncp_nks_kubeconfig_b64", None)
    deploy_manifest = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {repo}-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {repo}
  template:
    metadata:
      labels:
        app: {repo}
    spec:
      containers:
      - name: {repo}
        image: {image_repo}:${{TAG}}
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: {repo}-svc
  namespace: default
spec:
  selector:
    app: {repo}
  ports:
  - port: 80
    targetPort: 80
"""
    # Ensure SourceDeploy project by name → create if missing
    deploy_project_id = await ensure_sourcedeploy_project(
        owner=owner,
        repo=repo,
        manifest_text=deploy_manifest,
        nks_cluster_id=nks_cluster_id,
        db=db,
        user_id=user_id,
    )

    # Resolve missing IDs by name and persist immediately
    if not build_project_id:
        try:
            b_resolved = await _find_sourcebuild_project_id_by_name(getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com'), f"build-{owner}-{repo}")
            if b_resolved:
                build_project_id = b_resolved
                if db is not None and user_id is not None:
                    upsert_integration(db, user_id=user_id, owner=owner, repo=repo, build_project_id=str(b_resolved))
        except Exception:
            pass
    if not deploy_project_id:
        try:
            d_resolved = await _find_sourcedeploy_project_id_by_name(getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com'), f"deploy-{owner}-{repo}")
            if d_resolved:
                deploy_project_id = d_resolved
                if db is not None and user_id is not None:
                    upsert_integration(db, user_id=user_id, owner=owner, repo=repo, deploy_project_id=str(d_resolved))
        except Exception:
            pass

    # Create Pipeline referencing both projects (SDK or REST)
    # If build/deploy IDs are still missing, try DB-first to honor contract
    if (not build_project_id or not deploy_project_id) and db is not None and user_id is not None:
        integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
        if integ:
            build_project_id = build_project_id or getattr(integ, 'build_project_id', None)
            deploy_project_id = deploy_project_id or getattr(integ, 'deploy_project_id', None)

    # Final attempt to resolve sentinel exists-without-id
    if isinstance(build_project_id, str) and build_project_id.strip() == "__EXISTS_NO_ID__":
        try:
            build_project_id = await _find_sourcebuild_project_id_by_name(
                getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com'),
                f"build-{owner}-{repo}"
            ) or None
        except Exception:
            pass
    if isinstance(deploy_project_id, str) and deploy_project_id.strip() == "__EXISTS_NO_ID__":
        try:
            deploy_project_id = await _find_sourcedeploy_project_id_by_name(
                getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com'),
                f"deploy-{owner}-{repo}"
            ) or None
        except Exception:
            pass

    if not build_project_id or not deploy_project_id:
        raise HTTPException(status_code=400, detail=f"Invalid build/deploy project id (build={build_project_id}, deploy={deploy_project_id}). Ensure both IDs exist and are numeric.")

    if SourcePipelineApi is None:
        pipeline_id = await create_sourcepipeline_rest(pipeline_name, str(build_project_id), str(deploy_project_id))
    else:
        pipeline_api = SourcePipelineApi(ncloud_client.api_client)
        try:
            pipe_req = {
                "name": pipeline_name,
                "stages": [
                    {"name": "Build", "type": "BUILD", "project_id": build_project_id},
                    {"name": "Deploy", "type": "DEPLOY", "project_id": deploy_project_id, "stage_name": "production", "scenario_name": "deploy-app"},
                ],
            }
            p = pipeline_api.create_pipeline(**pipe_req)
            pipeline_id = getattr(p, "id", None)
        except ApiException as e:
            raise HTTPException(status_code=getattr(e, "status", 500), detail=f"SourcePipeline API Exception: {getattr(e, 'body', str(e))}")
    # persist mapping if db/user provided
    if db is not None and user_id is not None:
        upsert_integration(
            db,
            user_id=user_id,
            owner=owner,
            repo=repo,
            sc_project_id=sc_project_id,
            sc_repo_name=sc_repo_name,
            build_project_id=str(build_project_id) if build_project_id else None,
            deploy_project_id=str(deploy_project_id) if deploy_project_id else None,
            pipeline_id=str(pipeline_id) if pipeline_id else None,
            registry_url=getattr(settings, "ncp_container_registry_url", None),
            image_repository=image_repo,
            branch=branch,
            auto_deploy_enabled=True,
        )
    return {"status": "created", "build_project_id": build_project_id, "deploy_project_id": deploy_project_id, "pipeline_id": pipeline_id, "image_repo": image_repo}


async def run_sourcebuild(
    build_project_id: str,
    image_repo: str | None = None,
    commit_sha: str | None = None,  # For rollback: specify exact commit to build
    sc_project_id: str | None = None,
    sc_repo_name: str | None = None,
    branch: str | None = None
) -> dict:
    """Run SourceBuild project and wait for completion.

    If image_repo is provided, include artifact+builder in trigger body so apigw
    executes a real Dockerfile build and pushes to NCR.

    If commit_sha is provided, builds that specific commit (for rollback scenarios).
    Otherwise, builds the latest commit from the branch.
    """
    base = getattr(settings, 'ncp_sourcebuild_endpoint', 'https://sourcebuild.apigw.ntruss.com')

    # 0. 프로젝트 상세 조회하여 cache 구성(레지스트리/이미지/태그) 확보
    registry_project: str | None = None
    image_name_from_project: str | None = None
    image_tag: str = commit_sha if commit_sha else 'latest'  # Use commit SHA as tag for rollback
    try:
        proj_detail = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{build_project_id}")
        proj_result = proj_detail.get('result', {}) if isinstance(proj_detail, dict) else {}
        cache_cfg = (proj_result.get('cache') or {}) if isinstance(proj_result, dict) else {}
        registry_project = cache_cfg.get('registry') or None
        image_name_from_project = cache_cfg.get('image') or None
        # Only use cache tag if commit_sha wasn't explicitly provided
        if not commit_sha:
            image_tag = cache_cfg.get('tag') or image_tag
        _dbg("SB-PROJECT-CACHE", registry=registry_project, image=image_name_from_project, image_tag=image_tag, commit_sha=commit_sha)
    except Exception as e:
        _dbg("SB-PROJECT-CACHE-ERR", error=str(e)[:200])

    # 1. Determine final registry and image name FIRST (before cache update)
    # Use image name directly from project cache config (already has timestamp for uniqueness)
    if image_name_from_project:
        # Project cache config has image name with timestamp (created at project creation time)
        # No need to append anything - the timestamp already ensures uniqueness
        final_image_name = image_name_from_project
        final_registry_project = registry_project or "klepaas-test"
        _dbg("SB-IMAGE-SOURCE", source="project_cache_config",
             image=final_image_name,
             registry=final_registry_project)
    elif image_repo:
        # Fallback: derive from image_repo if cache config is missing
        try:
            registry_host, image_path = image_repo.split("/", 1)
        except ValueError:
            registry_host, image_path = image_repo, image_repo
        # Extract image name and convert to lowercase for NCR compatibility
        raw_image_name = image_path.rsplit("/", 1)[-1]
        final_image_name = raw_image_name.lower()  # ✅ 소문자 변환 추가
        final_registry_project = (registry_host or "").split(".")[0] or "klepaas-test"
        _dbg("SB-IMAGE-SOURCE", source="fallback_image_repo",
             image=final_image_name,
             registry=final_registry_project)
    else:
        raise HTTPException(status_code=400, detail="빌드 실행 실패: 이미지 이름을 결정할 수 없습니다")

    # 2. 프로젝트 설정 업데이트 - cmd.dockerbuild의 tag 업데이트
    # IMPORTANT: 프로젝트 생성 시 cmd.dockerbuild를 사용했으므로 동일하게 PATCH
    _dbg("SB-UPDATE-PROJECT-TAG", project_id=build_project_id, image_tag=image_tag)
    try:
        update_body = {
            "cmd": {
                "dockerbuild": {
                    "use": True,
                    "dockerfile": "Dockerfile",
                    "registry": final_registry_project,
                    "image": final_image_name,
                    "tag": image_tag,
                    "latest": (image_tag == "latest")
                }
            }
        }
        await _call_ncp_rest_api('PATCH', base, f"/api/v1/project/{build_project_id}", update_body)
        _dbg("SB-PROJECT-TAG-UPDATED", image_tag=image_tag)
    except Exception as e:
        _dbg("SB-PROJECT-TAG-UPDATE-ERR", error=str(e)[:200])
        # Continue anyway - tag update failure shouldn't block build (will use trigger body)

    # 3. 빌드 시작
    _dbg("SB-BUILD-TRIGGER", project_id=build_project_id, image_tag=image_tag)

    # Console-compatible trigger body (cmd.dockerbuild) + explicit artifact push
    # This matches the PROVEN WORKING configuration from af4b939 commit
    # Construct full registry URL for artifact config
    if image_repo:
        registry_host = image_repo.split("/")[0] if "/" in image_repo else image_repo
    else:
        registry_host = f"{final_registry_project}.kr.ncr.ntruss.com"

    trigger_body = {
        "env": {
            "docker": {"use": True, "id": 1}
        },
        "cmd": {
            "pre": [],
            "build": [],
            "post": [],
            "dockerbuild": {
                "use": True,
                "dockerfile": "Dockerfile",
                "region": 1,
                "registry": final_registry_project,
                "image": final_image_name,
                "tag": image_tag,
                "latest": (image_tag == "latest")
            }
        },
        # Explicit artifact push to Container Registry
        "artifact": {
            "use": True,
            "type": "ContainerRegistry",
            "config": {
                "registry": f"{registry_host}/{final_image_name}",
                "tag": image_tag
            }
        },
        # Ensure image push is retained via cache block on tenants that require it
        "cache": {
            "use": True,
            "registry": final_registry_project,
            "image": final_image_name,
            "tag": image_tag,
            "latest": (image_tag == "latest"),
            "region": 1
        }
    }

    # NOTE: Do NOT add sourcecommit field to trigger body
    # It causes NCP to ignore builder config and use Buildpack instead
    # The commit SHA is used only for image tagging via cache.tag
    # SourceCommit integration handles the actual git commit automatically

    _dbg("SB-TRIGGER-BODY", body=trigger_body, commit_sha=commit_sha)
    build_data = await _call_ncp_rest_api('POST', base, f"/api/v1/project/{build_project_id}/build", trigger_body)
    # Accept multiple response shapes
    build_id = (
        (build_data.get('result') or {}).get('buildId')
        or build_data.get('buildId')
        or build_data.get('id')
    )
    
    if not build_id:
        raise HTTPException(status_code=500, detail="SourceBuild 실행 실패: 빌드 ID를 얻지 못했습니다.")
    
    _dbg("SB-BUILD-STARTED", build_id=build_id)
    
    # 2. 빌드 완료까지 폴링 (history 목록 기반, 최대 ~5분)
    # 초기 대기 (빌드 시작 여유)
    await asyncio.sleep(5)
    for attempt in range(30):  # 30번 × 10초 = 5분 (이미지 push 시간 고려)
        if attempt > 0:
            await asyncio.sleep(10)
        try:
            # Use history list instead of detail endpoint (detail returns 404)
            list_path = f"/api/v1/project/{build_project_id}/history"
            history_data = await _call_ncp_rest_api('GET', base, list_path)
            items = (
                (history_data.get('result') or {}).get('history')
                or (history_data.get('result') or {}).get('builds')
                or history_data.get('history')
                or history_data.get('builds')
                or []
            )
            # Find current build in list
            current = None
            for it in items:
                bid = it.get('buildId') or it.get('id')
                if str(bid) == str(build_id):
                    current = it
                    break

            if not current:
                _dbg("SB-BUILD-POLL", build_id=build_id, status="not_found_in_list", attempt=attempt + 1)
                continue

            status = current.get('status') or current.get('buildStatus')
            _dbg("SB-BUILD-POLL", build_id=build_id, status=status, attempt=attempt + 1, begin=current.get('begin'), end=current.get('end'))

            st = str(status).lower() if status is not None else None
            if st in ("success", "succeeded", "completed"):
                container_image = current.get('containerImageUrl') or current.get('image')
                if not container_image:
                    # Fallback: construct from project cache config
                    if final_registry_project and final_image_name:
                        container_image = f"{final_registry_project}.kr.ncr.ntruss.com/{final_image_name}:{image_tag}"
                        _dbg("SB-IMAGE-FALLBACK", source="cache_config", image=container_image)
                    elif image_repo:
                        container_image = f"{image_repo}:{image_tag}"
                        _dbg("SB-IMAGE-FALLBACK", source="image_repo", image=container_image)

                if not container_image:
                    # 상세 응답에도 이미지 경로가 없으면 이미지 푸시가 수행되지 않은 것으로 판단
                    raise HTTPException(status_code=500, detail="SourceBuild 성공으로 표시되었으나 containerImageUrl이 없습니다 (이미지 푸시 미수행)")

                # NCR verify with short backoff (~30s)
                verified = False
                verify_code = None
                if container_image:
                    delays = [2, 4, 6, 8, 10]
                    for vi, delay in enumerate(delays, start=1):
                        try:
                            v = await _verify_ncr_manifest_exists(container_image)
                            verified = bool(v.get("exists"))
                            verify_code = v.get("code")
                            _dbg("NCR-VERIFY", attempt=vi, code=verify_code, verified=verified)
                            if verified:
                                break
                        except Exception as _ve:
                            _dbg("NCR-VERIFY-ERR", err=str(_ve)[:200])
                        if vi < len(delays):
                            await asyncio.sleep(delay)

                _dbg("SB-BUILD-SUCCESS", build_id=build_id, image=container_image, image_tag=image_tag, registry_verified=verified, verify_code=verify_code)
                return {
                    "status": st,
                    "build_id": build_id,
                    "image": container_image,
                    "image_tag": image_tag,
                    "build_project_id": build_project_id,
                    "registry_verified": verified,
                    "registry_verify_code": verify_code,
                }
            if st in ("failed", "error", "cancelled"):
                err = current.get('errorMessage') or current.get('message') or "Unknown error"
                _dbg("SB-BUILD-FAILED", build_id=build_id, status=status, error=err)
                raise HTTPException(status_code=500, detail=f"SourceBuild 실패: {status} - {err}")
            # running/pending → 계속 대기
            continue
        except HTTPException as e:
            _dbg("SB-HISTORY-ERR", error=str(e.detail))
            raise e
    
    # 타임아웃
    _dbg("SB-BUILD-TIMEOUT", build_id=build_id)
    raise HTTPException(status_code=500, detail="SourceBuild 타임아웃: 빌드 완료까지 너무 오래 걸립니다.")


async def _verify_sourcecommit_manifest(sc_repo_name: str) -> bool:
    """Verify if manifest files exist in SourceCommit repository."""
    try:
        # Check if manifest files exist using git ls-remote
        import subprocess
        import os
        
        # Get SourceCommit URL from settings
        sc_username = getattr(settings, 'ncp_sourcecommit_username', None)
        sc_password = getattr(settings, 'ncp_sourcecommit_password', None)
        sc_project_id = getattr(settings, 'ncp_sourcecommit_project_id', None)
        
        if not all([sc_username, sc_password, sc_project_id]):
            _dbg("SD-MANIFEST-CHECK", status="missing_credentials")
            return False
            
        sc_url = f"https://{sc_username}:{sc_password}@devtools.ncloud.com/{sc_project_id}/{sc_repo_name}.git"
        
        # Check if manifest files exist
        result = subprocess.run(
            ["git", "ls-remote", "--heads", sc_url, "main"],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            _dbg("SD-MANIFEST-CHECK", status="git_ls_remote_failed", error=result.stderr[:200])
            return False
            
        # Check if k8s directory exists
        result = subprocess.run(
            ["git", "ls-remote", "--heads", sc_url, "main:k8s/"],
            capture_output=True, text=True, timeout=30
        )
        
        manifest_exists = result.returncode == 0 and "k8s/deployment.yaml" in result.stdout
        _dbg("SD-MANIFEST-CHECK", status="success" if manifest_exists else "missing_manifest")
        return manifest_exists
        
    except Exception as e:
        _dbg("SD-MANIFEST-CHECK", status="error", error=str(e)[:200])
        return False

async def run_sourcedeploy(
    deploy_project_id: str,
    stage_name: str = "production",
    scenario_name: str = "deploy-app",
    sc_project_id: str | None = None,
    db: Session | None = None,
    user_id: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    tag: str | None = None,
    is_rollback: bool = False,
) -> dict:
    """Run SourceDeploy project via REST only using scenario deploy endpoint.

    Steps:
    1) GET project detail → find stage/scenario IDs by name
    2) If missing, create stage/scenario minimal; then re-fetch IDs
    3) POST /api/v1/project/{projectId}/stage/{stageId}/scenario/{scenarioId}/deploy

    NOTE: Scenario creation currently fails with error 330900 "unknown" from NCP API.
    This is a known issue where the API payload schema doesn't match NCP's expectations.
    As a workaround, scenarios should be created manually in NCP Console first.
    """
    base = getattr(settings, 'ncp_sourcedeploy_endpoint', 'https://vpcsourcedeploy.apigw.ntruss.com')
    nks_cluster_id = getattr(settings, 'ncp_nks_cluster_id', None)
    
    # honor the provided deploy_project_id without overriding
    
    # Use public endpoint for better accessibility during development
    _dbg("SD-ENDPOINT", endpoint=base, deploy_project_id=deploy_project_id, stage_name=stage_name, scenario_name=scenario_name, sc_project_id=sc_project_id)

    async def _get_stage_scenario_ids() -> tuple[str | None, str | None]:
        try:
            detail = await _call_ncp_rest_api('GET', base, [f"/api/v1/project/{deploy_project_id}"])
            result = detail.get('result', {}) if isinstance(detail, dict) else {}
            stages = result.get('stages') or result.get('stageList') or []
            sid = None
            scid = None
            for st in stages:
                if st.get('name') == stage_name:
                    sid = st.get('id') or st.get('stageId')
                    scs = st.get('scenarios') or st.get('scenarioList') or []
                    for sc in scs:
                        if sc.get('name') == scenario_name:
                            scid = sc.get('id') or sc.get('scenarioId')
                            break
                    break
            return (str(sid) if sid is not None else None, str(scid) if scid is not None else None)
        except HTTPException:
            return (None, None)

    stage_id, scenario_id = await _get_stage_scenario_ids()

    # Create minimal stage/scenario if missing
    if stage_id is None:
        _dbg("SD-STAGE-CREATE", project_id=deploy_project_id, name=stage_name, nks_cluster_id=nks_cluster_id)
        # Official NCP API schema for Kubernetes stage with cluster
        body = {
            "name": stage_name,
            "type": "KubernetesService",
            "config": {}
        }
        if nks_cluster_id:
            try:
                cluster_numeric_id = int(nks_cluster_id)
                body["config"]["clusterNo"] = cluster_numeric_id
                _dbg("SD-STAGE-CONFIG", type="KubernetesService", cluster_no=cluster_numeric_id)
            except (ValueError, TypeError):
                _dbg("SD-STAGE-WARNING", message=f"Invalid cluster ID format: {nks_cluster_id}")
        else:
            _dbg("SD-STAGE-WARNING", message="NKS cluster ID not provided, stage may not work properly")
        
        try:
            await _call_ncp_rest_api('POST', base, f"/api/v1/project/{deploy_project_id}/stage", body)
            _dbg("SD-STAGE-CREATED", project_id=deploy_project_id, name=stage_name)
        except HTTPException as e:
            _dbg("SD-STAGE-CREATE-ERR", code=getattr(e, 'status_code', None), detail=str(getattr(e, 'detail', ''))[:500])
            # Stage might already exist, continue

        # Poll stage list until the created stage appears with longer delays
        _dbg("SD-STAGE-POLL-START", project_id=deploy_project_id)
        for attempt, delay in enumerate((2, 3, 5, 10, 15, 20), start=1):
            await asyncio.sleep(delay)
            try:
                lst = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{deploy_project_id}/stage", None)
                items = (lst.get('result', {}) or {}).get('stages') or (lst.get('result', {}) or {}).get('stageList') or []
                for it in items:
                    if it.get('name') == stage_name:
                        stage_id = it.get('id') or it.get('stageId')
                        _dbg("SD-STAGE-FOUND", stage_id=stage_id, attempt=attempt, delay=delay)
                        break
                if stage_id:
                    break
            except HTTPException as e:
                _dbg("SD-STAGE-POLL-ERR", attempt=attempt, code=getattr(e, 'status_code', None))

        if not stage_id:
            _dbg("SD-STAGE-NOT-FOUND", project_id=deploy_project_id, name=stage_name)
            raise HTTPException(status_code=500, detail=f"Failed to create or find stage '{stage_name}' after polling")

        # NOTE: Target (cluster) is already set during stage creation via config.clusterNo
        # No need for separate target setting API call
    # Note: Scenario는 SDK를 통해 생성되어야 정상 작동합니다
    # create_sourcedeploy_project_sdk()에서 이미 생성 시도했으므로
    # 여기서는 기존 scenario를 찾기만 합니다

    if scenario_id is None:
        if stage_id is None:
            stage_id, _ = await _get_stage_scenario_ids()
            if not stage_id:
                raise HTTPException(status_code=500, detail=f"Stage '{stage_name}' not found for deploy project {deploy_project_id}")

        # Scenario 자동 생성 활성화 (Console에서 캡처한 정확한 스키마 사용)
        if stage_id is not None and scenario_id is None:
            _dbg("SD-SCENARIO-CREATE-START", project_id=deploy_project_id, stage_id=stage_id, name=scenario_name)

            # Get SourceCommit repo name
            sc_repo_name: str | None = None
            try:
                lst = await _call_ncp_rest_api('GET', base, '/api/v1/project', None)
                items = (lst.get('result', {}) or {}).get('projectList') or (lst.get('result', {}) or {}).get('projects') or []
                for it in items:
                    pid = str(it.get('id') or it.get('projectId'))
                    if pid == str(deploy_project_id):
                        nm = it.get('name') or ''
                        if nm.startswith('deploy-'):
                            sc_repo_name = nm[len('deploy-'):]
                        break
            except Exception as e:
                _dbg("SD-REPO-NAME-ERR", error=str(e)[:200])
                sc_repo_name = None

            if not sc_repo_name:
                _dbg("SD-REPO-NAME-MISSING", project_id=deploy_project_id)
                raise HTTPException(status_code=400, detail=f"Cannot derive SourceCommit repo name for scenario from deploy project {deploy_project_id}")
                
            # Assume manifest exists since auto-inject was enabled during create-and-link
            manifest_exists = True
            _dbg("SD-MANIFEST-ASSUME", reason="auto_inject_enabled_during_create_and_link", repo=sc_repo_name)

            # Prepare SourceCommit identifiers (DB first → REST)
            sc_proj_id = sc_project_id
            sc_repo_id: int | None = None
            # DB first
            if db is not None and user_id is not None and owner and repo:
                try:
                    integ_existing = get_integration(db, user_id=user_id, owner=owner, repo=repo)
                    val = getattr(integ_existing, "sc_repo_id", None) if integ_existing else None
                    if val:
                        try:
                            sc_repo_id = int(val)
                            _dbg("SD-SC-REPO-ID-DB", id=sc_repo_id)
                        except Exception:
                            sc_repo_id = None
                    if not sc_proj_id:
                        sc_proj_id = getattr(integ_existing, "sc_project_id", None)
                except Exception:
                    pass
            if not sc_proj_id or not sc_repo_id:
                try:
                    sc_base = getattr(settings, 'ncp_sourcecommit_endpoint', 'https://sourcecommit.apigw.ntruss.com')
                    sc_detail_meta = await _call_ncp_rest_api('GET', sc_base, f"/api/v1/repository/{sc_repo_name}")
                    sc_meta = sc_detail_meta.get('result', {}) if isinstance(sc_detail_meta, dict) else {}
                    if not sc_proj_id:
                        sc_proj_id = sc_meta.get('projectId') or sc_meta.get('projectID') or sc_meta.get('project_id')
                    if not sc_repo_id:
                        sc_repo_id = sc_meta.get('id') or sc_meta.get('repositoryId')
                    _dbg("SD-SC-RESOLVED-PROJECT-ID", id=sc_proj_id, repo=sc_repo_name)
                    _dbg("SD-SC-RESOLVED-REPO-ID", id=sc_repo_id, repo=sc_repo_name)
                    # persist to DB
                    if db is not None and user_id is not None and owner and repo and sc_repo_id:
                        try:
                            upsert_integration(db, user_id=user_id, owner=owner, repo=repo, sc_repo_id=str(int(sc_repo_id)))
                        except Exception:
                            pass
                except Exception as e:
                    _dbg("SD-SC-PROJECT-ID-ERR", error=str(e)[:200])
                    sc_proj_id = None
                    sc_repo_id = None

            # Golden payload per actual console payload (not API docs)
            _dbg("SD-SCENARIO-SCHEMA", type="console_payload", repo=sc_repo_name)
            # Use actual console payload structure with config wrapper
            body_sc = {
                "name": scenario_name,
                "config": {
                    "strategy": "rolling",  # Inside config object as API expects
                    "manifest": {
                        "type": "SourceCommit",  # Inside config.manifest
                        "repository": sc_repo_name,  # String value, not object
                        "branch": "main",
                        "path": [
                            "k8s/deployment.yaml",
                            "k8s/service.yaml"
                        ]
                    },
                    "env": {  # Environment variables for image tag injection
                        "IMAGE_TAG": "latest"  # Will be overridden during deploy
                    }
                },
                "description": "Auto-generated Kubernetes deployment with dynamic image tag"
            }
            _dbg("SD-SCENARIO-BODY", variant="consolePayload", body=body_sc)
            
            # Backoff attempts before creation (stage/target propagation)
            scenario_created = False
            last_error = None
            for attempt, delay in enumerate((5, 10, 15), start=1):
                await asyncio.sleep(delay)
                try:
                    _dbg("SD-SCENARIO-ATTEMPT", attempt=attempt, delay=delay, body_keys=list(body_sc.keys()))
                    await _call_ncp_rest_api('POST', base, f"/api/v1/project/{deploy_project_id}/stage/{stage_id}/scenario", body_sc)
                    _dbg("SD-SCENARIO-SUCCESS", attempt=attempt, delay=delay)
                    scenario_created = True
                    break
                except HTTPException as e1:
                    last_error = e1
                    _dbg("SD-SCENARIO-ERR", attempt=attempt, code=getattr(e1, 'status_code', None), detail=str(getattr(e1, 'detail', ''))[:500])
                    # Continue retrying with backoff
                    continue

        # Poll scenario list to get scenario_id (regardless of creation success/failure)
        # NCP API may not immediately return the created scenario, so always poll
        if scenario_id is None:
            if not scenario_created and last_error:
                _dbg("SD-SCENARIO-ALL-FAILED", last_error=str(getattr(last_error, 'detail', ''))[:500])

            _dbg("SD-SCENARIO-POLL-START", project_id=deploy_project_id, stage_id=stage_id, created=scenario_created)
            for poll_attempt in range(20):
                await asyncio.sleep(2.0)
                try:
                    lst = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{deploy_project_id}/stage/{stage_id}/scenario", None)
                    items = (lst.get('result', {}) or {}).get('scenarios') or (lst.get('result', {}) or {}).get('scenarioList') or []
                    _dbg("SD-SCENARIO-POLL-LIST", poll_attempt=poll_attempt, items_count=len(items), items=[it.get('name') for it in items])
                    for it in items:
                        if it.get('name') == scenario_name:
                            scenario_id = it.get('id') or it.get('scenarioId')
                            _dbg("SD-SCENARIO-POLL-FOUND", scenario_id=scenario_id, poll_attempt=poll_attempt)
                            break
                    if scenario_id:
                        break
                except HTTPException as e:
                    _dbg("SD-SCENARIO-POLL-ERR", poll_attempt=poll_attempt, code=getattr(e, 'status_code', None))

    # Image tag verification and environment variable preparation
    # Convert full commit SHA to 7-character short SHA if needed
    if tag and len(tag) > 7:
        effective_tag = tag[:7]
    else:
        effective_tag = tag or "latest"

    if not (owner and repo and sc_repo_name):
        _dbg("SD-DEPLOY-MISSING-PARAMS", owner=owner, repo=repo, sc_repo_name=sc_repo_name)
        raise HTTPException(
            status_code=400,
            detail=f"Missing required parameters for deployment: owner={owner}, repo={repo}, sc_repo_name={sc_repo_name}"
        )

    registry = getattr(settings, "ncp_container_registry_url", None)
    if not registry:
        _dbg("SD-MANIFEST-NO-REGISTRY")
        raise HTTPException(status_code=500, detail="Container registry URL not configured (KLEPAAS_NCP_CONTAINER_REGISTRY_URL)")

    image_repo, _ = _compose_image_repo(registry, owner, repo, build_project_id=None)
    desired_image = f"{image_repo}:{effective_tag}"

    # Verify image exists in registry before deployment
    _dbg("SD-IMAGE-VERIFY-START", image=desired_image)
    verification = await _verify_ncr_manifest_exists(desired_image)
    if not verification.get("exists"):
        error_code = verification.get("code")
        _dbg("SD-IMAGE-NOT-FOUND", image=desired_image, code=error_code)
        raise HTTPException(
            status_code=404,
            detail=f"Container image not found in registry: {desired_image} (HTTP {error_code}). Ensure SourceBuild completed successfully."
        )

    _dbg("SD-IMAGE-VERIFIED", image=desired_image, code=verification.get("code"))

    # Manifest uses ${IMAGE_TAG} environment variable - no file update needed
    # The tag will be injected at deployment time via SourceDeploy env config
    _dbg("SD-ENV-VAR-APPROACH", image_tag=effective_tag, template=f"{image_repo}:${{IMAGE_TAG}}")

    # Use the IDs we already have (polling already confirmed they exist)
    if not stage_id or not scenario_id:
        error_detail = f"Stage/Scenario not found (stage={stage_name}, scenario={scenario_name}). "
        error_detail += "\n\nNOTE: Scenario creation is currently failing with NCP API error 330900 'unknown'. "
        error_detail += "Please create the scenario manually in NCP Console:"
        error_detail += f"\n1. Go to https://console.ncloud.com → DevTools → SourceDeploy"
        error_detail += f"\n2. Open project ID: {deploy_project_id}"
        error_detail += f"\n3. Go to stage '{stage_name}' (ID: {stage_id or 'N/A'})"
        error_detail += f"\n4. Create scenario '{scenario_name}' with:"
        error_detail += f"\n   - Type: Kubernetes"
        error_detail += f"\n   - Manifest Source: SourceCommit"
        error_detail += f"\n   - Repository: {getattr(settings, 'ncp_sourcecommit_project_id', 'N/A')}"
        error_detail += f"\n   - Branch: main"
        error_detail += f"\n   - Path: k8s/deployment.yaml"
        error_detail += f"\n\nSee NCP_SCENARIO_DEBUG.md for more details."
        raise HTTPException(status_code=400, detail=error_detail)

    # Step 0: Mirror GitHub code to SourceCommit with manifest update (필수)
    # SourceBuild는 SourceCommit의 코드를 사용하므로, 먼저 최신 코드를 미러링해야 함
    # 이 단계에서 k8s/deployment.yaml의 이미지 태그도 함께 업데이트
    manifest_updated = False
    if owner and repo and sc_repo_name:
        _dbg("SC-MIRROR-START", owner=owner, repo=repo, sc_repo=sc_repo_name, image_tag=effective_tag)
        try:
            # Get GitHub Installation Token from DB
            github_token = None
            installation_id = None

            if db is not None and user_id is not None:
                try:
                    integ = get_integration(db, user_id=user_id, owner=owner, repo=repo)
                    if integ:
                        installation_id = getattr(integ, "github_installation_id", None)
                        _dbg("SC-MIRROR-INSTALLATION", installation_id=installation_id)
                except Exception as e:
                    _dbg("SC-MIRROR-INTEG-ERR", error=str(e)[:200])

            # Generate GitHub App Installation Token
            if installation_id:
                try:
                    from .github_app import github_app_auth
                    github_token = await github_app_auth.get_installation_token(installation_id)
                    _dbg("SC-MIRROR-TOKEN", token_prefix=github_token[:10] if github_token else None)
                except Exception as e:
                    _dbg("SC-MIRROR-TOKEN-ERR", error=str(e)[:200])

            if not github_token:
                # Fallback to environment variable
                github_token = os.environ.get("KLEPAAS_GITHUB_TOKEN") or getattr(settings, "github_token", None)
                _dbg("SC-MIRROR-FALLBACK", has_token=github_token is not None)

            if github_token and sc_project_id:
                github_repo_url = f"https://github.com/{owner}/{repo}.git"

                # Use new mirror function that updates manifest with actual image tag
                # Note: Do NOT pass sc_username/sc_password (NCP API keys are not Git credentials)
                mirror_result = mirror_and_update_manifest(
                    github_repo_url=github_repo_url,
                    installation_or_access_token=github_token,
                    sc_project_id=sc_project_id,
                    sc_repo_name=sc_repo_name,
                    image_repo=image_repo,
                    image_tag=effective_tag,
                    sc_endpoint=getattr(settings, "ncp_sourcecommit_endpoint", None)
                )
                _dbg("SC-MIRROR-SUCCESS", result=mirror_result)
                manifest_updated = mirror_result.get("manifest_updated", False)
            else:
                _dbg("SC-MIRROR-SKIP", reason="missing_github_token_or_project_id")
        except Exception as e:
            _dbg("SC-MIRROR-ERROR", error=str(e)[:500])
            raise HTTPException(
                status_code=500,
                detail=f"Failed to mirror and update manifest: {str(e)}"
            )
    else:
        _dbg("SC-MIRROR-SKIP", reason="missing_params", owner=owner, repo=repo, sc_repo_name=sc_repo_name)

    # Step 1: 이미지 정보 구성 (빌드는 이미 webhook handler에서 완료됨)
    # mirror_and_update_manifest에서 이미 매니페스트에 실제 이미지 태그가 설정됨
    _dbg("SB-BUILD-SKIP", reason="already_built_in_webhook", effective_tag=effective_tag)

    # Get build_project_id from DB for history recording
    build_project_id = None
    if db is not None and user_id is not None and owner and repo:
        try:
            integ_existing = get_integration(db, user_id=user_id, owner=owner, repo=repo)
            if integ_existing and getattr(integ_existing, 'build_project_id', None):
                build_project_id = str(getattr(integ_existing, 'build_project_id'))
                _dbg("SB-PROJECT-ID-FROM-DB", build_project_id=build_project_id)
        except Exception:
            pass

    # Compose image info for downstream deploy (without actually building)
    registry = getattr(settings, "ncp_container_registry_url", None)
    if registry and owner and repo:
        def _norm_part_fb(s: str | None) -> str:
            raw = (s or "").lower()
            return "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in raw) or "app"
        image_name_fb = f"{_norm_part_fb(owner)}-{_norm_part_fb(repo)}"
        deployed_image = f"{registry}/{image_name_fb}:{effective_tag}"
        _dbg("SB-IMAGE-INFO", image=deployed_image, image_tag=effective_tag)
        build_result = {
            "status": "skipped",
            "image": deployed_image,
            "image_tag": effective_tag,
            "reason": "already_built_in_webhook_handler"
        }
    else:
        build_result = {
            "status": "skipped",
            "reason": "already_built_in_webhook_handler"
        }

    # Step 2: SourceDeploy 실행 (환경변수 없이, manifest에 이미 실제 태그 설정됨)
    # Manifest already contains the actual image tag (e.g., registry/owner_repo:v1.2.3)
    # No environment variable substitution needed
    deploy_path = f"/api/v1/project/{deploy_project_id}/stage/{stage_id}/scenario/{scenario_id}/deploy"

    # Deploy with empty body (manifest already has correct image tag)
    deploy_body = {}

    _dbg("SD-DEPLOY", path=deploy_path, manifest_updated=manifest_updated, image_tag=effective_tag)
    data = await _call_ncp_rest_api('POST', base, deploy_path, deploy_body)
    result = data.get('result') if isinstance(data, dict) else None

    # Record deployment history
    deploy_history_id = None
    if db and user_id and owner and repo:
        try:
            from ..models.deployment_history import DeploymentHistory
            from datetime import datetime

            history_record = DeploymentHistory(
                user_id=user_id,
                github_owner=owner,
                github_repo=repo,
                github_commit_sha=effective_tag,  # Store the deployed commit SHA/tag
                github_commit_message=f"Rollback to commit {effective_tag[:7]}" if is_rollback else None,
                sourcecommit_project_id=sc_project_id,
                sourcecommit_repo_name=sc_repo_name,
                sourcebuild_project_id=str(build_project_id) if build_project_id else None,
                sourcedeploy_project_id=deploy_project_id,
                deploy_id=str((result or {}).get('historyId')) if result else None,
                status="running",
                sourcedeploy_status="started",
                image_name=image_repo,
                image_tag=effective_tag,
                image_url=desired_image,
                cluster_id=getattr(settings, 'ncp_nks_cluster_id', None),
                namespace="default",
                started_at=get_kst_now(),
                auto_deploy_enabled=True,
                is_rollback=is_rollback
            )

            db.add(history_record)
            db.commit()
            db.refresh(history_record)
            deploy_history_id = history_record.id

            _dbg("SD-HISTORY-RECORDED", history_id=deploy_history_id, image_tag=effective_tag, commit_sha=effective_tag)

            # 백그라운드에서 배포 상태 폴링 시작 (공식 API 경로 사용)
            # GET /api/v1/project/{projectId}/history
            from .ncp_deployment_status_poller import poll_deployment_status
            asyncio.create_task(
                poll_deployment_status(
                    deploy_history_id=deploy_history_id,
                    deploy_project_id=deploy_project_id,
                    stage_id=str(stage_id)
                )
            )
            _dbg("SD-STATUS-POLLING-STARTED", history_id=deploy_history_id,
                 project_id=deploy_project_id, stage_id=stage_id)

        except Exception as e:
            _dbg("SD-HISTORY-ERROR", error=str(e)[:500])
            # Don't fail deployment if history recording fails
            pass

    return {
        "status": "started",
        "deploy_project_id": deploy_project_id,
        "build_project_id": build_project_id,
        "build_result": build_result,
        "code_mirrored": owner is not None and repo is not None and sc_repo_name is not None,
        "manifest_updated": manifest_updated,  # True if manifest was updated during mirroring
        "uses_env_var": False,  # No longer using environment variable approach
        "image": desired_image,
        "deploy_history_id": deploy_history_id,
        "response": (result or {}).get('historyId') or data
    }

# Helper: compose NCR image repo path using repo + optional build_project_id digits
def _compose_image_repo(
    registry: str | None,
    owner: str | None,
    repo: str | None,
    *,
    build_project_id: int | str | None = None,
) -> tuple[str | None, str]:
    """Compose NCR-safe image repo.

    Policy:
    - Use unified <owner>_<repo> (hyphen→underscore), lowercase only (registry rules).
    - No hyphens allowed in image name.
    - Ignore build_project_id for naming to keep stable repo path.
    Returns: (image_repo or None, strategy)
    """
    if not owner or not repo:
        # Fallback for missing owner/repo
        return (None, "missing_params")

    reg = (registry or "").strip()
    registry_host = reg

    # Use centralized naming function
    image_name = _generate_ncr_image_name(owner, repo)

    image_repo = (f"{registry_host}/{image_name}" if registry_host else image_name)
    return (image_repo if image_repo else None), "owner_repo_underscore"

# Export _dbg function for use in other modules
__all__ = [
    "ensure_sourcecommit_repo",
    "create_sourcebuild_project_rest",
    "create_sourcedeploy_project_rest",
    "create_split_build_deploy_pipeline",
    "run_sourcebuild",
    "run_sourcedeploy",
    "ensure_sourcedeploy_project",
    "mirror_to_sourcecommit",
    "update_sourcecommit_manifest",
    "_dbg",
    "_compose_image_repo",
]