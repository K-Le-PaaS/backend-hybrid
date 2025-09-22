from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...mcp.tools.k8s_resources import (
    k8s_create, k8s_get, k8s_apply, k8s_delete,
    ResourceKind, K8sObject, K8sRef
)
from ...services.k8s_client import get_core_v1_api, get_apps_v1_api

router = APIRouter()


class K8sResourceListResponse(BaseModel):
    """Kubernetes 리소스 목록 응답"""
    resources: List[Dict[str, Any]]
    total: int
    resource_type: str
    namespace: str


class K8sResourceResponse(BaseModel):
    """Kubernetes 리소스 응답"""
    resource: Dict[str, Any]
    resource_type: str
    name: str
    namespace: str


class K8sCreateRequest(BaseModel):
    """Kubernetes 리소스 생성 요청"""
    apiVersion: str = Field(..., description="API 버전")
    kind: str = Field(..., description="리소스 종류")
    metadata: Dict[str, Any] = Field(..., description="메타데이터")
    spec: Optional[Dict[str, Any]] = Field(None, description="스펙")
    data: Optional[Dict[str, Any]] = Field(None, description="데이터 (ConfigMap, Secret용)")
    kube_context: Optional[str] = Field(None, description="Kubernetes 컨텍스트")


class K8sUpdateRequest(BaseModel):
    """Kubernetes 리소스 업데이트 요청"""
    apiVersion: str = Field(..., description="API 버전")
    kind: str = Field(..., description="리소스 종류")
    metadata: Dict[str, Any] = Field(..., description="메타데이터")
    spec: Optional[Dict[str, Any]] = Field(None, description="스펙")
    data: Optional[Dict[str, Any]] = Field(None, description="데이터 (ConfigMap, Secret용)")
    kube_context: Optional[str] = Field(None, description="Kubernetes 컨텍스트")


