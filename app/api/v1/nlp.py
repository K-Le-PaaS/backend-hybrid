from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import uuid
import json
from sqlalchemy.orm import Session

# commands.py 연동을 위한 import
from ...services.commands import CommandRequest, plan_command, execute_command
from ...database import get_db
from ...services.security import get_current_user_id, security

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
    timestamp: str  # ISO format string instead of datetime
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# 메모리 기반 명령 히스토리 (실제 환경에서는 데이터베이스 사용)
command_history: List[CommandHistory] = []

@router.post(
    "/nlp/process",
    response_model=CommandResponse,
    summary="Process natural language command",
    description="Processes a natural language command and executes the corresponding K8s or NCP operation. JWT token optional but recommended for user-specific operations.",
    responses={
        200: {"description": "Command processed successfully"},
        400: {"description": "Invalid command"},
        404: {"description": "Resource not found"},
    },
)
async def process_command(
    command_data: NaturalLanguageCommand,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    """
    자연어 명령을 처리합니다 (일반 K8s 명령 + 롤백 명령 지원).

    JWT 토큰이 있으면 인증된 사용자로, 없으면 'api_user'로 처리합니다.
    """
    try:
        # 디버깅: credentials 확인
        logger.info(f"Credentials received: {credentials is not None}")
        if credentials:
            logger.info(f"Token (first 20 chars): {credentials.credentials[:20]}...")

        # 사용자 ID 결정 (JWT 토큰 있으면 사용, 없으면 기본값)
        effective_user_id = user_id or "api_user"

        command = command_data.command.strip()
        logger.info(f"자연어 명령 처리 시작: {command} (user_id: {effective_user_id})")

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
                user_id=effective_user_id,  # 실제 사용자 ID 사용
                project_name=command_data.context.get("project_name", "default") if command_data.context else "default"
            )
            
            logger.info(f"Gemini 해석 결과: {gemini_result}")
            
            # 데이터베이스에 명령 히스토리 저장
            from ...services.command_history import save_command_history
            command_history_response = await save_command_history(
                db=db,
                command_text=command,
                tool="nlp_process",
                args={"intent": intent, "entities": entities},
                status="processing",
                user_id=effective_user_id
            )
            command_id = str(command_history_response.id)
            
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

                # user_id를 plan.args에 추가
                if not plan.args:
                    plan.args = {}
                plan.args["user_id"] = effective_user_id

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
        
        # 데이터베이스 히스토리 업데이트
        from ...services.command_history import update_command_status
        await update_command_status(
            db=db,
            command_id=int(command_id),
            status="completed",
            result=result
        )
        
        return CommandResponse(
            success=True,
            message="명령이 성공적으로 처리되었습니다.",
            data=result
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"명령 처리 실패: {str(e)}")
        
        # 에러 히스토리 업데이트
        if 'command_id' in locals():
            from ...services.command_history import update_command_status
            await update_command_status(
                db=db,
                command_id=int(command_id),
                status="failed",
                error_message=str(e)
            )
        
        return CommandResponse(
            success=False,
            message="명령 처리 중 오류가 발생했습니다.",
            error=str(e)
        )

