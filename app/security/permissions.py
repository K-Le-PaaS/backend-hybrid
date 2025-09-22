"""
권한 관리 모듈
"""
from typing import List, Dict, Any, Optional
from enum import Enum
from fastapi import HTTPException, status

class Permission(Enum):
    """권한 열거형"""
    # 사용자 관리
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    USER_ADMIN = "user:admin"
    
    # 배포 관리
    DEPLOY_READ = "deploy:read"
    DEPLOY_WRITE = "deploy:write"
    DEPLOY_DELETE = "deploy:delete"
    DEPLOY_ADMIN = "deploy:admin"
    
    # 클러스터 관리
    CLUSTER_READ = "cluster:read"
    CLUSTER_WRITE = "cluster:write"
    CLUSTER_DELETE = "cluster:delete"
    CLUSTER_ADMIN = "cluster:admin"
    
    # 모니터링
    MONITOR_READ = "monitor:read"
    MONITOR_WRITE = "monitor:write"
    MONITOR_ADMIN = "monitor:admin"
    
    # 시스템 관리
    SYSTEM_READ = "system:read"
    SYSTEM_WRITE = "system:write"
    SYSTEM_ADMIN = "system:admin"

class Role(Enum):
    """역할 열거형"""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

class PermissionManager:
    """권한 관리를 담당하는 클래스"""
    
    def __init__(self):
        self.role_permissions = self._initialize_role_permissions()
    
    def _initialize_role_permissions(self) -> Dict[Role, List[Permission]]:
        """역할별 권한 매핑 초기화"""
        return {
            Role.SUPER_ADMIN: list(Permission),  # 모든 권한
            
            Role.ADMIN: [
                # 사용자 관리
                Permission.USER_READ, Permission.USER_WRITE, Permission.USER_DELETE,
                # 배포 관리
                Permission.DEPLOY_READ, Permission.DEPLOY_WRITE, Permission.DEPLOY_DELETE, Permission.DEPLOY_ADMIN,
                # 클러스터 관리
                Permission.CLUSTER_READ, Permission.CLUSTER_WRITE, Permission.CLUSTER_DELETE, Permission.CLUSTER_ADMIN,
                # 모니터링
                Permission.MONITOR_READ, Permission.MONITOR_WRITE, Permission.MONITOR_ADMIN,
                # 시스템 관리
                Permission.SYSTEM_READ, Permission.SYSTEM_WRITE
            ],
            
            Role.DEVELOPER: [
                # 사용자 관리 (읽기만)
                Permission.USER_READ,
                # 배포 관리
                Permission.DEPLOY_READ, Permission.DEPLOY_WRITE,
                # 클러스터 관리 (읽기만)
                Permission.CLUSTER_READ,
                # 모니터링
                Permission.MONITOR_READ, Permission.MONITOR_WRITE,
                # 시스템 관리 (읽기만)
                Permission.SYSTEM_READ
            ],
            
            Role.VIEWER: [
                # 읽기 권한만
                Permission.USER_READ,
                Permission.DEPLOY_READ,
                Permission.CLUSTER_READ,
                Permission.MONITOR_READ,
                Permission.SYSTEM_READ
            ]
        }
    
    def get_permissions_for_role(self, role: Role) -> List[Permission]:
        """역할에 대한 권한 목록 반환"""
        return self.role_permissions.get(role, [])
    
    def get_permissions_for_roles(self, roles: List[Role]) -> List[Permission]:
        """여러 역할에 대한 권한 목록 반환 (중복 제거)"""
        permissions = set()
        for role in roles:
            permissions.update(self.get_permissions_for_role(role))
        return list(permissions)
    
    def has_permission(self, user_permissions: List[str], required_permission: Permission) -> bool:
        """사용자가 특정 권한을 가지고 있는지 확인"""
        return required_permission.value in user_permissions
    
    def has_any_permission(self, user_permissions: List[str], required_permissions: List[Permission]) -> bool:
        """사용자가 여러 권한 중 하나라도 가지고 있는지 확인"""
        return any(self.has_permission(user_permissions, perm) for perm in required_permissions)
    
    def has_all_permissions(self, user_permissions: List[str], required_permissions: List[Permission]) -> bool:
        """사용자가 모든 권한을 가지고 있는지 확인"""
        return all(self.has_permission(user_permissions, perm) for perm in required_permissions)
    
    def check_permission(self, user_permissions: List[str], required_permission: Permission) -> None:
        """권한 확인 및 예외 발생"""
        if not self.has_permission(user_permissions, required_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {required_permission.value}"
            )
    
    def check_any_permission(self, user_permissions: List[str], required_permissions: List[Permission]) -> None:
        """여러 권한 중 하나라도 가지고 있는지 확인 및 예외 발생"""
        if not self.has_any_permission(user_permissions, required_permissions):
            permission_names = [perm.value for perm in required_permissions]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required one of: {', '.join(permission_names)}"
            )
    
    def check_all_permissions(self, user_permissions: List[str], required_permissions: List[Permission]) -> None:
        """모든 권한을 가지고 있는지 확인 및 예외 발생"""
        if not self.has_all_permissions(user_permissions, required_permissions):
            permission_names = [perm.value for perm in required_permissions]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required all of: {', '.join(permission_names)}"
            )
    
    def get_resource_permissions(self, resource_type: str, action: str) -> List[Permission]:
        """리소스 타입과 액션에 따른 필요한 권한 반환"""
        permission_map = {
            "user": {
                "read": [Permission.USER_READ],
                "write": [Permission.USER_WRITE],
                "delete": [Permission.USER_DELETE],
                "admin": [Permission.USER_ADMIN]
            },
            "deploy": {
                "read": [Permission.DEPLOY_READ],
                "write": [Permission.DEPLOY_WRITE],
                "delete": [Permission.DEPLOY_DELETE],
                "admin": [Permission.DEPLOY_ADMIN]
            },
            "cluster": {
                "read": [Permission.CLUSTER_READ],
                "write": [Permission.CLUSTER_WRITE],
                "delete": [Permission.CLUSTER_DELETE],
                "admin": [Permission.CLUSTER_ADMIN]
            },
            "monitor": {
                "read": [Permission.MONITOR_READ],
                "write": [Permission.MONITOR_WRITE],
                "admin": [Permission.MONITOR_ADMIN]
            },
            "system": {
                "read": [Permission.SYSTEM_READ],
                "write": [Permission.SYSTEM_WRITE],
                "admin": [Permission.SYSTEM_ADMIN]
            }
        }
        
        return permission_map.get(resource_type, {}).get(action, [])
    
    def check_resource_permission(self, user_permissions: List[str], resource_type: str, action: str) -> None:
        """리소스별 권한 확인"""
        required_permissions = self.get_resource_permissions(resource_type, action)
        if required_permissions:
            self.check_any_permission(user_permissions, required_permissions)
    
    def is_admin(self, user_roles: List[str]) -> bool:
        """관리자 권한 확인"""
        admin_roles = [Role.SUPER_ADMIN.value, Role.ADMIN.value]
        return any(role in admin_roles for role in user_roles)
    
    def is_super_admin(self, user_roles: List[str]) -> bool:
        """슈퍼 관리자 권한 확인"""
        return Role.SUPER_ADMIN.value in user_roles
