from fastapi import APIRouter, HTTPException
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
        
        # Gemini API를 통한 고급 명령 처리
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
            
            # Gemini 결과를 간소화된 형식으로 변환
            if gemini_result.get("intent") != "unknown":
                result = {
                    "message": gemini_result.get("message", "명령이 성공적으로 처리되었습니다."),
                    "action": gemini_result.get("intent", "unknown"),
                    "entities": gemini_result.get("entities", {}),
                    "result": gemini_result.get("result", {})
                }
            else:
                # Gemini가 해석하지 못한 경우 에러 응답
                result = {
                    "message": "명령을 해석할 수 없습니다. 다시 시도해주세요.",
                    "action": "unknown",
                    "entities": {},
                    "result": {"error": "Command not recognized"}
                }
                
        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {e}")
            # Gemini 실패 시 에러 응답
            result = {
                "message": f"명령 처리 중 오류가 발생했습니다: {str(e)}",
                "action": "error",
                "entities": {},
                "result": {"error": str(e)}
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
# 현재는 POST 방식으로 /api/v1/commands/execute를 통해 백엔드에서 처리