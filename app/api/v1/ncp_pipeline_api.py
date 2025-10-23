"""
NCP SourcePipeline API endpoints for managing CI/CD pipelines.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from ...database import get_db
from ...services.ncp_pipeline import (
    create_split_build_deploy_pipeline,
    execute_sourcepipeline_rest,
    get_sourcepipeline_history_detail
)
from ...services.user_project_integration import get_integration

router = APIRouter()


# --- Request/Response Models ---

class CreatePipelineRequest(BaseModel):
    """Request model for creating a full CI/CD pipeline."""
    owner: str = Field(..., description="GitHub repository owner")
    repo: str = Field(..., description="GitHub repository name")
    branch: str = Field(default="main", description="Git branch to trigger on")
    user_id: str = Field(..., description="User ID for database storage")
    sc_project_id: Optional[str] = Field(default=None, description="SourceCommit project ID (optional)")
    sc_repo_name: Optional[str] = Field(default=None, description="SourceCommit repository name (optional)")


class CreatePipelineResponse(BaseModel):
    """Response model for pipeline creation."""
    status: str
    build_project_id: str
    deploy_project_id: str
    pipeline_id: str
    image_repo: str
    message: str


class ExecutePipelineRequest(BaseModel):
    """Request model for executing a pipeline."""
    pipeline_id: str = Field(..., description="Pipeline project ID to execute")


class ExecutePipelineResponse(BaseModel):
    """Response model for pipeline execution."""
    status: str
    project_id: str
    history_id: Optional[int]
    message: str


class PipelineStatusResponse(BaseModel):
    """Response model for pipeline status."""
    pipeline_id: Optional[str]
    build_project_id: Optional[str]
    deploy_project_id: Optional[str]
    sc_repo_name: Optional[str]
    branch: Optional[str]
    auto_deploy_enabled: bool
    message: str


# --- API Endpoints ---

@router.post("/create", response_model=CreatePipelineResponse)
async def create_pipeline(
    request: CreatePipelineRequest,
    db: Session = Depends(get_db)
):
    """
    Create a complete CI/CD pipeline including:
    - SourceCommit repository (mirror from GitHub)
    - SourceBuild project (Docker image build)
    - SourceDeploy project (NKS deployment)
    - SourcePipeline project (Build → Deploy automation)

    All IDs are saved to the database for future reference.

    **Example:**
    ```json
    {
      "owner": "myorg",
      "repo": "myrepo",
      "branch": "main",
      "user_id": "user123"
    }
    ```
    """
    try:
        result = await create_split_build_deploy_pipeline(
            pipeline_name=f"pipeline-{request.owner}-{request.repo}",
            owner=request.owner,
            repo=request.repo,
            branch=request.branch,
            sc_project_id=request.sc_project_id,
            sc_repo_name=request.sc_repo_name,
            db=db,
            user_id=request.user_id
        )

        return CreatePipelineResponse(
            status=result.get("status", "created"),
            build_project_id=result.get("build_project_id", ""),
            deploy_project_id=result.get("deploy_project_id", ""),
            pipeline_id=result.get("pipeline_id", ""),
            image_repo=result.get("image_repo", ""),
            message=f"Full CI/CD pipeline created for {request.owner}/{request.repo}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline creation failed: {str(e)}")


@router.post("/execute", response_model=ExecutePipelineResponse)
async def execute_pipeline(request: ExecutePipelineRequest):
    """
    Manually trigger a pipeline execution.

    This will:
    1. Run SourceBuild to build Docker image
    2. Run SourceDeploy to deploy to NKS cluster

    **Example:**
    ```json
    {
      "pipeline_id": "12345"
    }
    ```
    """
    try:
        result = await execute_sourcepipeline_rest(request.pipeline_id)

        return ExecutePipelineResponse(
            status=result.get("status", "started"),
            project_id=result.get("project_id", request.pipeline_id),
            history_id=result.get("history_id"),
            message=f"Pipeline execution started (history_id: {result.get('history_id')})"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")


@router.get("/history/{pipeline_id}/{history_id}")
async def get_pipeline_history(
    pipeline_id: str,
    history_id: int
):
    """
    Get detailed execution history of a pipeline run.

    Returns:
    - Execution status (InProgress, success, failed, stopped)
    - Task-level status for Build and Deploy
    - Timestamps and error details if any

    **Example:**
    ```
    GET /api/v1/ncp/pipeline/history/12345/67890
    ```
    """
    try:
        result = await get_sourcepipeline_history_detail(pipeline_id, history_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get pipeline history: {str(e)}")


@router.get("/status/{owner}/{repo}", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    owner: str,
    repo: str,
    user_id: str = Query(..., description="User ID"),
    db: Session = Depends(get_db)
):
    """
    Get the current pipeline configuration for a repository.

    Returns the stored IDs for SourceCommit, SourceBuild, SourceDeploy, and SourcePipeline.

    **Example:**
    ```
    GET /api/v1/ncp/pipeline/status/myorg/myrepo?user_id=user123
    ```
    """
    try:
        integration = get_integration(db, user_id=user_id, owner=owner, repo=repo)

        if not integration:
            return PipelineStatusResponse(
                pipeline_id=None,
                build_project_id=None,
                deploy_project_id=None,
                sc_repo_name=None,
                branch=None,
                auto_deploy_enabled=False,
                message=f"No pipeline found for {owner}/{repo}"
            )

        return PipelineStatusResponse(
            pipeline_id=getattr(integration, 'pipeline_id', None),
            build_project_id=getattr(integration, 'build_project_id', None),
            deploy_project_id=getattr(integration, 'deploy_project_id', None),
            sc_repo_name=getattr(integration, 'sc_repo_name', None),
            branch=getattr(integration, 'branch', 'main'),
            auto_deploy_enabled=getattr(integration, 'auto_deploy_enabled', False),
            message=f"Pipeline configuration for {owner}/{repo}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get pipeline status: {str(e)}")


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: str):
    """
    Delete a pipeline project (future implementation).

    Currently returns 501 Not Implemented.
    """
    raise HTTPException(status_code=501, detail="Pipeline deletion not yet implemented")


# Health check endpoint for the pipeline API
@router.get("/health")
async def health_check():
    """Health check endpoint for NCP Pipeline API."""
    return {
        "status": "healthy",
        "service": "ncp-pipeline-api",
        "endpoints": [
            "POST /create",
            "POST /execute",
            "GET /history/{pipeline_id}/{history_id}",
            "GET /status/{owner}/{repo}",
            "GET /health"
        ]
    }
