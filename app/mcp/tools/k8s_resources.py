from typing import Any, Dict, Optional

try:
    from fastapi_mcp import mcp_tool  # type: ignore
except Exception:  # noqa: BLE001
    def mcp_tool(*args: Any, **kwargs: Any):  # type: ignore
        def wrapper(func):
            return func
        return wrapper

from pydantic import BaseModel, Field

from ...services.k8s_client import get_core_v1_api, get_apps_v1_api


class ResourceKind(str):
    DEPLOYMENT = "Deployment"
    SERVICE = "Service"
    CONFIGMAP = "ConfigMap"
    SECRET = "Secret"


class K8sObject(BaseModel):
    apiVersion: str
    kind: str
    metadata: Dict[str, Any]
    spec: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    kube_context: Optional[str] = None


class K8sRef(BaseModel):
    kind: str = Field(pattern="^(Deployment|Service|ConfigMap|Secret)$")
    name: str
    namespace: str = "default"
    kube_context: Optional[str] = None


@mcp_tool(
    name="k8s_create",
    description="Create a Kubernetes resource (Deployment, Service, ConfigMap, Secret)",
    input_model=K8sObject,
)
async def k8s_create(obj: K8sObject) -> Dict[str, Any]:
    ns = obj.metadata.get("namespace", "default")
    kind = obj.kind
    ctx = obj.kube_context
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        created = api.create_namespaced_deployment(namespace=ns, body=obj.model_dump())
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_service(namespace=ns, body=obj.model_dump())
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_config_map(namespace=ns, body=obj.model_dump())
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_secret(namespace=ns, body=obj.model_dump())
    else:
        raise ValueError("Unsupported kind")
    return {"status": "created", "kind": kind, "name": created.metadata.name, "namespace": ns}


@mcp_tool(
    name="k8s_get",
    description="Get a Kubernetes resource by kind/name/namespace",
    input_model=K8sRef,
)
async def k8s_get(ref: K8sRef) -> Dict[str, Any]:
    ctx = ref.kube_context
    if ref.kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        obj = api.read_namespaced_deployment(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_service(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_config_map(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_secret(name=ref.name, namespace=ref.namespace)
    else:
        raise ValueError("Unsupported kind")
    return obj.to_dict()  # type: ignore[no-any-return]


@mcp_tool(
    name="k8s_apply",
    description="Apply (create or patch) a Kubernetes resource by full manifest",
    input_model=K8sObject,
)
async def k8s_apply(obj: K8sObject) -> Dict[str, Any]:
    ns = obj.metadata.get("namespace", "default")
    name = obj.metadata.get("name")
    if not name:
        raise ValueError("metadata.name is required for apply")
    kind = obj.kind
    body = obj.model_dump()
    ctx = obj.kube_context
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        try:
            api.read_namespaced_deployment(name=name, namespace=ns)
            api.patch_namespaced_deployment(name=name, namespace=ns, body=body)
            action = "patched"
        except Exception:
            api.create_namespaced_deployment(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_service(name=name, namespace=ns)
            api.patch_namespaced_service(name=name, namespace=ns, body=body)
            action = "patched"
        except Exception:
            api.create_namespaced_service(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_config_map(name=name, namespace=ns)
            api.patch_namespaced_config_map(name=name, namespace=ns, body=body)
            action = "patched"
        except Exception:
            api.create_namespaced_config_map(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_secret(name=name, namespace=ns)
            api.patch_namespaced_secret(name=name, namespace=ns, body=body)
            action = "patched"
        except Exception:
            api.create_namespaced_secret(namespace=ns, body=body)
            action = "created"
    else:
        raise ValueError("Unsupported kind")
    return {"status": action, "kind": kind, "name": name, "namespace": ns}


@mcp_tool(
    name="k8s_delete",
    description="Delete a Kubernetes resource by kind/name/namespace",
    input_model=K8sRef,
)
async def k8s_delete(ref: K8sRef) -> Dict[str, Any]:
    ctx = ref.kube_context
    if ref.kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        api.delete_namespaced_deployment(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_service(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_config_map(name=ref.name, namespace=ref.namespace)
    elif ref.kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_secret(name=ref.name, namespace=ref.namespace)
    else:
        raise ValueError("Unsupported kind")
    return {"status": "deleted", "kind": ref.kind, "name": ref.name, "namespace": ref.namespace}


