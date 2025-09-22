#!/usr/bin/env python3
"""
Git 자동배포 MCP 도구

기존 CI/CD 파이프라인과 MCP 네이티브 Git 에이전트를 연동하는 통합 도구입니다.
"""

import asyncio
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from mcp.types import Tool, TextContent
from ..external.registry import mcp_registry

logger = logging.getLogger(__name__)


class GitDeploymentMCPTools:
    """Git 자동배포 MCP 도구 모음"""
    
    def __init__(self):
        self.tools = [
            Tool(
                name="deploy_application_mcp",
                description="Deploy application using MCP native Git agents",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"},
                        "environment": {"type": "string", "enum": ["staging", "production"], "description": "Deployment environment"},
                        "image": {"type": "string", "description": "Container image"},
                        "replicas": {"type": "number", "default": 2, "description": "Number of replicas"},
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp"], "description": "Cloud provider"},
                        "namespace": {"type": "string", "default": "default", "description": "Kubernetes namespace"},
                        "port": {"type": "number", "default": 8080, "description": "Service port"},
                        "env_vars": {"type": "object", "description": "Environment variables"},
                        "resources": {"type": "object", "description": "Resource limits and requests"}
                    },
                    "required": ["app_name", "environment", "image", "cloud_provider"]
                }
            ),
            Tool(
                name="rollback_deployment_mcp",
                description="Rollback deployment using MCP native Git agents",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"},
                        "environment": {"type": "string", "enum": ["staging", "production"], "description": "Deployment environment"},
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp"], "description": "Cloud provider"},
                        "namespace": {"type": "string", "default": "default", "description": "Kubernetes namespace"}
                    },
                    "required": ["app_name", "environment", "cloud_provider"]
                }
            ),
            Tool(
                name="get_deployment_status_mcp",
                description="Get deployment status using MCP native Git agents",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"},
                        "environment": {"type": "string", "enum": ["staging", "production"], "description": "Deployment environment"},
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp"], "description": "Cloud provider"},
                        "namespace": {"type": "string", "default": "default", "description": "Kubernetes namespace"}
                    },
                    "required": ["app_name", "environment", "cloud_provider"]
                }
            ),
            Tool(
                name="git_workflow_automation",
                description="Execute Git workflow automation (clone, build, deploy)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repository_url": {"type": "string", "description": "Git repository URL"},
                        "branch": {"type": "string", "default": "main", "description": "Branch to deploy"},
                        "environment": {"type": "string", "enum": ["staging", "production"], "description": "Deployment environment"},
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp"], "description": "Cloud provider"},
                        "app_name": {"type": "string", "description": "Application name"},
                        "dockerfile_path": {"type": "string", "default": "Dockerfile", "description": "Dockerfile path"},
                        "build_args": {"type": "object", "description": "Docker build arguments"},
                        "auto_deploy": {"type": "boolean", "default": True, "description": "Automatically deploy after build"}
                    },
                    "required": ["repository_url", "environment", "cloud_provider", "app_name"]
                }
            ),
            Tool(
                name="create_release_tag",
                description="Create release tag and trigger production deployment",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "repository_url": {"type": "string", "description": "Git repository URL"},
                        "tag_name": {"type": "string", "description": "Release tag name (e.g., v1.0.0)"},
                        "message": {"type": "string", "description": "Tag message"},
                        "environment": {"type": "string", "enum": ["staging", "production"], "description": "Deployment environment"},
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp"], "description": "Cloud provider"},
                        "app_name": {"type": "string", "description": "Application name"},
                        "auto_deploy": {"type": "boolean", "default": True, "description": "Automatically deploy after tagging"}
                    },
                    "required": ["repository_url", "tag_name", "environment", "cloud_provider", "app_name"]
                }
            ),
            Tool(
                name="list_git_agents",
                description="List available Git agents and their status",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cloud_provider": {"type": "string", "enum": ["gcp", "ncp", "all"], "default": "all", "description": "Filter by cloud provider"}
                    }
                }
            )
        ]
    
    def get_tools(self) -> List[Tool]:
        """MCP 도구 목록 반환"""
        return self.tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """MCP 도구 실행"""
        try:
            if name == "deploy_application_mcp":
                result = await self._deploy_application_mcp(arguments)
            elif name == "rollback_deployment_mcp":
                result = await self._rollback_deployment_mcp(arguments)
            elif name == "get_deployment_status_mcp":
                result = await self._get_deployment_status_mcp(arguments)
            elif name == "git_workflow_automation":
                result = await self._git_workflow_automation(arguments)
            elif name == "create_release_tag":
                result = await self._create_release_tag(arguments)
            elif name == "list_git_agents":
                result = await self._list_git_agents(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")
            
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False)
            )]
            
        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e), "tool": name}, indent=2, ensure_ascii=False)
            )]
    
    async def _deploy_application_mcp(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """MCP 네이티브 에이전트를 통한 애플리케이션 배포"""
        app_name = args["app_name"]
        environment = args["environment"]
        image = args["image"]
        cloud_provider = args["cloud_provider"]
        replicas = args.get("replicas", 2)
        namespace = args.get("namespace", "default")
        port = args.get("port", 8080)
        env_vars = args.get("env_vars", {})
        resources = args.get("resources", {})
        
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
                "env_vars": env_vars,
                "resources": resources
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
    
    async def _rollback_deployment_mcp(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """MCP 네이티브 에이전트를 통한 배포 롤백"""
        app_name = args["app_name"]
        environment = args["environment"]
        cloud_provider = args["cloud_provider"]
        namespace = args.get("namespace", "default")
        
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
    
    async def _get_deployment_status_mcp(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """MCP 네이티브 에이전트를 통한 배포 상태 조회"""
        app_name = args["app_name"]
        environment = args["environment"]
        cloud_provider = args["cloud_provider"]
        namespace = args.get("namespace", "default")
        
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
    
    async def _git_workflow_automation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Git 워크플로우 자동화 (클론 → 빌드 → 배포)"""
        repository_url = args["repository_url"]
        branch = args.get("branch", "main")
        environment = args["environment"]
        cloud_provider = args["cloud_provider"]
        app_name = args["app_name"]
        dockerfile_path = args.get("dockerfile_path", "Dockerfile")
        build_args = args.get("build_args", {})
        auto_deploy = args.get("auto_deploy", True)
        
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
                **build_args
            })
            results["build"] = build_result
            
            if build_result.get("status") != "success":
                raise Exception(f"Docker build failed: {build_result.get('error')}")
            
            image = build_result.get("gcr_image") or build_result.get("ncp_image")
            
            # 3. 자동 배포 (옵션)
            if auto_deploy:
                deploy_result = await self._deploy_application_mcp({
                    "app_name": app_name,
                    "environment": environment,
                    "image": image,
                    "cloud_provider": cloud_provider
                })
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
    
    async def _create_release_tag(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """릴리스 태그 생성 및 프로덕션 배포 트리거"""
        repository_url = args["repository_url"]
        tag_name = args["tag_name"]
        message = args.get("message", f"Release {tag_name}")
        environment = args["environment"]
        cloud_provider = args["cloud_provider"]
        app_name = args["app_name"]
        auto_deploy = args.get("auto_deploy", True)
        
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
                "message": message,
                "push": True
            })
            results["tag"] = tag_result
            
            if tag_result.get("status") != "success":
                raise Exception(f"Git tag creation failed: {tag_result.get('error')}")
            
            # 3. 자동 배포 (옵션)
            if auto_deploy:
                # 태그 기반 이미지 이름 생성
                image = f"{app_name}:{tag_name}"
                
                deploy_result = await self._deploy_application_mcp({
                    "app_name": app_name,
                    "environment": environment,
                    "image": image,
                    "cloud_provider": cloud_provider
                })
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
    
    async def _list_git_agents(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """사용 가능한 Git 에이전트 목록 조회"""
        cloud_provider = args.get("cloud_provider", "all")
        
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


# 전역 인스턴스
git_deployment_tools = GitDeploymentMCPTools()
