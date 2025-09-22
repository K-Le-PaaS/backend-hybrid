from typing import Any, Dict

from ...services.deployments import DeployApplicationInput, perform_deploy


async def deploy_application_tool(
    app_name: str,
    environment: str,
    image: str,
    replicas: int = 2,
    namespace: str = "default",
    port: int = 8080,
    env_vars: Dict[str, str] = None,
    resources: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Deploy application to Kubernetes cluster"""
    input_data = DeployApplicationInput(
        app_name=app_name,
        environment=environment,
        image=image,
        replicas=replicas,
        namespace=namespace,
        port=port,
        env_vars=env_vars or {},
        resources=resources or {}
    )
    return perform_deploy(input_data)


