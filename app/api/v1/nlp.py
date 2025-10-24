from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import uuid
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
            
            # 명령 히스토리에 추가
            command_id = str(uuid.uuid4())
            history_entry = CommandHistory(
                id=command_id,
                command=command,
                timestamp=datetime.now().isoformat(),
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

        # 2. 사용자 메시지 저장
        await conv_manager.add_message(
            user_id, session_id, "user", request.command
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
            
            # 명령어에 "○○" 같은 플레이스홀더가 있는지 확인
            if "○○" in request.command or "unknown" in request.command.lower():
                error_message = (
                    "❌ **명령어를 이해할 수 없습니다**\n\n"
                    "🔍 **올바른 사용법:**\n"
                    "• `K-Le-PaaS/test01 4개로 스케일링 해줘`\n"
                    "• `K-Le-PaaS/test01 롤백 목록 보여줘`\n"
                    "• `K-Le-PaaS/test01 상태 확인`\n"
                    "• `K-Le-PaaS/test01 로그 보여줘`\n\n"
                    "💡 **팁:** GitHub 저장소의 owner/repo 형식으로 입력해주세요"
                )
                
                # 구조화된 에러 데이터 생성
                error_data = {
                    "error_type": "missing_info",
                    "error_message": "프로젝트 정보가 불완전합니다",
                    "solutions": [
                        {
                            "title": "프로젝트 이름을 정확히 입력하세요",
                            "description": "GitHub 저장소의 owner/repo 형식으로 입력해주세요",
                            "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                        },
                        {
                            "title": "리포지토리 연결 확인",
                            "description": "GitHub에 연결된 프로젝트인지 확인해주세요",
                            "example": "owner/repo 롤백 목록"
                        }
                    ],
                    "supported_commands": [
                        {
                            "category": "롤백",
                            "name": "롤백 목록 조회",
                            "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                        },
                        {
                            "category": "배포",
                            "name": "애플리케이션 배포",
                            "example": "K-Le-PaaS/test01 배포해줘"
                        }
                    ]
                }
            else:
                error_message = (
                    "❌ **명령을 이해하지 못했습니다**\n\n"
                    "🔍 **지원하는 명령어:**\n"
                    "• **롤백**: `K-Le-PaaS/test01 롤백 목록 보여줘`\n"
                    "• **배포**: `K-Le-PaaS/test01 배포해줘`\n"
                    "• **Pod 관리**: `pod 목록 보여줘`\n"
                    "• **서비스 관리**: `service 목록 보여줘`\n\n"
                    "💡 **팁:** 구체적인 리소스 이름과 함께 명령어를 입력해주세요"
                )
                
                # 구조화된 에러 데이터 생성
                error_data = {
                    "error_type": "uninterpretable",
                    "error_message": "명령을 이해하지 못했습니다",
                    "solutions": [
                        {
                            "title": "명령어 형식을 확인하세요",
                            "description": "지원되는 명령어 형식으로 입력해주세요",
                            "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                        },
                        {
                            "title": "리소스 이름을 명확히 하세요",
                            "description": "구체적인 리소스 이름과 함께 명령어를 입력해주세요",
                            "example": "nginx-pod 로그 보여줘"
                        }
                    ],
                    "supported_commands": [
                        {
                            "category": "롤백",
                            "name": "롤백 목록 조회",
                            "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                        },
                        {
                            "category": "배포",
                            "name": "애플리케이션 배포",
                            "example": "K-Le-PaaS/test01 배포해줘"
                        },
                        {
                            "category": "Pod 관리",
                            "name": "Pod 목록 조회",
                            "example": "pod 목록 보여줘"
                        },
                        {
                            "category": "서비스 관리",
                            "name": "서비스 목록 조회",
                            "example": "service 목록 보여줘"
                        }
                    ]
                }
            
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
                result={
                    "type": "command_error",
                    "summary": error_message,
                    "data": {
                        "formatted": error_data,
                        "raw": {"command": request.command, "error": error_message}
                    },
                    "metadata": {
                        "error_type": error_data["error_type"],
                        "timestamp": datetime.now().isoformat(),
                        "command": request.command
                    }
                }
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

        # 6. 비용 추정 (필요시)
        cost_estimate = None
        if requires_cost:
            await conv_manager.update_state(
                user_id, session_id, ConversationState.ESTIMATING
            )

            if intent == "scale":
                # 현재 replicas 조회 (여기서는 가정, 실제로는 K8s에서 조회)
                current_replicas = 2  # TODO: K8s API로 조회
                target_replicas = entities.get("replicas", 3)

                cost_estimate = await estimator.estimate_scaling_cost(
                    current_replicas=current_replicas,
                    target_replicas=target_replicas,
                    db=db
                )

            elif intent == "deploy":
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

            # 확인 메시지 생성
            confirmation_message = classifier.get_confirmation_message(
                intent, entities, cost_estimate
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
                logger.error(f"명령 계획 실패: {str(e)}")
                await conv_manager.update_state(
                    user_id, session_id, ConversationState.ERROR
                )
                
                # ValueError를 새로운 에러 타입으로 변환
                error_message = str(e)
                
                # 에러 타입 결정
                if "프로젝트 정보가 필요합니다" in error_message:
                    error_type = "missing_info"
                    error_data = {
                        "error_type": "missing_info",
                        "error_message": "프로젝트 정보가 불완전합니다",
                        "solutions": [
                            {
                                "title": "프로젝트 이름을 정확히 입력하세요",
                                "description": "GitHub 저장소의 owner/repo 형식으로 입력해주세요",
                                "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                            },
                            {
                                "title": "리포지토리 연결 확인",
                                "description": "GitHub에 연결된 프로젝트인지 확인해주세요",
                                "example": "owner/repo 롤백 목록"
                            }
                        ],
                        "supported_commands": [
                            {
                                "category": "롤백",
                                "name": "롤백 목록 조회",
                                "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                            },
                            {
                                "category": "배포",
                                "name": "애플리케이션 배포",
                                "example": "K-Le-PaaS/test01 배포해줘"
                            }
                        ]
                    }
                else:
                    error_type = "uninterpretable"
                    error_data = {
                        "error_type": "uninterpretable",
                        "error_message": "명령을 이해하지 못했습니다",
                        "solutions": [
                            {
                                "title": "명령어 형식을 확인하세요",
                                "description": "지원되는 명령어 형식으로 입력해주세요",
                                "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                            },
                            {
                                "title": "리소스 이름을 명확히 하세요",
                                "description": "구체적인 리소스 이름과 함께 명령어를 입력해주세요",
                                "example": "nginx-pod 로그 보여줘"
                            }
                        ],
                        "supported_commands": [
                            {
                                "category": "롤백",
                                "name": "롤백 목록 조회",
                                "example": "K-Le-PaaS/test01 롤백 목록 보여줘"
                            },
                            {
                                "category": "배포",
                                "name": "애플리케이션 배포",
                                "example": "K-Le-PaaS/test01 배포해줘"
                            },
                            {
                                "category": "Pod 관리",
                                "name": "Pod 목록 조회",
                                "example": "pod 목록 보여줘"
                            },
                            {
                                "category": "서비스 관리",
                                "name": "서비스 목록 조회",
                                "example": "service 목록 보여줘"
                            }
                        ]
                    }
                
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
                    result={
                        "type": "command_error",
                        "summary": error_message,
                        "data": {
                            "formatted": error_data,
                            "raw": {"command": request.command, "error": error_message}
                        },
                        "metadata": {
                            "error_type": error_data["error_type"],
                            "timestamp": datetime.now().isoformat(),
                            "command": request.command
                        }
                    }
                )

            await conv_manager.update_state(
                user_id, session_id, ConversationState.COMPLETED
            )

            response_message = result.get("message", "작업이 완료되었습니다.")
            await conv_manager.add_message(
                user_id, session_id,
                "assistant", response_message,
                action="execution_completed"
            )

            return ConversationResponse(
                session_id=session_id,
                state=ConversationState.COMPLETED.value,
                message=response_message,
                requires_confirmation=False,
                cost_estimate=None,
                pending_action=None,
                result=result
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

        # 롤백 명령어인 경우 저장소 정보가 없으면 에러 메시지 개선
        if not github_owner or not github_repo:
            if command == "rollback":
                error_msg = (
                    "❌ **롤백할 저장소 정보가 없습니다**\n\n"
                    "🔍 **해결 방법:**\n"
                    "• `K-Le-PaaS/test01 롤백 목록 보여줘` - 먼저 롤백 목록을 확인하세요\n"
                    "• `K-Le-PaaS/test01 롤백해줘` - 저장소 정보와 함께 롤백 명령을 입력하세요\n\n"
                    "💡 **팁:** GitHub 저장소의 owner/repo 형식으로 입력해주세요"
                )
            else:
                error_msg = (
                    f"저장소 정보가 없습니다. 먼저 '저장소이름 롤백 목록' 명령으로 "
                    f"롤백할 저장소를 지정해주세요. (owner={github_owner}, repo={github_repo})"
                )
            logger.error(error_msg)
            raise HTTPException(400, error_msg)

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

        # 롤백 완료 시 특별한 메시지 처리
        if result.get('action') == 'ncp_rollback_to_previous' or result.get('action') == 'ncp_rollback_to_commit':
            # 롤백 성공 메시지 생성
            target_commit = result.get('target_commit_short', '')
            owner = result.get('owner', '')
            repo = result.get('repo', '')
            
            if target_commit:
                result_message = f"✅ 롤백이 성공적으로 완료되었습니다!\n\n"
                result_message += f"📦 **프로젝트**: {owner}/{repo}\n"
                result_message += f"🔄 **롤백된 커밋**: {target_commit}\n"
                result_message += f"🚀 **상태**: 배포 완료\n\n"
                result_message += f"이전 배포로 성공적으로 롤백되었습니다."
            else:
                result_message = f"✅ 롤백이 성공적으로 완료되었습니다!\n\n"
                result_message += f"📦 **프로젝트**: {owner}/{repo}\n"
                result_message += f"🚀 **상태**: 배포 완료\n\n"
                result_message += f"이전 배포로 성공적으로 롤백되었습니다."
        else:
            # 일반적인 작업 완료 메시지
            result_message = f"작업이 완료되었습니다: {result.get('message', '')}"
        
        await conv_manager.add_message(
            user_id, request.session_id,
            "assistant", result_message,
            action="execution_completed",
            metadata={"result": result}
        )

        return {
            "status": "completed",
            "message": result_message,
            "result": result,
            "session_id": request.session_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"확인 처리 실패: {str(e)}", exc_info=True)
        raise HTTPException(500, f"확인 처리 중 오류가 발생했습니다: {str(e)}")