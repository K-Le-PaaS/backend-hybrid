from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

# commands.py 연동을 위한 import
from ...services.commands import CommandRequest, plan_command, execute_command
from ...database import get_db

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
async def process_command(
    command_data: NaturalLanguageCommand,
    db: Session = Depends(get_db)
):
    """
    자연어 명령을 처리합니다 (일반 K8s 명령 + 롤백 명령 지원).
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

        # 로그 줄 수 제한 검증 (추가 검증)
        if "줄" in command or "lines" in command.lower():
            # 숫자 추출하여 제한 확인
            import re
            numbers = re.findall(r'\d+', command)
            for num_str in numbers:
                num = int(num_str)
                if num > 100:
                    raise HTTPException(status_code=400, detail="로그 줄 수는 최대 100줄까지 조회 가능합니다.")

        # 위험한 명령어 체크
        dangerous_keywords = ['rm -rf', 'sudo', 'kill', 'format', 'delete all']
        if any(keyword in command.lower() for keyword in dangerous_keywords):
            raise HTTPException(status_code=400, detail="위험한 명령어가 포함되어 있습니다.")

        # Gemini API를 통한 자연어 해석 (1회만!)
        try:
            from ...llm.gemini import GeminiClient
            gemini_client = GeminiClient()
            
            # Gemini로 명령 해석
            gemini_result = await gemini_client.interpret(
                prompt=command,
                user_id="api_user",
                project_name=command_data.context.get("project_name", "default") if command_data.context else "default"
            )
            
            logger.info(f"Gemini 해석 결과: {gemini_result}")
            
            # 명령 히스토리에 추가
            command_id = str(uuid.uuid4())
            history_entry = CommandHistory(
                id=command_id,
                command=command,
                timestamp=datetime.now(),
                status="processing"
            )
            command_history.insert(0, history_entry)
            
            # Gemini 결과를 CommandRequest로 변환
            entities = gemini_result.get("entities", {})
            intent = gemini_result.get("intent", "status")
            
            logger.info(f"Gemini intent: {intent}")
            logger.info(f"Gemini entities: {entities}")
            
            req = CommandRequest(
                command=intent,
                # 리소스 타입별 필드 설정
                pod_name=entities.get("pod_name") or "",
                deployment_name=entities.get("deployment_name") or "",
                service_name=entities.get("service_name") or "",
                # 기타 파라미터들
                replicas=entities.get("replicas", 1),
                lines=entities.get("lines", 30),
                version=entities.get("version") or "",
                namespace=entities.get("namespace") or "default",
                previous=bool(entities.get("previous", False)),
                # NCP 롤백 관련 필드
                github_owner=entities.get("github_owner") or "",
                github_repo=entities.get("github_repo") or "",
                target_commit_sha=entities.get("target_commit_sha") or "",
                steps_back=entities.get("steps_back", 0)
            )
            
            logger.info(f"CommandRequest 생성: {req}")
            
            # commands.py로 실제 K8s 작업 수행
            try:
                plan = plan_command(req)
                logger.info(f"CommandPlan 생성: {plan}")
                
                k8s_result = await execute_command(plan)
                logger.info(f"K8s 실행 결과: {k8s_result}")
                
                # Gemini 메시지 + K8s 결과를 조합
                result = {
                    "message": gemini_result.get("message", "명령이 완료되었습니다."),
                    "action": gemini_result.get("intent", "unknown"),
                    "entities": entities,
                    "k8s_result": k8s_result  # 실제 K8s 작업 결과
                }
                
            except Exception as k8s_error:
                logger.error(f"commands.py 실행 실패: {k8s_error}")
                result = {
                    "message": f"명령 해석은 성공했지만 실행 중 오류가 발생했습니다: {str(k8s_error)}",
                    "action": gemini_result.get("intent", "unknown"),
                    "entities": entities,
                    "k8s_result": {"error": str(k8s_error)}
                }
                
        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {e}")
            # Gemini 실패 시 에러 응답
            result = {
                "message": f"명령 해석 중 오류가 발생했습니다: {str(e)}",
                "action": "error",
                "entities": {},
                "k8s_result": {"error": str(e)}
            }
        
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


# REMOVED: execute_kubernetes_command() - 레거시 코드
# 현재는 services/commands.py를 직접 호출하여 처리