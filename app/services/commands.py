from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from .deployments import DeployApplicationInput, perform_deploy
from .k8s_client import get_apps_v1_api


class CommandRequest(BaseModel):
    command: str = Field(min_length=1)
    app_name: str = Field(default="")
    replicas: int = Field(default=1)
    lines: int = Field(default=30)
    version: str = Field(default="")


@dataclass
class CommandPlan:
    tool: str
    args: Dict[str, Any]


def _parse_environment(text: str) -> Optional[str]:
    if re.search(r"프로덕션|production", text, re.I):
        return "production"
    if re.search(r"스테이징|staging", text, re.I):
        return "staging"
    return None


def _parse_replicas(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*(개|레플리카|replicas?)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _parse_app_name(text: str) -> Optional[str]:
    # naive: word before '배포' or explicit quotes
    q = re.search(r"[\"'`](.+?)[\"'`].*배포", text)
    if q:
        return q.group(1)
    m = re.search(r"([a-z0-9-_.]+)\s*(앱|app)?\s*.*배포", text, re.I)
    if m:
        return m.group(1)
    # For non-deploy commands, extract app name more broadly
    # Handle Korean particles like '를', '을', '이', '가', '은', '는'
    m = re.search(r"([a-z0-9-_.]+)(?:[를을이가은는]|$)", text, re.I)
    if m:
        return m.group(1)
    # Fallback: extract any alphanumeric word
    m = re.search(r"([a-z0-9-_.]+)\s*(앱|app)?", text, re.I)
    if m:
        return m.group(1)
    return None


def _parse_log_lines(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*(줄|줄|lines?)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _parse_version(text: str) -> Optional[str]:
    m = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
    if m:
        return f"v{m.group(1)}"
    return None


def plan_command(req: CommandRequest) -> CommandPlan:
    command = req.command.lower()
    app_name = req.app_name or "app"
    ns = "default"

    if command == "deploy":
        return CommandPlan(
            tool="deploy_application",
            args={
                "app_name": app_name,
                "environment": "staging",
                "image": f"{app_name}:latest",
                "replicas": 2,
            },
        )
    
    elif command == "scale":
        return CommandPlan(
            tool="k8s_scale_deployment",
            args={"name": app_name, "namespace": ns, "replicas": req.replicas},
        )
    
    elif command == "status":
        return CommandPlan(
            tool="k8s_get_status",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "logs":
        return CommandPlan(
            tool="k8s_get_logs",
            args={"name": app_name, "namespace": ns, "lines": req.lines},
        )
    
    elif command == "endpoint":
        return CommandPlan(
            tool="k8s_get_endpoints",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "restart":
        return CommandPlan(
            tool="k8s_restart_deployment",
            args={"name": app_name, "namespace": ns},
        )
    
    elif command == "rollback":
        return CommandPlan(
            tool="k8s_rollback_deployment",
            args={"name": app_name, "namespace": ns, "version": req.version},
        )

    raise ValueError("해석할 수 없는 명령입니다.")


async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    if plan.tool == "deploy_application":
        payload = DeployApplicationInput(**plan.args)
        return await perform_deploy(payload)

    if plan.tool == "k8s_scale_deployment":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        replicas = plan.args["replicas"]
        # TODO: Implement actual Kubernetes scale operation
        return {"status": "not_implemented", "message": f"Scale {name} in {ns} namespace to {replicas} replicas"}

    # TODO: Implement the following command handlers
    if plan.tool == "k8s_get_status":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        # TODO: Implement actual Kubernetes status check
        return {"status": "not_implemented", "message": f"Status check for {name} in {ns} namespace"}

    if plan.tool == "k8s_get_logs":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        lines = plan.args["lines"]
        # TODO: Implement actual Kubernetes logs retrieval
        return {"status": "not_implemented", "message": f"Logs for {name} in {ns} namespace ({lines} lines)"}

    if plan.tool == "k8s_get_endpoints":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        # TODO: Implement actual Kubernetes endpoints retrieval
        return {"status": "not_implemented", "message": f"Endpoints for {name} in {ns} namespace"}

    if plan.tool == "k8s_restart_deployment":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        # TODO: Implement actual Kubernetes deployment restart
        return {"status": "not_implemented", "message": f"Restart {name} in {ns} namespace"}

    if plan.tool == "k8s_rollback_deployment":
        name = plan.args["name"]
        ns = plan.args["namespace"]
        version = plan.args.get("version")
        # TODO: Implement actual Kubernetes deployment rollback
        return {"status": "not_implemented", "message": f"Rollback {name} in {ns} namespace to {version or 'previous version'}"}

    raise ValueError("지원하지 않는 실행 계획입니다.")


