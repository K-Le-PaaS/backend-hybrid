from typing import Any, Dict

try:
    from fastapi_mcp import mcp_tool  # type: ignore
except Exception:  # noqa: BLE001
    def mcp_tool(*args: Any, **kwargs: Any):  # type: ignore
        def wrapper(func):
            return func
        return wrapper

from pydantic import BaseModel, Field

from ...services.deployments import perform_rollback


class RollbackInput(BaseModel):
    app_name: str = Field(min_length=1)
    environment: str = Field(pattern="^(staging|production)$")


@mcp_tool(
    name="rollback_deployment",
    description="Rollback to the previous deployment version (keeps last 3 versions)",
    input_model=RollbackInput,
)
async def rollback_deployment(input_data: RollbackInput) -> Dict[str, Any]:
    return perform_rollback(app_name=input_data.app_name, environment=input_data.environment)


