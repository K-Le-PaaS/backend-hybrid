from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.github_workflow import create_or_update_workflow, DEFAULT_CI_YAML


router = APIRouter()


class InstallWorkflowRequest(BaseModel):
    owner: str = Field(..., description="GitHub owner/organization")
    repo: str = Field(..., description="Repository name")
    installation_id: str = Field(..., description="GitHub App installation ID")
    branch: Optional[str] = Field(None, description="Target branch (use when default is protected)")
    path: str = Field(default=".github/workflows/ci.yml", description="Workflow file path")
    yaml_content: Optional[str] = Field(None, description="Custom workflow YAML (defaults to standard CI)")
    commit_message: str = Field(default="chore: add or update CI workflow")
    author_name: Optional[str] = None
    author_email: Optional[str] = None


@router.post("/github/workflows/install", response_model=Dict[str, Any])
async def install_default_workflow(body: InstallWorkflowRequest) -> Dict[str, Any]:
    try:
        result = await create_or_update_workflow(
            owner=body.owner,
            repo=body.repo,
            installation_id=body.installation_id,
            branch=body.branch,
            path=body.path,
            yaml_content=body.yaml_content or DEFAULT_CI_YAML,
            commit_message=body.commit_message,
            author_name=body.author_name,
            author_email=body.author_email,
        )
        if result.get("status") != "success":
            raise HTTPException(status_code=400, detail=f"Workflow installation failed: {result}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