@router.get("/nlp/history")
async def get_command_history(
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    """
    명령 히스토리를 조회합니다. (사용자 메시지만)
    """
    try:
        from ...services.command_history import get_command_history as get_command_history_service
        
        # 데이터베이스에서 명령 히스토리 조회 (사용자 메시지만)
        command_histories = await get_command_history_service(
            db=db,
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        # 사용자 메시지만 필터링 (tool이 "user_message"인 것만)
        user_messages = [ch for ch in command_histories if ch.tool == "user_message"]
        
        # CommandHistory 모델로 변환 (프론트엔드 인터페이스와 일치)
        return [
            {
                "id": ch.id,
                "command_text": ch.command_text,
                "tool": ch.tool,
                "args": ch.args,
                "result": ch.result,
                "status": ch.status,
                "error_message": ch.error_message,
                "user_id": ch.user_id,
                "created_at": ch.created_at.isoformat() if ch.created_at else datetime.now().isoformat(),
                "updated_at": ch.updated_at.isoformat() if ch.updated_at else datetime.now().isoformat()
            }
            for ch in user_messages
        ]
    except Exception as e:
        logger.error(f"명령 히스토리 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="명령 히스토리 조회에 실패했습니다.")

@router.get("/nlp/conversation-history")
async def get_conversation_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    """
    대화 히스토리를 조회합니다. (사용자 메시지와 AI 응답 모두)
    """
    try:
        from ...services.command_history import get_command_history as get_command_history_service
        
        # 데이터베이스에서 명령 히스토리 조회 (모든 메시지)
        command_histories = await get_command_history_service(
            db=db,
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        
        # 대화 히스토리는 오래된 순서로 정렬 (사용자 질문 → AI 응답 순서)
        command_histories.sort(key=lambda x: x.created_at)
        
        # CommandHistory 모델로 변환 (프론트엔드 인터페이스와 일치)
        return [
            {
                "id": ch.id,
                "command_text": ch.command_text,
                "tool": ch.tool,
                "args": ch.args,
                "result": ch.result,
                "status": ch.status,
                "error_message": ch.error_message,
                "user_id": ch.user_id,
                "created_at": ch.created_at.isoformat() if ch.created_at else datetime.now().isoformat(),
                "updated_at": ch.updated_at.isoformat() if ch.updated_at else datetime.now().isoformat()
            }
            for ch in command_histories
        ]
    except Exception as e:
        logger.error(f"대화 히스토리 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="대화 히스토리 조회에 실패했습니다.")

@router.get("/nlp/suggestions", response_model=List[str])
async def get_command_suggestions(context: Optional[str] = None):
    """
    명령 제안 목록을 조회합니다.
    """
    try:
        suggestions = [
            # Pod 관련 명령어
            "nginx pod 상태 확인해줘",
            "frontend-app pod 로그 50줄 보여줘",
            "api-service pod 재시작해줘",
            
            # Deployment 관련 명령어  
            "nginx deployment 스케일 3개로 늘려줘",
            "frontend-app deployment 롤백해줘",
            "backend deployment 배포해줘",
            
            # Service 관련 명령어
            "api-service endpoint 확인해줘",
            "web-service 정보 보여줘",
            
            # 리소스 목록 조회
            "모든 pod 목록 보여줘",
            "deployment 목록 확인해줘",
            "service 목록 보여줘",
            "namespace 목록 확인해줘",
            
            # 시스템 상태
            "클러스터 상태 확인해줘",
            "앱 목록 보여줘"
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


# ============================================================
# 대화형 인터랙션 API (Conversational Interaction)
# ============================================================

from ...services.conversation_manager import ConversationManager, ConversationState
from ...services.action_classifier import ActionClassifier
from ...services.cost_estimator import CostEstimator
from ...core.config import get_settings
import redis

# Redis 클라이언트 초기화 (싱글톤)
_redis_client = None

def get_redis_client():
    """Redis 클라이언트 가져오기"""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        redis_url = getattr(settings, 'redis_url', 'redis://localhost:6379')
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


class ConversationRequest(BaseModel):
    """대화형 명령 요청"""
    command: str
    session_id: Optional[str] = None
    timestamp: str
    context: Optional[Dict[str, Any]] = None


class ConversationResponse(BaseModel):
    """대화형 명령 응답"""
    session_id: str
    state: str
    message: str
    requires_confirmation: bool
    cost_estimate: Optional[Dict[str, Any]] = None
    pending_action: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None


class ConfirmationRequest(BaseModel):
    """확인 요청"""
    session_id: str
    confirmed: bool
    user_response: Optional[str] = None


@router.post(
    "/nlp/conversation",
    response_model=ConversationResponse,
    summary="Process conversational command",
    description="대화형 명령 처리 - 확인 메커니즘과 비용 추정을 포함한 멀티턴 대화 지원"
)
async def process_conversation(
    request: ConversationRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """
    대화형 명령 처리

    - 민감한 작업은 사용자 확인 요청
    - 비용이 발생하는 작업은 예상 비용 표시
    - Redis를 사용한 대화 세션 관리
    """
    try:
        redis_client = get_redis_client()
        conv_manager = ConversationManager(redis_client)
        classifier = ActionClassifier()
        estimator = CostEstimator(provider="NCP")

        # 1. 세션 생성 또는 조회
        session_id = request.session_id
        if not session_id:
            session_id = await conv_manager.create_session(user_id)
            logger.info(f"새 대화 세션 생성: {session_id}")
        else:
            session = await conv_manager.get_session(user_id, session_id)
            if not session:
                raise HTTPException(404, "세션을 찾을 수 없습니다")

        # 2. 사용자 메시지 저장 (Redis + DB)
        await conv_manager.add_message(
            user_id, session_id, "user", request.command
        )
        
        # 사용자 메시지를 command_history에 저장 (DB)
        from ...services.command_history import save_command_history
        await save_command_history(
            db=db,
            command_text=request.command,
            tool="user_message",
            args={"session_id": session_id, "action": "user_input"},
            status="completed",
            user_id=user_id
        )

        # 3. 상태 업데이트: INTERPRETING
        await conv_manager.update_state(
            user_id, session_id, ConversationState.INTERPRETING
        )

        # 4. Gemini로 명령 해석
        from ...llm.gemini import GeminiClient
        gemini_client = GeminiClient()

        try:
            interpretation = await gemini_client.interpret(
                prompt=request.command,
                user_id=user_id,
                project_name="default"
            )
        except Exception as e:
            logger.error(f"Gemini API 호출 실패: {str(e)}")
            # Gemini 실패 시 에러 응답 반환
            await conv_manager.update_state(
                user_id, session_id, ConversationState.ERROR
            )
            error_message = f"죄송합니다. AI 서비스에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해주세요.\n오류: {str(e)}"
            await conv_manager.add_message(
                user_id, session_id,
                "assistant", error_message,
                action="error"
            )
            return ConversationResponse(
                session_id=session_id,
                state=ConversationState.ERROR.value,
                message=error_message,
                requires_confirmation=False,
                cost_estimate=None,
                pending_action=None,
                result=None
            )

        intent = interpretation.get("intent")
        entities = interpretation.get("entities", {})

        # 세션 조회 (컨텍스트 복원용)
        session = await conv_manager.get_session(user_id, session_id)
        session_context = session.get("context", {}) if session else {}

        # owner/repo 정보 처리: entities에 있으면 저장, 없으면 컨텍스트에서 복원
        owner = entities.get("github_owner")
        repo = entities.get("github_repo")

        if owner and repo:
            # 새로 파싱된 정보를 컨텍스트에 저장
            await conv_manager.update_context(
                user_id, session_id,
                {"github_owner": owner, "github_repo": repo}
            )
            logger.info(f"저장소 정보 컨텍스트 저장: {owner}/{repo}")
        else:
            # 컨텍스트에서 복원 시도
            owner = session_context.get("github_owner")
            repo = session_context.get("github_repo")
            if owner and repo:
                # entities에 복원된 정보 추가
                entities["github_owner"] = owner
                entities["github_repo"] = repo
                logger.info(f"저장소 정보 컨텍스트에서 복원: {owner}/{repo}")
            else:
                logger.warning(f"저장소 정보 없음: intent={intent}, entities={entities}")

        # intent가 error인 경우 처리
        if intent == "error":
            logger.warning(f"명령 해석 실패: {request.command}")
            await conv_manager.update_state(
                user_id, session_id, ConversationState.ERROR
            )
            error_message = "죄송합니다. 명령을 이해하지 못했습니다. 다시 말씀해주시겠어요?"
            await conv_manager.add_message(
                user_id, session_id,
                "assistant", error_message,
                action="error"
            )
            return ConversationResponse(
                session_id=session_id,
                state=ConversationState.ERROR.value,
                message=error_message,
                requires_confirmation=False,
                cost_estimate=None,
                pending_action=None,
                result=None
            )

        logger.info(f"명령 해석 완료: intent={intent}, entities={entities}")

        # 5. 위험도 분류
        risk_level = classifier.classify(intent)
        requires_confirmation = classifier.requires_confirmation(intent)
        requires_cost = classifier.requires_cost_estimation(intent)

        logger.info(
            f"작업 분류: risk={risk_level.value}, "
            f"confirmation={requires_confirmation}, cost={requires_cost}"
        )

        # 6. 비용 추정 (필요시, 스케일링 제외)
        cost_estimate = None
        if requires_cost and intent != "scale":
            await conv_manager.update_state(
                user_id, session_id, ConversationState.ESTIMATING
            )

            if intent == "deploy":
                owner = entities.get("github_owner", "")
                repo = entities.get("github_repo", "")

                if owner and repo:
                    cost_estimate = await estimator.estimate_deployment_cost(
                        owner=owner,
                        repo=repo,
                        db=db
                    )

        # 7. 확인 필요 여부 판단
        if requires_confirmation:
            # 확인 대기 상태로 전환
            pending_action = {
                "type": intent,
                "parsed_intent": intent,
                "parameters": entities,
                "estimated_cost": cost_estimate,
                "risk_level": risk_level.value
            }

            await conv_manager.update_state(
                user_id,
                session_id,
                ConversationState.WAITING_CONFIRMATION,
                pending_action=pending_action
            )

            # 확인 메시지 생성 (스케일링 명령은 비용 정보 제외)
            show_cost_info = intent != "scale"
            confirmation_message = classifier.get_confirmation_message(
                intent, entities, cost_estimate, show_cost_info
            )

            await conv_manager.add_message(
                user_id, session_id,
                "assistant", confirmation_message,
                action="request_confirmation"
            )

            return ConversationResponse(
                session_id=session_id,
                state=ConversationState.WAITING_CONFIRMATION.value,
                message=confirmation_message,
                requires_confirmation=True,
                cost_estimate=cost_estimate,
                pending_action=pending_action,
                result=None
            )

        # 8. 바로 실행 (확인 불필요)
        else:
            await conv_manager.update_state(
                user_id, session_id, ConversationState.EXECUTING
            )

            # CommandRequest 생성 및 실행
            req = CommandRequest(
                command=intent,
                pod_name=entities.get("pod_name") or "",
                deployment_name=entities.get("deployment_name") or "",
                service_name=entities.get("service_name") or "",
                replicas=entities.get("replicas", 1),
                lines=entities.get("lines", 30),
                version=entities.get("version") or "",
                namespace=entities.get("namespace") or "default",
                previous=bool(entities.get("previous", False)),
                github_owner=entities.get("github_owner") or "",
                github_repo=entities.get("github_repo") or "",
                target_commit_sha=entities.get("target_commit_sha") or "",
                steps_back=entities.get("steps_back", 0)
            )

            try:
                plan = plan_command(req)
                result = await execute_command(plan)
            except ValueError as e:
                # 사용자 친화적인 에러 메시지
                error_message = str(e)
                await conv_manager.update_state(
                    user_id, session_id, ConversationState.COMPLETED
                )
                
                # 에러 메시지 저장
                await conv_manager.add_message(
                    user_id, session_id,
                    "assistant", error_message,
                    action="execution_failed",
                    metadata={"error": error_message}
                )
                
                # ConversationResponse에 에러 포함하여 반환
                return ConversationResponse(
                    session_id=session_id,
                    state=ConversationState.COMPLETED.value,
                    message=error_message,
                    requires_confirmation=False,
                    cost_estimate=None,
                    pending_action=None,
                    result={"error": error_message, "type": "command_error"}
                )
            
            await conv_manager.update_state(
                user_id, session_id, ConversationState.COMPLETED
            )

            # ResponseFormatter를 사용하여 결과 포맷팅
            from ...services.response_formatter import ResponseFormatter
            formatter = ResponseFormatter()
            
            # 스케일링 명령의 경우 특별 처리
            if intent == "scale":
                # 데이터베이스에서 이전 레플리카 개수 가져오기
                try:
                    from ...services.deployment_config import DeploymentConfigService
                    config_service = DeploymentConfigService()
                    github_owner = entities.get("github_owner", "")
                    github_repo = entities.get("github_repo", "")
                    db_old_replicas = config_service.get_replica_count(db, github_owner, github_repo)
                    logger.info(f"데이터베이스에서 가져온 이전 레플리카 개수: {db_old_replicas}")
                    
                    # result에 이전 레플리카 개수 추가
                    if "old_replicas" not in result or result.get("old_replicas", 0) == 0:
                        result["old_replicas"] = db_old_replicas
                        logger.info(f"result에 old_replicas 추가: {result['old_replicas']}")
                except Exception as e:
                    logger.error(f"데이터베이스에서 이전 레플리카 개수 가져오기 실패: {str(e)}")
                
                formatted_result = formatter.format_scale({
                    "k8s_result": result,
                    "entities": entities
                })
                response_message = formatted_result.get("summary", "스케일링이 완료되었습니다.")
            else:
                response_message = result.get("message", "작업이 완료되었습니다.")
            
            await conv_manager.add_message(
                user_id, session_id,
                "assistant", response_message,
                action="execution_completed",
                metadata={"result": formatted_result if intent == "scale" else result}
            )
            
            # 어시스턴트 응답을 command_history에 저장 (DB)
            # 스케일링의 경우 formatted_result를 저장, 그렇지 않으면 result 저장
            await save_command_history(
                db=db,
                command_text=response_message,
                tool="assistant_response",
                args={"session_id": session_id, "action": "execution_completed", "intent": intent, "entities": entities},
                result=formatted_result if intent == "scale" else result,
                status="completed",
                user_id=user_id
            )

            # 디버깅을 위한 로그 추가
            logger.info(f"ConversationResponse 생성 - intent: {intent}, formatted_result 존재: {formatted_result is not None if intent == 'scale' else 'N/A'}")
            if intent == "scale" and formatted_result:
                logger.info(f"formatted_result 내용: {formatted_result}")
            
            return ConversationResponse(
                session_id=session_id,
                state=ConversationState.COMPLETED.value,
                message=response_message,
                requires_confirmation=False,
                cost_estimate=None,
                pending_action=None,
                result=formatted_result if intent == "scale" else result  # 스케일링일 때만 formatted_result 사용
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"대화 처리 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"대화 처리 중 오류가 발생했습니다: {str(e)}")


@router.get(
    "/nlp/conversation/{session_id}/history",
    summary="Get conversation history",
    description="특정 세션의 대화 히스토리 조회"
)
async def get_conversation_history(
    session_id: str,
    limit: int = 50,
    user_id: str = Depends(get_current_user_id)
):
    """
    대화 히스토리 조회
    """
    try:
        redis_client = get_redis_client()
        conv_manager = ConversationManager(redis_client)

        session = await conv_manager.get_session(user_id, session_id)
        if not session:
            raise HTTPException(404, "세션을 찾을 수 없습니다")

        history = await conv_manager.get_conversation_history(
            user_id, session_id, limit=limit
        )


        return {
            "session_id": session_id,
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "state": session["state"],
            "message_count": len(history),
            "messages": history
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"히스토리 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"히스토리 조회 중 오류가 발생했습니다: {str(e)}")


@router.get(
    "/nlp/conversations",
    summary="List user conversations",
    description="사용자의 모든 대화 세션 목록 조회"
)
async def list_conversations(
    user_id: str = Depends(get_current_user_id)
):
    """
    사용자의 모든 대화 세션 목록
    """
    try:
        redis_client = get_redis_client()
        pattern = f"conversation:{user_id}:*"
        keys = redis_client.keys(pattern)

        sessions = []
        for key in keys:
            data = redis_client.get(key)
            if data:
                session = json.loads(data)
                sessions.append({
                    "session_id": session["session_id"],
                    "created_at": session["created_at"],
                    "updated_at": session["updated_at"],
                    "state": session["state"],
                    "message_count": len(session.get("conversation_history", [])),
                    "last_message": session.get("conversation_history", [])[-1] if session.get("conversation_history") else None
                })

        sessions.sort(key=lambda x: x["updated_at"], reverse=True)

        return {
            "user_id": user_id,
            "session_count": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"세션 목록 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"세션 목록 조회 중 오류가 발생했습니다: {str(e)}")


@router.delete(
    "/nlp/conversation/{session_id}",
    summary="Delete conversation",
    description="대화 세션 삭제"
)
async def delete_conversation(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    대화 세션 삭제
    """
    try:
        redis_client = get_redis_client()
        conv_manager = ConversationManager(redis_client)

        session = await conv_manager.get_session(user_id, session_id)
        if not session:
            raise HTTPException(404, "세션을 찾을 수 없습니다")

        await conv_manager.delete_session(user_id, session_id)

        return {
            "success": True,
            "message": "세션이 삭제되었습니다",
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"세션 삭제 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"세션 삭제 중 오류가 발생했습니다: {str(e)}")


@router.post(
    "/nlp/confirm",
    response_model=Dict[str, Any],
    summary="Confirm pending action",
    description="사용자 확인 응답 처리 - 대기 중인 작업을 승인하거나 거부"
)
async def confirm_action(
    request: ConfirmationRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """
    사용자 확인 응답 처리
    """
    try:
        redis_client = get_redis_client()
        conv_manager = ConversationManager(redis_client)
        classifier = ActionClassifier()

        # 1. 세션 조회
        session = await conv_manager.get_session(user_id, request.session_id)
        if not session:
            raise HTTPException(404, "세션을 찾을 수 없습니다")

        # 2. 상태 확인
        if session["state"] != ConversationState.WAITING_CONFIRMATION.value:
            raise HTTPException(400, "확인 대기 상태가 아닙니다")

        pending_action = session.get("pending_action")
        if not pending_action:
            raise HTTPException(400, "대기 중인 작업이 없습니다")

        # 3. 사용자 거부
        if not request.confirmed:
            await conv_manager.update_state(
                user_id, request.session_id, ConversationState.CANCELLED
            )

            cancel_message = "작업이 취소되었습니다."
            await conv_manager.add_message(
                user_id, request.session_id,
                "assistant", cancel_message,
                action="cancelled"
            )

            return {
                "status": "cancelled",
                "message": cancel_message,
                "session_id": request.session_id
            }

        # 4. 고위험 작업 검증 (사용자 응답 확인)
        command = pending_action["type"]
        if request.user_response:
            is_valid = classifier.validate_high_risk_confirmation(
                command, request.user_response
            )
            if not is_valid:
                error_msg = "확인 문구가 올바르지 않습니다. 정확히 입력해주세요."
                await conv_manager.add_message(
                    user_id, request.session_id,
                    "assistant", error_msg,
                    action="validation_failed"
                )
                return {
                    "status": "validation_failed",
                    "message": error_msg,
                    "session_id": request.session_id
                }

        # 5. 사용자 승인 → 실행
        await conv_manager.update_state(
            user_id, request.session_id, ConversationState.EXECUTING
        )

        # CommandRequest 생성
        params = pending_action["parameters"]

        # 세션 컨텍스트에서 owner/repo 복원 (파라미터에 없으면)
        context = session.get("context", {})
        github_owner = params.get("github_owner") or context.get("github_owner") or ""
        github_repo = params.get("github_repo") or context.get("github_repo") or ""

        logger.info(
            f"확인 처리 시 저장소 정보 확인: "
            f"owner={github_owner}, repo={github_repo}, "
            f"params.owner={params.get('github_owner')}, "
            f"context.owner={context.get('github_owner')}, "
            f"session_id={request.session_id}"
        )

        # 저장소 정보가 필요한 명령어만 체크 (deploy, scale, rollback 등)
        requires_github = command in ("deploy", "scale", "rollback")
        
        if requires_github and (not github_owner or not github_repo):
            error_msg = (
                f"저장소 정보가 없습니다. 먼저 '저장소이름 롤백 목록' 명령으로 "
                f"롤백할 저장소를 지정해주세요. (owner={github_owner}, repo={github_repo})"
            )
            logger.error(error_msg)
            raise HTTPException(400, error_msg)

        # 저장소 정보가 필요한 명령어일 때만 github_owner, github_repo 설정
        if requires_github:
            req = CommandRequest(
                command=pending_action["type"],
                pod_name=params.get("pod_name") or "",
                deployment_name=params.get("deployment_name") or "",
                service_name=params.get("service_name") or "",
                replicas=params.get("replicas", 1),
                lines=params.get("lines", 30),
                version=params.get("version") or "",
                namespace=params.get("namespace") or "default",
                previous=bool(params.get("previous", False)),
                github_owner=github_owner,
                github_repo=github_repo,
                target_commit_sha=params.get("target_commit_sha") or "",
                steps_back=params.get("steps_back") or 0
            )
        else:
            req = CommandRequest(
                command=pending_action["type"],
                pod_name=params.get("pod_name") or "",
                deployment_name=params.get("deployment_name") or "",
                service_name=params.get("service_name") or "",
                replicas=params.get("replicas", 1),
                lines=params.get("lines", 30),
                version=params.get("version") or "",
                namespace=params.get("namespace") or "default",
                previous=bool(params.get("previous", False)),
                github_owner="",
                github_repo="",
                target_commit_sha=params.get("target_commit_sha") or "",
                steps_back=params.get("steps_back") or 0
            )

        # 명령 실행
        plan = plan_command(req)

        # user_id를 plan.args에 추가
        if not plan.args:
            plan.args = {}
        plan.args["user_id"] = user_id

        result = await execute_command(plan)

        # 6. 완료 상태로 전환
        await conv_manager.update_state(
            user_id, request.session_id, ConversationState.COMPLETED
        )

        # 대기 중인 작업 제거
        await conv_manager.clear_pending_action(user_id, request.session_id)

        # ResponseFormatter를 사용하여 결과 포맷팅
        from ...services.response_formatter import ResponseFormatter
        formatter = ResponseFormatter()
        
        # 스케일링 명령의 경우 특별 처리
        if pending_action["type"] == "scale":
            # 디버깅을 위한 로그 추가
            logger.info(f"스케일링 결과 포맷팅 - result: {result}")
            logger.info(f"스케일링 결과 포맷팅 - params: {params}")
            
            # scale_deployment에서 이미 올바른 old_replicas를 반환하므로 추가로 덮어쓰지 않음
            # result.data에서 old_replicas를 추출하여 result에 추가
            if "data" in result and "old_replicas" in result["data"]:
                result["old_replicas"] = result["data"]["old_replicas"]
                logger.info(f"scale_deployment에서 반환된 old_replicas 사용: {result['old_replicas']}")
            
            formatted_result = formatter.format_scale({
                "k8s_result": result,
                "entities": params
            })
            logger.info(f"포맷된 결과: {formatted_result}")
            result_message = formatted_result.get("summary", "스케일링이 완료되었습니다.")
        else:
            result_message = f"작업이 완료되었습니다: {result.get('message', '')}"
        
        await conv_manager.add_message(
            user_id, request.session_id,
            "assistant", result_message,
            action="execution_completed",
            metadata={"result": formatted_result if pending_action["type"] == "scale" else result}
        )

        # 어시스턴트 응답을 command_history에 저장 (DB)
        # 스케일링의 경우 formatted_result를 저장, 그렇지 않으면 result 저장
        from ...services.command_history import save_command_history
        await save_command_history(
            db=db,
            command_text=result_message,
            tool="assistant_response",
            args={"session_id": request.session_id, "action": "execution_completed", "type": pending_action["type"], "parameters": params},
            result=formatted_result if pending_action["type"] == "scale" else result,
            status="completed",
            user_id=user_id
        )

        return {
            "status": "completed",
            "message": result_message,
            "result": formatted_result if pending_action["type"] == "scale" else result,
            "session_id": request.session_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"확인 처리 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"확인 처리 중 오류가 발생했습니다: {str(e)}")