from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from .registry import mcp_registry, MCPProviderConfig
from .errors import MCPExternalError


router = APIRouter(prefix="/mcp/external", tags=["MCP External"])


class ToolCallRequest(BaseModel):
    """Request model for tool calls."""
    provider: str
    tool_name: str
    arguments: Dict[str, Any]


class ToolCallResponse(BaseModel):
    """Response model for tool calls."""
    ok: bool
    content: Any
    error: Optional[str] = None


class ListToolsResponse(BaseModel):
    """Response model for listing tools."""
    provider: str
    tools: List[Dict[str, Any]]


class HealthCheckResponse(BaseModel):
    """Response model for health checks."""
    provider: str
    ok: bool
    connected: bool
    server_status: Optional[str] = None
    error: Optional[str] = None


class ProviderConfigRequest(BaseModel):
    """Request model for provider configuration."""
    name: str
    provider_type: str
    base_url: str
    config: Dict[str, Any]
    enabled: bool = True


@router.post("/providers", response_model=Dict[str, str])
async def add_provider_config(request: ProviderConfigRequest):
    """Add a new MCP provider configuration."""
    try:
        config = MCPProviderConfig(
            name=request.name,
            provider_type=request.provider_type,
            base_url=request.base_url,
            config=request.config,
            enabled=request.enabled
        )
        mcp_registry.add_provider_config(config)
        return {"message": f"Provider {request.name} configured successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/providers", response_model=List[str])
async def list_providers():
    """List all configured MCP providers."""
    return mcp_registry.list_providers()


@router.post("/providers/{provider_name}/initialize", response_model=Dict[str, str])
async def initialize_provider(provider_name: str):
    """Initialize a specific MCP provider."""
    try:
        success = await mcp_registry.initialize_provider(provider_name)
        if success:
            return {"message": f"Provider {provider_name} initialized successfully"}
        else:
            raise HTTPException(status_code=400, detail=f"Failed to initialize provider {provider_name}")
    except MCPExternalError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/initialize-all", response_model=Dict[str, bool])
async def initialize_all_providers():
    """Initialize all configured MCP providers."""
    try:
        results = await mcp_registry.initialize_all_providers()
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    """Call a tool on a specific MCP provider."""
    try:
        result = await mcp_registry.call_tool(
            request.provider,
            request.tool_name,
            request.arguments
        )
        return ToolCallResponse(
            ok=result.get("ok", True),
            content=result.get("content", result)
        )
    except MCPExternalError as e:
        return ToolCallResponse(
            ok=False,
            content=None,
            error=e.message
        )
    except Exception as e:
        return ToolCallResponse(
            ok=False,
            content=None,
            error=str(e)
        )


@router.get("/tools/{provider_name}", response_model=ListToolsResponse)
async def list_tools(provider_name: str):
    """List tools for a specific MCP provider."""
    try:
        tools = await mcp_registry.list_tools(provider_name)
        return ListToolsResponse(
            provider=provider_name,
            tools=tools
        )
    except MCPExternalError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/{provider_name}", response_model=HealthCheckResponse)
async def health_check(provider_name: str):
    """Check health of a specific MCP provider."""
    try:
        health = await mcp_registry.health_check(provider_name)
        return HealthCheckResponse(
            provider=provider_name,
            ok=health.get("ok", True),
            connected=health.get("connected", False),
            server_status=health.get("server_status"),
            error=health.get("error")
        )
    except MCPExternalError as e:
        return HealthCheckResponse(
            provider=provider_name,
            ok=False,
            connected=False,
            error=e.message
        )
    except Exception as e:
        return HealthCheckResponse(
            provider=provider_name,
            ok=False,
            connected=False,
            error=str(e)
        )


@router.get("/health", response_model=Dict[str, Dict[str, Any]])
async def health_check_all():
    """Check health of all MCP providers."""
    try:
        return await mcp_registry.health_check_all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", response_model=Dict[str, str])
async def cleanup_all_providers():
    """Cleanup all MCP providers."""
    try:
        await mcp_registry.cleanup_all_providers()
        return {"message": "All providers cleaned up successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

