"""
Git 자동배포 MCP 도구 (FastAPI 통합 버전)
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# from fastmcp.tools import Tool  # Will be registered via @server.tool decorator

from ..external.registry import mcp_registry

logger = logging.getLogger(__name__)


async def deploy_application_mcp(
    app_name: str,
    environment: str,
    image: str,
    cloud_provider: str,
    replicas: int = 2,
    namespace: str = "default",
    port: int = 8080,
    env_vars: Optional[Dict[str, str]] = None,
    resources: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Deploy application using MCP native Git agents"""
    try:
        # 클라우드 프로바이더별 에이전트 선택
        agent_name = f"{cloud_provider}-git-agent"
        
        # MCP 에이전트 호출
        tool_name = f"deploy_to_{cloud_provider}"
        tool_args = {
            "app_name": app_name,
            "environment": environment,
            "image": image,
            "replicas": replicas,
            "namespace": namespace,
            "port": port,
            "env_vars": env_vars or {},
            "resources": resources or {}
        }
        
        result = await mcp_registry.call_tool(agent_name, tool_name, tool_args)
        
        return {
            "status": "success",
            "action": "deploy",
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "agent_result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"MCP deployment failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider
        }


async def rollback_deployment_mcp(
    app_name: str,
    environment: str,
    cloud_provider: str,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Rollback deployment using MCP native Git agents"""
    try:
        # 클라우드 프로바이더별 에이전트 선택
        agent_name = f"{cloud_provider}-git-agent"
        
        # MCP 에이전트 호출
        tool_name = f"rollback_{cloud_provider}_deployment"
        tool_args = {
            "app_name": app_name,
            "environment": environment,
            "namespace": namespace
        }
        
        result = await mcp_registry.call_tool(agent_name, tool_name, tool_args)
        
        return {
            "status": "success",
            "action": "rollback",
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "agent_result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"MCP rollback failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider
        }


async def get_deployment_status_mcp(
    app_name: str,
    environment: str,
    cloud_provider: str,
    namespace: str = "default"
) -> Dict[str, Any]:
    """Get deployment status using MCP native Git agents"""
    try:
        # 클라우드 프로바이더별 에이전트 선택
        agent_name = f"{cloud_provider}-git-agent"
        
        # MCP 에이전트 호출
        tool_name = f"get_{cloud_provider}_deployment_status"
        tool_args = {
            "app_name": app_name,
            "environment": environment,
            "namespace": namespace
        }
        
        result = await mcp_registry.call_tool(agent_name, tool_name, tool_args)
        
        return {
            "status": "success",
            "action": "status_check",
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "agent_result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"MCP status check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "app_name": app_name,
            "environment": environment,
            "cloud_provider": cloud_provider
        }


async def git_workflow_automation(
    repository_url: str,
    environment: str,
    cloud_provider: str,
    app_name: str,
    branch: str = "main",
    dockerfile_path: str = "Dockerfile",
    build_args: Optional[Dict[str, Any]] = None,
    auto_deploy: bool = True
) -> Dict[str, Any]:
    """Execute Git workflow automation (clone, build, deploy)"""
    try:
        agent_name = f"{cloud_provider}-git-agent"
        results = {}
        
        # 1. Git 리포지토리 클론
        clone_result = await mcp_registry.call_tool(agent_name, "git_clone_repository", {
            "repository_url": repository_url,
            "branch": branch
        })
        results["clone"] = clone_result
        
        if clone_result.get("status") != "success":
            raise Exception(f"Git clone failed: {clone_result.get('error')}")
        
        repository_path = clone_result.get("local_path")
        
        # 2. Docker 이미지 빌드 및 푸시
        image_name = app_name
        tag = f"{environment}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        build_result = await mcp_registry.call_tool(agent_name, "build_and_push_image", {
            "repository_path": repository_path,
            "image_name": image_name,
            "tag": tag,
            "dockerfile_path": dockerfile_path,
            **(build_args or {})
        })
        results["build"] = build_result
        
        if build_result.get("status") != "success":
            raise Exception(f"Docker build failed: {build_result.get('error')}")
        
        image = build_result.get("gcr_image") or build_result.get("ncp_image")
        
        # 3. 자동 배포 (옵션)
        if auto_deploy:
            deploy_result = await deploy_application_mcp(
                app_name=app_name,
                environment=environment,
                image=image,
                cloud_provider=cloud_provider
            )
            results["deploy"] = deploy_result
        
        return {
            "status": "success",
            "action": "git_workflow_automation",
            "repository_url": repository_url,
            "branch": branch,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "app_name": app_name,
            "image": image,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Git workflow automation failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "repository_url": repository_url,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "app_name": app_name
        }


async def create_release_tag(
    repository_url: str,
    tag_name: str,
    environment: str,
    cloud_provider: str,
    app_name: str,
    message: Optional[str] = None,
    auto_deploy: bool = True
) -> Dict[str, Any]:
    """Create release tag and trigger production deployment"""
    try:
        agent_name = f"{cloud_provider}-git-agent"
        results = {}
        
        # 1. Git 리포지토리 클론
        clone_result = await mcp_registry.call_tool(agent_name, "git_clone_repository", {
            "repository_url": repository_url,
            "branch": "main"
        })
        results["clone"] = clone_result
        
        if clone_result.get("status") != "success":
            raise Exception(f"Git clone failed: {clone_result.get('error')}")
        
        repository_path = clone_result.get("local_path")
        
        # 2. 릴리스 태그 생성
        tag_result = await mcp_registry.call_tool(agent_name, "git_create_tag", {
            "repository_path": repository_path,
            "tag_name": tag_name,
            "message": message or f"Release {tag_name}",
            "push": True
        })
        results["tag"] = tag_result
        
        if tag_result.get("status") != "success":
            raise Exception(f"Git tag creation failed: {tag_result.get('error')}")
        
        # 3. 자동 배포 (옵션)
        if auto_deploy:
            # 태그 기반 이미지 이름 생성
            image = f"{app_name}:{tag_name}"
            
            deploy_result = await deploy_application_mcp(
                app_name=app_name,
                environment=environment,
                image=image,
                cloud_provider=cloud_provider
            )
            results["deploy"] = deploy_result
        
        return {
            "status": "success",
            "action": "create_release_tag",
            "repository_url": repository_url,
            "tag_name": tag_name,
            "environment": environment,
            "cloud_provider": cloud_provider,
            "app_name": app_name,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Release tag creation failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "repository_url": repository_url,
            "tag_name": tag_name,
            "environment": environment,
            "cloud_provider": cloud_provider
        }


async def list_git_agents(
    cloud_provider: str = "all"
) -> Dict[str, Any]:
    """List available Git agents and their status"""
    try:
        agents = []
        
        if cloud_provider in ["gcp", "all"]:
            # GCP Git Agent 상태 확인
            try:
                gcp_status = await mcp_registry.call_tool("gcp-git-agent", "get_gcp_cluster_info", {
                    "cluster_name": "test",
                    "zone": "asia-northeast3-a"
                })
                agents.append({
                    "name": "gcp-git-agent",
                    "cloud_provider": "gcp",
                    "status": "available" if gcp_status.get("status") == "success" else "error",
                    "last_check": datetime.now().isoformat()
                })
            except Exception as e:
                agents.append({
                    "name": "gcp-git-agent",
                    "cloud_provider": "gcp",
                    "status": "unavailable",
                    "error": str(e),
                    "last_check": datetime.now().isoformat()
                })
        
        if cloud_provider in ["ncp", "all"]:
            # NCP Git Agent 상태 확인
            try:
                ncp_status = await mcp_registry.call_tool("ncp-git-agent", "get_ncp_cluster_info", {
                    "cluster_name": "test",
                    "region": "KR"
                })
                agents.append({
                    "name": "ncp-git-agent",
                    "cloud_provider": "ncp",
                    "status": "available" if ncp_status.get("status") == "success" else "error",
                    "last_check": datetime.now().isoformat()
                })
            except Exception as e:
                agents.append({
                    "name": "ncp-git-agent",
                    "cloud_provider": "ncp",
                    "status": "unavailable",
                    "error": str(e),
                    "last_check": datetime.now().isoformat()
                })
        
        return {
            "status": "success",
            "action": "list_git_agents",
            "cloud_provider_filter": cloud_provider,
            "agents": agents,
            "total_count": len(agents),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to list Git agents: {e}")
        return {
            "status": "error",
            "error": str(e),
            "cloud_provider_filter": cloud_provider
        }