@router.get("/resources/{resource_type}", response_model=K8sResourceListResponse)
async def list_resources(
    resource_type: str,
    namespace: str = Query("default", description="네임스페이스"),
    kube_context: Optional[str] = Query(None, description="Kubernetes 컨텍스트")
) -> K8sResourceListResponse:
    """Kubernetes 리소스 목록 조회"""
    try:
        if resource_type == ResourceKind.DEPLOYMENT:
            api = get_apps_v1_api(context=kube_context)
            response = api.list_namespaced_deployment(namespace=namespace)
            resources = [item.to_dict() for item in response.items]
        elif resource_type == ResourceKind.SERVICE:
            api = get_core_v1_api(context=kube_context)
            response = api.list_namespaced_service(namespace=namespace)
            resources = [item.to_dict() for item in response.items]
        elif resource_type == ResourceKind.CONFIGMAP:
            api = get_core_v1_api(context=kube_context)
            response = api.list_namespaced_config_map(namespace=namespace)
            resources = [item.to_dict() for item in response.items]
        elif resource_type == ResourceKind.SECRET:
            api = get_core_v1_api(context=kube_context)
            response = api.list_namespaced_secret(namespace=namespace)
            resources = [item.to_dict() for item in response.items]
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported resource type: {resource_type}")
        
        return K8sResourceListResponse(
            resources=resources,
            total=len(resources),
            resource_type=resource_type,
            namespace=namespace
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list resources: {str(e)}")


@router.get("/resources/{resource_type}/{name}", response_model=K8sResourceResponse)
async def get_resource(
    resource_type: str,
    name: str,
    namespace: str = Query("default", description="네임스페이스"),
    kube_context: Optional[str] = Query(None, description="Kubernetes 컨텍스트")
) -> K8sResourceResponse:
    """특정 Kubernetes 리소스 조회"""
    try:
        result = await k8s_get(
            kind=resource_type,
            name=name,
            namespace=namespace,
            kube_context=kube_context
        )
        return K8sResourceResponse(
            resource=result,
            resource_type=resource_type,
            name=name,
            namespace=namespace
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get resource: {str(e)}")


@router.post("/resources/{resource_type}", response_model=K8sResourceResponse)
async def create_resource(
    resource_type: str,
    request: K8sCreateRequest,
    namespace: Optional[str] = Query(None, description="네임스페이스 (요청의 metadata.namespace 우선)")
) -> K8sResourceResponse:
    """Kubernetes 리소스 생성"""
    try:
        # 요청의 metadata에 namespace가 없으면 쿼리 파라미터 사용
        if "namespace" not in request.metadata:
            request.metadata["namespace"] = namespace or "default"
        
        result = await k8s_create(
            apiVersion=request.apiVersion,
            kind=request.kind,
            metadata=request.metadata,
            spec=request.spec,
            data=request.data,
            kube_context=request.kube_context
        )
        
        # 생성된 리소스 조회
        resource = await k8s_get(
            kind=resource_type,
            name=result["name"],
            namespace=result["namespace"],
            kube_context=request.kube_context
        )
        
        return K8sResourceResponse(
            resource=resource,
            resource_type=resource_type,
            name=result["name"],
            namespace=result["namespace"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create resource: {str(e)}")


@router.put("/resources/{resource_type}/{name}", response_model=K8sResourceResponse)
async def update_resource(
    resource_type: str,
    name: str,
    request: K8sUpdateRequest,
    namespace: Optional[str] = Query(None, description="네임스페이스 (요청의 metadata.namespace 우선)")
) -> K8sResourceResponse:
    """Kubernetes 리소스 업데이트 (Apply)"""
    try:
        # 요청의 metadata에 namespace가 없으면 쿼리 파라미터 사용
        if "namespace" not in request.metadata:
            request.metadata["namespace"] = namespace or "default"
        
        # name이 일치하는지 확인
        if request.metadata.get("name") != name:
            request.metadata["name"] = name
        
        result = await k8s_apply(
            apiVersion=request.apiVersion,
            kind=request.kind,
            metadata=request.metadata,
            spec=request.spec,
            data=request.data,
            kube_context=request.kube_context
        )
        
        # 업데이트된 리소스 조회
        resource = await k8s_get(
            kind=resource_type,
            name=result["name"],
            namespace=result["namespace"],
            kube_context=request.kube_context
        )
        
        return K8sResourceResponse(
            resource=resource,
            resource_type=resource_type,
            name=result["name"],
            namespace=result["namespace"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update resource: {str(e)}")


@router.delete("/resources/{resource_type}/{name}")
async def delete_resource(
    resource_type: str,
    name: str,
    namespace: str = Query("default", description="네임스페이스"),
    kube_context: Optional[str] = Query(None, description="Kubernetes 컨텍스트")
) -> Dict[str, Any]:
    """Kubernetes 리소스 삭제"""
    try:
        result = await k8s_delete(
            kind=resource_type,
            name=name,
            namespace=namespace,
            kube_context=kube_context
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete resource: {str(e)}")


@router.get("/namespaces")
async def list_namespaces(
    kube_context: Optional[str] = Query(None, description="Kubernetes 컨텍스트")
) -> List[Dict[str, Any]]:
    """네임스페이스 목록 조회"""
    try:
        api = get_core_v1_api(context=kube_context)
        response = api.list_namespace()
        return [item.to_dict() for item in response.items]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list namespaces: {str(e)}")


@router.get("/contexts")
async def list_contexts() -> List[Dict[str, Any]]:
    """사용 가능한 Kubernetes 컨텍스트 목록 조회"""
    try:
        from ...services.k8s_client import list_kube_contexts
        contexts = list_kube_contexts()
        return [
            {"name": name, "current": is_current}
            for name, is_current in contexts
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list contexts: {str(e)}")


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Kubernetes 클러스터 연결 상태 확인"""
    try:
        # 간단한 API 호출로 연결 상태 확인
        api = get_core_v1_api()
        api.list_namespace()
        return {
            "status": "healthy",
            "message": "Kubernetes cluster is accessible"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Kubernetes cluster is not accessible: {str(e)}"
        }