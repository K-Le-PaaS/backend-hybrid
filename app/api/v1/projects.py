"""
프로젝트 온보딩 엔드포인트: repo clone → build → NCP pipeline 생성
"""

from typing import Dict, Any
from pathlib import Path
import uuid

from fastapi import APIRouter, HTTPException, Depends, Request, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ...database import get_db
from ...models.oauth_token import OAuthToken
from ...services.github_app import github_app_auth
from ...services.user_repository import get_user_repositories
from ...core.config import get_settings
import hmac, hashlib, json
from ..v1.auth_verify import get_current_user
from ...services.ncp_pipeline import (
    clone_repository,
    build_and_push_image_with_buildpack,
    create_ncp_pipeline_resource,
    mirror_to_sourcecommit,
    ensure_sourcecommit_repo,
    run_sourcebuild,
    run_sourcedeploy,
    create_split_build_deploy_pipeline,
)
from ...services.user_project_integration import (
    upsert_integration,
    get_integration,
    get_integration_by_installation,
)
import structlog


router = APIRouter(prefix="/projects", tags=["projects"])
settings = get_settings()


class OnboardRequest(BaseModel):
    repo_url: str
    app_name: str
    branch: str | None = "main"


@router.post("/onboard")
async def onboard_project(
    req: OnboardRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    # 인증 가정: 간단히 user_id를 repo 소유자 또는 외부에서 전달받는다고 가정
    # 여기서는 토큰 테이블에 저장된 임의 첫번째 GitHub 토큰을 사용 (데모 목적)
    # 우선 UserRepository에서 해당 repo의 installation_id가 있으면 App 설치 토큰 사용
    installation_id: str | None = None
    repos = await get_user_repositories(db, str(current_user["id"]))
    for r in repos:
        if r.get("fullName") and r["fullName"].lower() in (req.repo_url.lower(), req.repo_url.split("github.com/")[-1].lower()):
            installation_id = r.get("installation_id")
            break

    access_token: str | None = None
    if installation_id:
        access_token = await github_app_auth.get_installation_token(str(installation_id))
    else:
        # 폴백: 과거 저장된 사용자 토큰이 있으면 사용(가능하면 App 설치를 유도)
        token_row = (
            db.query(OAuthToken)
            .filter(OAuthToken.provider == "github", OAuthToken.user_id == str(current_user["id"]))
            .first()
        )
        if not token_row:
            raise HTTPException(status_code=401, detail="GitHub App 설치가 필요합니다 (또는 사용자 토큰 없음)")
        access_token = token_row.access_token

    # 1) clone
    work_dir = Path("/tmp") / f"onboard-{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    clone_repository(req.repo_url, str(work_dir), req.branch or "main", access_token)

    # 2) build & push (image name convention: registry/app:tag)
    image_name = f"{req.app_name}:latest"
    build_and_push_image_with_buildpack(str(work_dir), image_name, "latest")

    # 3) NCP pipeline create
    pipeline = create_ncp_pipeline_resource(req.app_name, image_name)

    return {
        "status": "success",
        "app": req.app_name,
        "image": image_name,
        "pipeline": pipeline,
    }


class MirrorToSCRequest(BaseModel):
    repo_url: str
    project_id: str
    repo_name: str
    sc_username: str | None = None
    sc_password: str | None = None
    installation_id: str | None = None
    sc_full_url: str | None = None


@router.post("/sourcecommit/create-and-link")
async def create_and_link_sourcecommit(
    req: MirrorToSCRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    # Resolve installation token if possible (explicit > lookup)
    installation_id: str | None = req.installation_id
    if not installation_id:
        repos = await get_user_repositories(db, str(current_user["id"]))
        for r in repos:
            full = r.get("fullName")
            if full and (full.lower() in (req.repo_url.lower(), req.repo_url.split("github.com/")[-1].lower())):
                installation_id = r.get("installation_id")
                break

    token: str | None = None
    if installation_id:
        token = await github_app_auth.get_installation_token(str(installation_id))
    else:
        # fallback to user token if necessary
        row = (
            db.query(OAuthToken)
            .filter(OAuthToken.provider == "github", OAuthToken.user_id == str(current_user["id"]))
            .first()
        )
        if not row:
            raise HTTPException(status_code=401, detail="GitHub App 설치 또는 사용자 토큰 필요")
        token = row.access_token

    # Parse owner/repo from URL for DB upsert
    tail = req.repo_url.split("github.com/")[-1].rstrip("/")
    owner = tail.split("/")[0]
    repo_name = tail.split("/")[1].replace('.git','') if '/' in tail else tail

    # Persist known values to DB first (fail fast if DB error)
    from ...services.user_project_integration import upsert_integration
    integ_first = upsert_integration(
        db=db,
        user_id=str(current_user["id"]),
        owner=owner,
        repo=repo_name,
        repository_id=None,
        installation_id=str(installation_id) if installation_id else None,
        sc_project_id=req.project_id,
        sc_repo_name=req.repo_name,
    )

    # Ensure Repository exists in SourceCommit (best-effort)
    _ = ensure_sourcecommit_repo(req.project_id, req.repo_name)

    result = mirror_to_sourcecommit(
        github_repo_url=req.repo_url,
        installation_or_access_token=token,
        sc_project_id=req.project_id,
        sc_repo_name=req.repo_name,
        sc_username=req.sc_username,
        sc_password=req.sc_password,
        sc_full_url=req.sc_full_url,
    )

    # Persist integration details to DB (DB-first contract)
    # Final normalization: ensure integration reflects latest values
    try:
        integ = upsert_integration(
            db=db,
            user_id=str(current_user["id"]),
            owner=owner,
            repo=repo_name,
            installation_id=str(installation_id) if installation_id else None,
            sc_project_id=req.project_id,
            sc_repo_name=req.repo_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to upsert integration: {e}")

    return {"status": "success", "mirror": result, "integration": {
        "owner": getattr(integ, 'github_owner', None) if integ else owner,
        "repo": getattr(integ, 'github_repo', None) if integ else repo_name,
        "sc_project_id": getattr(integ, 'sc_project_id', None) if integ else req.project_id,
        "sc_repo_name": getattr(integ, 'sc_repo_name', None) if integ else req.repo_name,
        "github_installation_id": getattr(integ, 'github_installation_id', None) if integ else (str(installation_id) if installation_id else None),
    }}


class CreateSplitPipelineRequest(BaseModel):
    pipeline_name: str
    owner: str
    repo: str
    branch: str = "main"
    sc_project_id: str | None = None
    sc_repo_name: str | None = None


@router.post("/pipelines/split/create")
async def create_split_pipeline(req: CreateSplitPipelineRequest, db: Session = Depends(get_db), current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return await create_split_build_deploy_pipeline(
        pipeline_name=req.pipeline_name,
        owner=req.owner,
        repo=req.repo,
        branch=req.branch,
        sc_project_id=req.sc_project_id,
        sc_repo_name=req.sc_repo_name,
        db=db,
        user_id=str(current_user["id"]),
    )

# GitHub push webhook → mirror to SourceCommit and optionally trigger pipeline
@router.post("/webhooks/github/push")
async def github_push_webhook(
    request: Request,
    db: Session = Depends(get_db),
    pipeline_id: str | None = Query(None, description="Optional SourcePipeline id to run after mirror"),
) -> Dict[str, Any]:
    secret = (settings.github_webhook_secret or "").encode("utf-8")
    body_bytes = await request.body()
    if secret:
        theirs = request.headers.get("X-Hub-Signature-256", "")
        mac = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
        if not theirs.endswith(mac):
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid payload")

    repo = payload.get("repository", {})
    repo_url = repo.get("html_url") or repo.get("clone_url")
    full_name = repo.get("full_name")  # owner/repo
    installation_id = payload.get("installation", {}).get("id")
    if not repo_url or not installation_id or not full_name:
        raise HTTPException(status_code=400, detail="missing repository url or installation id")

    token = await github_app_auth.get_installation_token(str(installation_id))

    owner, repo_name = full_name.split("/", 1)

    # 1) 통합정보 조회 (없으면 최소한의 정보로 레코드 생성만 하고 SourceCommit 미존재 처리)
    integ = get_integration_by_installation(db, installation_id=str(installation_id), owner=owner, repo=repo_name)
    if not integ:
        # 초기 연결이 필요함을 알림 (SourceCommit project/repo 정보를 알 수 없으므로 생성 단계 필요)
        upsert_integration(
            db,
            user_id="unknown",
            owner=owner,
            repo=repo_name,
            installation_id=str(installation_id),
        )
        raise HTTPException(status_code=409, detail="initial link required: call /projects/sourcecommit/create-and-link and /projects/pipelines/split/create")

    if not integ.sc_project_id or not integ.sc_repo_name:
        raise HTTPException(status_code=409, detail="sourcecommit mapping missing: call create-and-link first")

    # 🔧 추가: auto_deploy_enabled 상태 확인
    if not getattr(integ, 'auto_deploy_enabled', False):
        return {
            "status": "skipped", 
            "reason": "auto_deploy_disabled",
            "repository": full_name,
            "message": "Auto deploy is disabled for this repository"
        }

    # 2) SourceCommit 확인 및 미러링
    ensure = ensure_sourcecommit_repo(integ.sc_project_id, integ.sc_repo_name)
    if ensure.get("status") not in ("created", "exists"):
        raise HTTPException(status_code=400, detail={"sourcecommit_create": ensure})

    mirror = mirror_to_sourcecommit(
        github_repo_url=repo_url,
        installation_or_access_token=token,
        sc_project_id=integ.sc_project_id,
        sc_repo_name=integ.sc_repo_name,
    )

    # 3) Build/Deploy 리소스 없으면 생성
    created_pipeline: Dict[str, Any] | None = None
    if not integ.build_project_id or not integ.deploy_project_id:
        created_pipeline = create_split_build_deploy_pipeline(
            pipeline_name=f"pl-{owner}-{repo_name}",
            owner=owner,
            repo=repo_name,
            branch=integ.branch or "main",
        )
        upsert_integration(
            db,
            user_id=integ.user_id,
            owner=owner,
            repo=repo_name,
            build_project_id=str(created_pipeline.get("build_project_id", "")),
            deploy_project_id=str(created_pipeline.get("deploy_project_id", "")),
            pipeline_id=str(created_pipeline.get("pipeline_id", "")),
        )

    # 4) 실행
    run_results: Dict[str, Any] = {}
    try:
        # Extract commit SHA from webhook payload
        commit_sha = payload.get("after")[:7] if payload.get("after") else None

        build_id = integ.build_project_id or (created_pipeline or {}).get("build_project_id")
        if build_id:
            # Construct image_repo from settings for build execution
            registry = getattr(settings, "ncp_container_registry_url", None)
            if registry:
                image_repo = f"{registry}/{owner}-{repo_name}"
                run_results["build"] = await run_sourcebuild(
                    str(build_id),
                    image_repo=image_repo,
                    commit_sha=commit_sha,  # Pass commit SHA for tagging
                    sc_project_id=integ.sc_project_id,
                    sc_repo_name=integ.sc_repo_name,
                    branch=integ.branch or "main"
                )
            else:
                run_results["build"] = await run_sourcebuild(
                    str(build_id),
                    commit_sha=commit_sha,
                    sc_project_id=integ.sc_project_id,
                    sc_repo_name=integ.sc_repo_name,
                    branch=integ.branch or "main"
                )
        deploy_id = integ.deploy_project_id or (created_pipeline or {}).get("deploy_project_id")
        if deploy_id:
            # Pass commit SHA and other context to deploy for manifest update
            run_results["deploy"] = await run_sourcedeploy(
                str(deploy_id),
                sc_project_id=integ.sc_project_id,
                db=db,
                user_id=integ.user_id,
                owner=owner,
                repo=repo_name,
                tag=commit_sha  # Use commit SHA as deployment tag
            )
    except Exception as e:
        run_results["error"] = str(e)

    # 5) (선택) 파이프라인 실행
    pipeline_run: Dict[str, Any] | None = None
    try:
        from ...services.ncp_pipeline import run_sourcepipeline
        pl_id = pipeline_id or integ.pipeline_id or (created_pipeline or {}).get("pipeline_id")
        if pl_id:
            pipeline_run = run_sourcepipeline(str(pl_id))
    except Exception:
        pipeline_run = {"status": "skipped"}

    return {"status": "ok", "ensure": ensure, "mirror": mirror, "runs": run_results, "pipeline_run": pipeline_run}


class RunBuildRequest(BaseModel):
    build_project_id: str | None = None
    owner: str | None = None
    repo: str | None = None


@router.post("/build/run")
async def run_build(req: RunBuildRequest, db: Session = Depends(get_db), current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    from ...services.ncp_pipeline import ensure_sourcebuild_project, run_sourcebuild as run_sb

    # If only build_project_id provided, construct image_repo from settings
    if req.build_project_id:
        # Need owner/repo to construct image_repo, so require them even when build_project_id is provided
        if not (req.owner and req.repo):
            raise HTTPException(status_code=400, detail="owner/repo required to construct image_repo")
        registry = getattr(settings, "ncp_container_registry_url", None)
        if not registry:
            raise HTTPException(status_code=500, detail="ncp_container_registry_url not configured")
        image_repo = f"{registry}/{req.owner}-{req.repo}"

        # Get integration to pass SourceCommit info for Dockerfile verification
        integ = get_integration(db, user_id=str(current_user["id"]), owner=req.owner, repo=req.repo)
        sc_project_id = getattr(integ, "sc_project_id", None) if integ else None
        sc_repo_name = getattr(integ, "sc_repo_name", None) if integ else None
        branch = getattr(integ, "branch", None) or "main"

        return await run_sb(req.build_project_id, image_repo=image_repo, sc_project_id=sc_project_id, sc_repo_name=sc_repo_name, branch=branch)

    if not (req.owner and req.repo):
        raise HTTPException(status_code=400, detail="owner/repo or build_project_id required")

    # Construct image_repo from settings
    registry = getattr(settings, "ncp_container_registry_url", None)
    if not registry:
        raise HTTPException(status_code=500, detail="ncp_container_registry_url not configured")
    image_repo = f"{registry}/{req.owner}-{req.repo}"

    # Ensure SourceBuild exists and persist to DB (use SourceCommit mapping from integration)
    integ = get_integration(db, user_id=str(current_user["id"]), owner=req.owner, repo=req.repo)
    sc_project_id = getattr(integ, "sc_project_id", None) if integ else None
    sc_repo_name = getattr(integ, "sc_repo_name", None) if integ else None
    branch = getattr(integ, "branch", None) or "main"
    build_id = await ensure_sourcebuild_project(
        owner=req.owner,
        repo=req.repo,
        branch=branch,
        sc_project_id=sc_project_id,
        sc_repo_name=sc_repo_name,
        db=db,
        user_id=str(current_user["id"])  # type: ignore
    )
    return await run_sb(build_id, image_repo=image_repo)


class RunDeployRequest(BaseModel):
    deploy_project_id: str | None = None
    owner: str | None = None
    repo: str | None = None
    stage_name: str | None = "production"
    scenario_name: str | None = "deploy-app"
    tag: str | None = None  # Image tag (e.g., commit SHA) to deploy


@router.post("/deploy/run")
async def run_deploy(req: RunDeployRequest, db: Session = Depends(get_db), current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    # Do not override deploy project id; ensure and run via service layer
    from ...services.ncp_pipeline import ensure_sourcedeploy_project, run_sourcedeploy, _dbg
    if not req.owner or not req.repo:
        raise HTTPException(status_code=400, detail="owner/repo is required")
    # Build minimal inline manifest used when creating SourceDeploy project if missing
    registry = getattr(settings, "ncp_container_registry_url", None)
    image_repo = f"{registry}/{req.owner}-{req.repo}" if registry else f"{req.owner}-{req.repo}"
    manifest_text = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {req.repo}-deploy
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {req.repo}
  template:
    metadata:
      labels:
        app: {req.repo}
    spec:
      containers:
      - name: {req.repo}
        image: {image_repo}:${{GIT_COMMIT}}
        ports:
        - containerPort: 80
""".strip()
    nks_cluster_id = getattr(settings, "ncp_nks_cluster_id", None)
    # Resolve integration to obtain SourceCommit project id for scenario schema
    integ = get_integration(db, user_id=str(current_user["id"]), owner=req.owner, repo=req.repo)
    deploy_project_id = await ensure_sourcedeploy_project(
        owner=req.owner,
        repo=req.repo,
        manifest_text=manifest_text,
        nks_cluster_id=nks_cluster_id,
        db=db,
        user_id=str(current_user["id"]),
    )
    _dbg("SD-PROJECT-ENSURED", id=deploy_project_id)
    return await run_sourcedeploy(
        deploy_project_id,
        stage_name=req.stage_name or "production",
        scenario_name=req.scenario_name or "deploy-app",
        sc_project_id=getattr(integ, "sc_project_id", None) if integ else None,
        db=db,
        user_id=str(current_user["id"]),
        owner=req.owner,
        repo=req.repo,
        tag=req.tag,  # Pass tag parameter
    )


# List current user's project integrations
from sqlalchemy import or_, and_, func, cast, String

@router.get("/integrations")
async def list_project_integrations(db: Session = Depends(get_db), current_user: Dict[str, Any] = Depends(get_current_user)) -> Any:
    from ...models.user_project_integration import UserProjectIntegration
    # 임시 진단: DB 바인딩 및 원시 카운트 로그
    try:
        engine = db.get_bind()
        db_url = str(getattr(engine, 'url', 'unknown'))
    except Exception:
        db_url = 'unknown'
    try:
        raw = db.execute("SELECT id, user_id, github_full_name FROM user_project_integrations ORDER BY id")
        raw_rows = raw.fetchall()
        import structlog
        structlog.get_logger(__name__).info("integrations_db_probe", db_url=db_url, raw_count=len(raw_rows), raw_rows=[tuple(r) for r in raw_rows])
    except Exception:
        pass

    # 임시 진단: RAW로 직접 반환 (ORM 캐시/세션 문제 우회)
    raw_maps = db.execute(text("SELECT * FROM user_project_integrations ORDER BY id")).mappings().all()
    raw_count = len(raw_maps)

    def row_to_dict(r: Any) -> Dict[str, Any]:
        return {
            "id": r.id,
            "user_id": r.user_id,
            "user_email": getattr(r, "user_email", None),
            "owner": getattr(r, "github_owner", None) or getattr(r, "owner", None),
            "repo": getattr(r, "github_repo", None) or getattr(r, "repo", None),
            "github_full_name": getattr(r, "github_full_name", None) or (f"{getattr(r, 'github_owner', '')}/{getattr(r, 'github_repo', '')}" if getattr(r, 'github_owner', None) and getattr(r, 'github_repo', None) else None),
            "github_installation_id": getattr(r, "github_installation_id", None),
            "github_webhook_secret": getattr(r, "github_webhook_secret", None),
            "sc_project_id": getattr(r, "sc_project_id", None),
            "sc_repo_name": getattr(r, "sc_repo_name", None),
            "sc_clone_url": getattr(r, "sc_clone_url", None),
            "build_project_id": getattr(r, "build_project_id", None),
            "deploy_project_id": getattr(r, "deploy_project_id", None),
            "pipeline_id": getattr(r, "pipeline_id", None),
            "registry_url": getattr(r, "registry_url", None),
            "image_repository": getattr(r, "image_repository", None),
            "branch": getattr(r, "branch", None),
            "auto_deploy_enabled": getattr(r, "auto_deploy_enabled", False),
            "created_at": getattr(r, "created_at", None),
            "updated_at": getattr(r, "updated_at", None),
        }
    return [dict(r) for r in raw_maps]


@router.post("/github/connect")
async def connect_github_repository(
    req: MirrorToSCRequest,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """GitHub 레포지토리 연동 (NCP 연동 없이)"""
    # Parse owner/repo from URL
    tail = req.repo_url.split("github.com/")[-1].rstrip("/")
    owner = tail.split("/")[0]
    repo_name = tail.split("/")[1].replace('.git','') if '/' in tail else tail
    
    # GitHub App 설치 상태를 확인 (DB 우선 + API 폴백)
    try:
        # DB에서 먼저 조회하고, 없으면 GitHub API로 실시간 조회
        token, installation_id = await github_app_auth.get_installation_token_for_repo(owner, repo_name, db)
    except Exception as e:
        # GitHub App이 설치되지 않은 경우
        raise HTTPException(
            status_code=401, 
            detail=f"GitHub App이 레포지토리 '{owner}/{repo_name}'에 설치되지 않았습니다. GitHub App을 설치해주세요."
        )

    # GitHub 연동 정보를 DB에 저장 (user_project_integration 테이블 사용)
    integration = upsert_integration(
        db=db,
        user_id=str(current_user["id"]),
        user_email=current_user.get("email"),
        owner=owner,
        repo=repo_name,
        repository_id=None,
        installation_id=installation_id,  # GitHub App 설치 ID 저장
        sc_project_id=None,    # NCP 연동은 별도
        sc_repo_name=None,
    )

    return {
        "status": "success",
        "message": "GitHub 레포지토리가 성공적으로 연동되었습니다.",
        "repository": {
            "owner": owner,
            "repo": repo_name,
            "url": req.repo_url
        },
        "integration_id": integration.id
    }

