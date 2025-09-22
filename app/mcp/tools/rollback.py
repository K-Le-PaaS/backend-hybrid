from typing import Any, Dict

from ...services.deployments import perform_rollback


async def rollback_deployment(
    app_name: str,
    environment: str
) -> Dict[str, Any]:
    """Rollback to the previous deployment version (keeps last 3 versions)"""
    return perform_rollback(app_name=app_name, environment=environment)


