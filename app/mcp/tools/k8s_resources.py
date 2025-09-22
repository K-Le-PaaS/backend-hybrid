from enum import Enum
from typing import Any, Dict, Optional

# from fastmcp.tools import Tool  # Will be registered via @server.tool decorator
from pydantic import BaseModel, Field

from ...services.k8s_client import get_core_v1_api, get_apps_v1_api

try:
    from kubernetes.client import ApiException
except ImportError:
    # Fallback for when kubernetes client is not available
    class ApiException(Exception):
        def __init__(self, status: int, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.status = status


class ResourceKind(str, Enum):
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


async def k8s_create(
    apiVersion: str,
    kind: str,
    metadata: Dict[str, Any],
    spec: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    kube_context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes resource (Deployment, Service, ConfigMap, Secret)"""
    ns = metadata.get("namespace", "default")
    ctx = kube_context
    
    # Create the object body
    obj_body = {
        "apiVersion": apiVersion,
        "kind": kind,
        "metadata": metadata,
    }
    if spec:
        obj_body["spec"] = spec
    if data:
        obj_body["data"] = data
    
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        created = api.create_namespaced_deployment(namespace=ns, body=obj_body)
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_service(namespace=ns, body=obj_body)
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_config_map(namespace=ns, body=obj_body)
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        created = api.create_namespaced_secret(namespace=ns, body=obj_body)
    else:
        raise ValueError("Unsupported kind")
    return {"status": "created", "kind": kind, "name": created.metadata.name, "namespace": ns}


async def k8s_get(
    kind: str,
    name: str,
    namespace: str = "default",
    kube_context: Optional[str] = None
) -> Dict[str, Any]:
    """Get a Kubernetes resource by kind/name/namespace"""
    ctx = kube_context
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        obj = api.read_namespaced_deployment(name=name, namespace=namespace)
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_service(name=name, namespace=namespace)
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_config_map(name=name, namespace=namespace)
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        obj = api.read_namespaced_secret(name=name, namespace=namespace)
    else:
        raise ValueError("Unsupported kind")
    return obj.to_dict()  # type: ignore[no-any-return]


async def k8s_apply(
    apiVersion: str,
    kind: str,
    metadata: Dict[str, Any],
    spec: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    kube_context: Optional[str] = None
) -> Dict[str, Any]:
    """Apply (create or patch) a Kubernetes resource by full manifest"""
    ns = metadata.get("namespace", "default")
    name = metadata.get("name")
    if not name:
        raise ValueError("metadata.name is required for apply")
    ctx = kube_context
    
    # Create the object body
    body = {
        "apiVersion": apiVersion,
        "kind": kind,
        "metadata": metadata,
    }
    if spec:
        body["spec"] = spec
    if data:
        body["data"] = data
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        try:
            api.read_namespaced_deployment(name=name, namespace=ns)
            api.patch_namespaced_deployment(name=name, namespace=ns, body=body)
            action = "patched"
        except ApiException as e:
            if e.status != 404:
                raise
            api.create_namespaced_deployment(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_service(name=name, namespace=ns)
            api.patch_namespaced_service(name=name, namespace=ns, body=body)
            action = "patched"
        except ApiException as e:
            if e.status != 404:
                raise
            api.create_namespaced_service(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_config_map(name=name, namespace=ns)
            api.patch_namespaced_config_map(name=name, namespace=ns, body=body)
            action = "patched"
        except ApiException as e:
            if e.status != 404:
                raise
            api.create_namespaced_config_map(namespace=ns, body=body)
            action = "created"
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        try:
            api.read_namespaced_secret(name=name, namespace=ns)
            api.patch_namespaced_secret(name=name, namespace=ns, body=body)
            action = "patched"
        except ApiException as e:
            if e.status != 404:
                raise
            api.create_namespaced_secret(namespace=ns, body=body)
            action = "created"
    else:
        raise ValueError("Unsupported kind")
    return {"status": action, "kind": kind, "name": name, "namespace": ns}


async def k8s_delete(
    kind: str,
    name: str,
    namespace: str = "default",
    kube_context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes resource by kind/name/namespace"""
    ctx = kube_context
    if kind == ResourceKind.DEPLOYMENT:
        api = get_apps_v1_api(context=ctx)
        api.delete_namespaced_deployment(name=name, namespace=namespace)
    elif kind == ResourceKind.SERVICE:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_service(name=name, namespace=namespace)
    elif kind == ResourceKind.CONFIGMAP:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_config_map(name=name, namespace=namespace)
    elif kind == ResourceKind.SECRET:
        api = get_core_v1_api(context=ctx)
        api.delete_namespaced_secret(name=name, namespace=namespace)
    else:
        raise ValueError("Unsupported kind")
    return {"status": "deleted", "kind": kind, "name": name, "namespace": namespace}


