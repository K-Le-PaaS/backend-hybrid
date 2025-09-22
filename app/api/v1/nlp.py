from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)

# 자연어 명령 처리 모델
class NaturalLanguageCommand(BaseModel):
    command: str
    timestamp: str
    context: Optional[Dict[str, Any]] = None

class CommandResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class CommandHistory(BaseModel):
    id: str
    command: str
    timestamp: datetime
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# 메모리 기반 명령 히스토리 (실제 환경에서는 데이터베이스 사용)
command_history: List[CommandHistory] = []

@router.post("/nlp/process", response_model=CommandResponse)
async def process_command(command_data: NaturalLanguageCommand):
    """
    자연어 명령을 처리합니다.
    """
    try:
        command = command_data.command.strip()
        logger.info(f"자연어 명령 처리 시작: {command}")
        
        # 명령 유효성 검사
        if not command:
            raise HTTPException(status_code=400, detail="명령을 입력해주세요.")
        
        if len(command) < 3:
            raise HTTPException(status_code=400, detail="명령이 너무 짧습니다. (최소 3자 이상)")
        
        if len(command) > 500:
            raise HTTPException(status_code=400, detail="명령이 너무 깁니다. (최대 500자)")
        
        # 위험한 명령어 체크
        dangerous_keywords = ['rm -rf', 'sudo', 'kill', 'format', 'delete all']
        if any(keyword in command.lower() for keyword in dangerous_keywords):
            raise HTTPException(status_code=400, detail="위험한 명령어가 포함되어 있습니다.")
        
        # 명령 파싱 및 처리
        parsed_command = parse_natural_language_command(command)
        logger.info(f"파싱된 명령: {parsed_command}")
        
        # 명령 히스토리에 추가
        command_id = str(uuid.uuid4())
        history_entry = CommandHistory(
            id=command_id,
            command=command,
            timestamp=datetime.now(),
            status="processing"
        )
        command_history.insert(0, history_entry)
        
        # 명령 실행 (실제 구현에서는 Kubernetes API 호출)
        result = await execute_kubernetes_command(parsed_command)
        
        # 히스토리 업데이트
        history_entry.status = "completed"
        history_entry.result = result
        
        return CommandResponse(
            success=True,
            message="명령이 성공적으로 처리되었습니다.",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"명령 처리 실패: {str(e)}")
        
        # 에러 히스토리 추가
        if 'command_id' in locals():
            history_entry.status = "failed"
            history_entry.error = str(e)
        
        return CommandResponse(
            success=False,
            message="명령 처리 중 오류가 발생했습니다.",
            error=str(e)
        )

