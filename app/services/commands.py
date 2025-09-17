from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from .deployments import DeployApplicationInput, perform_deploy
from .k8s_client import get_apps_v1_api


class CommandRequest(BaseModel):
    text: str = Field(min_length=1)


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
    q = re.search(r"["'`](.+?)["'`].*배포", text)
    if q:
        return q.group(1)
    m = re.search(r"([a-z0-9-_.]+)\s*(앱|app)?\s*.*배포", text, re.I)
    if m:
        return m.group(1)
    return None


def plan_command(req: CommandRequest) -> CommandPlan:
    text = req.text.strip()

    # Deploy intent
    if re.search(r"배포|deploy", text, re.I):
        app_name = _parse_app_name(text) or "app"
        environment = _parse_environment(text) or "staging"
        replicas = _parse_replicas(text) or 2
        # naive image guess
        image = f"{app_name}:latest"
        return CommandPlan(
            tool="deploy_application",
            args={
                "app_name": app_name,
                "environment": environment,
                "image": image,
                "replicas": replicas,
            },
        )

    # Scale intent (deployment replicas)
    if re.search(r"스케일|레플리카|replica", text, re.I):
        app_name = _parse_app_name(text) or "app"
        replicas = _parse_replicas(text) or 2
        ns = "default"
        return CommandPlan(
            tool="k8s_scale_deployment",
            args={"name": app_name, "namespace": ns, "replicas": replicas},
        )

    raise ValueError("해석할 수 없는 명령입니다.")


async def execute_command(plan: CommandPlan) -> Dict[str, Any]:
    if plan.tool == "deploy_application":
        payload = DeployApplicationInput(**plan.args)
        return perform_deploy(payload)

    if plan.tool == "k8s_scale_deployment":
        apps = get_apps_v1_api()
        name = plan.args["name"]
        ns = plan.args["namespace"]
        replicas = plan.args["replicas"]
        body = {"spec": {"replicas": replicas}}
        apps.patch_namespaced_deployment(name=name, namespace=ns, body=body)
        return {"status": "patched", "kind": "Deployment", "name": name, "namespace": ns, "replicas": replicas}

    raise ValueError("지원하지 않는 실행 계획입니다.")


