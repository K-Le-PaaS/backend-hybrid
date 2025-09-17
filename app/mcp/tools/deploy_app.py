from typing import Any, Dict

try:
    from fastapi_mcp import mcp_tool  # type: ignore
except Exception:  # noqa: BLE001
    # Define a no-op decorator so imports don't fail when MCP not installed
    def mcp_tool(*args: Any, **kwargs: Any):  # type: ignore
        def wrapper(func):
            return func
        return wrapper

from ...services.deployments import DeployApplicationInput, perform_deploy


@mcp_tool(
    name="deploy_application",
    description="Deploy application to Kubernetes cluster",
    input_model=DeployApplicationInput,
)
async def deploy_application_tool(input_data: DeployApplicationInput) -> Dict[str, Any]:
    return perform_deploy(input_data)