@router.get("/nlp/history", response_model=List[CommandHistory])
async def get_command_history(limit: int = 10):
    """
    명령 히스토리를 조회합니다.
    """
    try:
        return command_history[:limit]
    except Exception as e:
        logger.error(f"명령 히스토리 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="명령 히스토리 조회에 실패했습니다.")

@router.get("/nlp/suggestions", response_model=List[str])
async def get_command_suggestions(context: Optional[str] = None):
    """
    명령 제안 목록을 조회합니다.
    """
    try:
        suggestions = [
            "nginx deployment 생성해줘",
            "모든 pod 상태 확인해줘",
            "frontend-app replicas 3개로 늘려줘",
            "test-deployment 삭제해줘",
            "configmap 목록 보여줘",
            "service 생성해줘",
            "secret 업데이트해줘",
            "namespace 생성해줘",
            "리소스 사용량 확인해줘",
            "로그 확인해줘"
        ]
        
        # 컨텍스트에 따른 필터링
        if context:
            context_lower = context.lower()
            suggestions = [s for s in suggestions if context_lower in s.lower()]
        
        return suggestions[:10]
    except Exception as e:
        logger.error(f"명령 제안 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="명령 제안 조회에 실패했습니다.")

def parse_natural_language_command(command: str) -> Dict[str, Any]:
    """
    자연어 명령을 파싱합니다.
    """
    command_lower = command.lower()
    
    # 액션 감지
    action = "unknown"
    if any(keyword in command_lower for keyword in ["생성", "만들", "추가", "create"]):
        action = "create"
    elif any(keyword in command_lower for keyword in ["확인", "보여", "조회", "get", "list"]):
        action = "get"
    elif any(keyword in command_lower for keyword in ["수정", "변경", "업데이트", "update"]):
        action = "update"
    elif any(keyword in command_lower for keyword in ["삭제", "제거", "delete"]):
        action = "delete"
    
    # 리소스 타입 감지
    resource_type = "unknown"
    resource_keywords = {
        "deployment": ["deployment", "배포"],
        "service": ["service", "서비스"],
        "pod": ["pod", "파드"],
        "configmap": ["configmap", "설정"],
        "secret": ["secret", "시크릿"],
        "namespace": ["namespace", "네임스페이스"]
    }
    
    for resource, keywords in resource_keywords.items():
        if any(keyword in command_lower for keyword in keywords):
            resource_type = resource
            break
    
    # 숫자 추출 (replicas 등)
    import re
    numbers = re.findall(r'\d+', command)
    replicas = int(numbers[0]) if numbers else None
    
    return {
        "action": action,
        "resource_type": resource_type,
        "replicas": replicas,
        "original_command": command,
        "parsed_at": datetime.now().isoformat()
    }

async def execute_kubernetes_command(parsed_command: Dict[str, Any]) -> Dict[str, Any]:
    """
    파싱된 명령을 실행합니다.
    """
    from ...mcp.tools.k8s_resources import k8s_create, k8s_get, k8s_apply, k8s_delete, ResourceKind
    
    action = parsed_command["action"]
    resource_type = parsed_command["resource_type"]
    original_command = parsed_command["original_command"]
    
    try:
        if action == "create":
            # 실제 Kubernetes 리소스 생성
            if resource_type == "deployment":
                # nginx deployment 생성 예시
                result = await k8s_create(
                    apiVersion="apps/v1",
                    kind="Deployment",
                    metadata={
                        "name": "nginx-deployment",
                        "namespace": "default",
                        "labels": {"app": "nginx"}
                    },
                    spec={
                        "replicas": parsed_command.get("replicas", 2),
                        "selector": {"matchLabels": {"app": "nginx"}},
                        "template": {
                            "metadata": {"labels": {"app": "nginx"}},
                            "spec": {
                                "containers": [{
                                    "name": "nginx",
                                    "image": "nginx:latest",
                                    "ports": [{"containerPort": 80}]
                                }]
                            }
                        }
                    }
                )
                return {
                    "message": f"Deployment '{result['name']}'이 성공적으로 생성되었습니다.",
                    "resource_type": resource_type,
                    "action": "created",
                    "result": result
                }
            elif resource_type == "service":
                result = await k8s_create(
                    apiVersion="v1",
                    kind="Service",
                    metadata={
                        "name": "nginx-service",
                        "namespace": "default",
                        "labels": {"app": "nginx"}
                    },
                    spec={
                        "selector": {"app": "nginx"},
                        "ports": [{"port": 80, "targetPort": 80}],
                        "type": "ClusterIP"
                    }
                )
                return {
                    "message": f"Service '{result['name']}'이 성공적으로 생성되었습니다.",
                    "resource_type": resource_type,
                    "action": "created",
                    "result": result
                }
            else:
                return {
                    "message": f"{resource_type} 리소스 생성은 아직 지원되지 않습니다.",
                    "resource_type": resource_type,
                    "action": "not_supported"
                }
                
        elif action == "get":
            # 실제 Kubernetes 리소스 조회
            if resource_type == "pod":
                # Pod 목록 조회 (Deployment를 통해)
                result = await k8s_get(
                    kind="Deployment",
                    name="nginx-deployment",
                    namespace="default"
                )
                return {
                    "message": f"Pod 상태를 확인했습니다. Deployment '{result.get('metadata', {}).get('name', 'unknown')}' 상태: {result.get('status', {}).get('phase', 'unknown')}",
                    "resource_type": resource_type,
                    "action": "listed",
                    "result": result
                }
            else:
                return {
                    "message": f"{resource_type} 리소스 조회는 아직 지원되지 않습니다.",
                    "resource_type": resource_type,
                    "action": "not_supported"
                }
                
        elif action == "update":
            return {
                "message": f"{resource_type} 리소스 업데이트는 아직 지원되지 않습니다.",
                "resource_type": resource_type,
                "action": "not_supported"
            }
        elif action == "delete":
            # 실제 Kubernetes 리소스 삭제
            if resource_type == "deployment":
                # nginx-deployment 삭제
                result = await k8s_delete(
                    kind="Deployment",
                    name="nginx-deployment",
                    namespace="default"
                )
                return {
                    "message": f"Deployment 'nginx-deployment'이 성공적으로 삭제되었습니다.",
                    "resource_type": resource_type,
                    "action": "deleted",
                    "result": result
                }
            else:
                return {
                    "message": f"{resource_type} 리소스 삭제는 아직 지원되지 않습니다.",
                    "resource_type": resource_type,
                    "action": "not_supported"
                }
        else:
            return {
                "message": "명령을 인식할 수 없습니다.",
                "action": "unknown"
            }
            
    except Exception as e:
        logger.error(f"Kubernetes 명령 실행 실패: {str(e)}")
        return {
            "message": f"명령 실행 중 오류가 발생했습니다: {str(e)}",
            "action": "error",
            "error": str(e)
        }