"""
도메인 변경 대화형 플로우 관리

사용자와의 대화를 통해 안전하게 도메인을 변경합니다.
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from enum import Enum

from .pipeline_user_url import (
    validate_domain_format,
    check_domain_availability,
    get_all_deployment_urls_for_user,
    change_deployment_url,
    get_deployment_url
)

logger = logging.getLogger(__name__)


class DomainChangeStep(str, Enum):
    """도메인 변경 대화 단계"""
    INITIAL = "initial"  # 초기 상태
    SERVICE_SELECTION = "service_selection"  # 서비스 선택 대기
    DOMAIN_INPUT = "domain_input"  # 도메인 입력 대기
    CONFIRMATION = "confirmation"  # 최종 확인 대기
    COMPLETED = "completed"  # 완료
    CANCELLED = "cancelled"  # 취소


class DomainChangeConversation:
    """도메인 변경 대화 관리자"""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.step = DomainChangeStep.INITIAL
        self.context: Dict[str, Any] = {}

    async def process_message(
        self,
        user_message: str,
        extracted_entities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        사용자 메시지를 처리하고 다음 단계로 이동

        Args:
            user_message: 사용자 메시지
            extracted_entities: Gemini가 추출한 엔티티 (owner, repo 등)

        Returns:
            응답 딕셔너리 (message, next_step, options 등)
        """
        if self.step == DomainChangeStep.INITIAL:
            return await self._handle_initial(user_message, extracted_entities)

        elif self.step == DomainChangeStep.SERVICE_SELECTION:
            return await self._handle_service_selection(user_message)

        elif self.step == DomainChangeStep.DOMAIN_INPUT:
            return await self._handle_domain_input(user_message)

        elif self.step == DomainChangeStep.CONFIRMATION:
            return await self._handle_confirmation(user_message)

        else:
            return {
                "message": "대화가 완료되었거나 취소되었습니다.",
                "step": self.step,
                "completed": True
            }

    async def _handle_initial(
        self,
        user_message: str,
        extracted_entities: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """초기 단계: 서비스 특정 여부 확인"""

        # Gemini가 owner/repo/new_domain을 추출했는지 확인
        owner = extracted_entities.get("github_owner") if extracted_entities else None
        repo = extracted_entities.get("github_repo") if extracted_entities else None
        new_domain = extracted_entities.get("new_domain") if extracted_entities else None

        # Case 1: owner와 repo 모두 있음 - 바로 진행
        if owner and repo:
            # 서비스가 완전히 특정되었음
            self.context["owner"] = owner
            self.context["repo"] = repo

            # 현재 도메인 조회
            current_url_record = get_deployment_url(self.db, self.user_id, owner, repo)
            current_url = current_url_record.url if current_url_record else "없음"
            self.context["current_url"] = current_url

            # 새 도메인이 사전 지정되었는지 확인
            if new_domain and new_domain.strip():
                # 도메인이 지정됨 - 검증 후 확인 단계로 바로 이동
                return await self._process_new_domain(new_domain)

            # 도메인 미지정 - 입력 요청
            self.step = DomainChangeStep.DOMAIN_INPUT

            return {
                "message": f"**{owner}/{repo}** 서비스의 도메인을 변경하시겠습니까?\n\n"
                          f"📍 현재 도메인: `{current_url}`\n\n"
                          f"새로운 도메인을 입력하세요.\n"
                          f"형식: `https://(원하는이름).klepaas.app`\n\n"
                          f"예시:\n"
                          f"- `myapp`\n"
                          f"- `my-service`\n"
                          f"- `test-v2`\n\n"
                          f"_(취소하려면 '취소' 또는 '그만'을 입력하세요)_",
                "step": DomainChangeStep.DOMAIN_INPUT,
                "context": self.context,
                "completed": False
            }

        # Case 2: repo만 있음 (예: "test02 도메인 바꿔줘")
        elif repo and not owner:
            # 사용자의 모든 배포 목록 조회
            all_deployments = get_all_deployment_urls_for_user(self.db, self.user_id)

            if not all_deployments:
                return {
                    "message": "배포된 서비스가 없습니다. 먼저 서비스를 배포해주세요.",
                    "step": DomainChangeStep.CANCELLED,
                    "completed": True
                }

            # repo 이름으로 검색 (대소문자 무시, 부분 일치)
            repo_lower = repo.lower()
            matched_services = []

            for deployment in all_deployments:
                deployment_repo = deployment.github_repo.lower()
                # 정확 일치 또는 repo 이름이 포함된 경우
                if repo_lower == deployment_repo or repo_lower in deployment_repo:
                    matched_services.append({
                        "owner": deployment.github_owner,
                        "repo": deployment.github_repo,
                        "url": deployment.url
                    })

            # 정확히 1개 매칭 - 바로 진행
            if len(matched_services) == 1:
                service = matched_services[0]
                self.context["owner"] = service["owner"]
                self.context["repo"] = service["repo"]
                self.context["current_url"] = service["url"]

                # 새 도메인이 사전 지정되었는지 확인
                if new_domain and new_domain.strip():
                    # 도메인이 지정됨 - 검증 후 확인 단계로 바로 이동
                    return await self._process_new_domain(new_domain)

                # 도메인 미지정 - 입력 요청
                self.step = DomainChangeStep.DOMAIN_INPUT

                return {
                    "message": f"**{service['owner']}/{service['repo']}** 서비스를 찾았습니다!\n\n"
                              f"📍 현재 도메인: `{service['url']}`\n\n"
                              f"새로운 도메인을 입력하세요.\n"
                              f"형식: `https://(원하는이름).klepaas.app`\n\n"
                              f"예시:\n"
                              f"- `myapp`\n"
                              f"- `my-service`\n"
                              f"- `test-v2`\n\n"
                              f"_(취소하려면 '취소' 또는 '그만'을 입력하세요)_",
                    "step": DomainChangeStep.DOMAIN_INPUT,
                    "context": self.context,
                    "completed": False
                }

            # 여러 개 매칭 - 선택 요청
            elif len(matched_services) > 1:
                service_list = []
                for idx, service in enumerate(matched_services, 1):
                    service_list.append({
                        "index": idx,
                        "owner": service["owner"],
                        "repo": service["repo"],
                        "url": service["url"]
                    })

                self.context["service_list"] = service_list
                self.step = DomainChangeStep.SERVICE_SELECTION

                message_lines = [f"'{repo}' 이름과 일치하는 서비스가 여러 개 있습니다. 선택하세요:\n"]
                for service in service_list:
                    message_lines.append(
                        f"{service['index']}. **{service['owner']}/{service['repo']}**\n"
                        f"   현재 도메인: `{service['url']}`\n"
                    )
                message_lines.append("\n번호를 입력하세요.")
                message_lines.append("_(취소하려면 '취소' 또는 '그만'을 입력하세요)_")

                return {
                    "message": "\n".join(message_lines),
                    "step": DomainChangeStep.SERVICE_SELECTION,
                    "options": service_list,
                    "context": self.context,
                    "completed": False
                }

            # 매칭 없음 - 전체 목록 표시
            else:
                return await self._show_service_list()

        # Case 3: 아무것도 없음 - 전체 목록 표시
        else:
            # 서비스가 특정되지 않음 - 목록 보여주기
            return await self._show_service_list()

    async def _show_service_list(self) -> Dict[str, Any]:
        """사용자의 서비스 목록 보여주기"""

        deployments = get_all_deployment_urls_for_user(self.db, self.user_id)

        if not deployments:
            return {
                "message": "배포된 서비스가 없습니다. 먼저 서비스를 배포해주세요.",
                "step": DomainChangeStep.CANCELLED,
                "completed": True
            }

        # 서비스 목록 생성
        service_list = []
        for idx, deployment in enumerate(deployments, 1):
            service_list.append({
                "index": idx,
                "owner": deployment.github_owner,
                "repo": deployment.github_repo,
                "url": deployment.url
            })

        self.context["service_list"] = service_list
        self.step = DomainChangeStep.SERVICE_SELECTION

        # 메시지 생성
        message_lines = ["도메인을 변경할 서비스를 선택하세요:\n"]
        for service in service_list:
            message_lines.append(
                f"{service['index']}. **{service['owner']}/{service['repo']}**\n"
                f"   현재 도메인: `{service['url']}`\n"
            )
        message_lines.append("\n번호 또는 서비스 이름을 입력하세요.")
        message_lines.append("_(취소하려면 '취소' 또는 '그만'을 입력하세요)_")

        return {
            "message": "\n".join(message_lines),
            "step": DomainChangeStep.SERVICE_SELECTION,
            "options": service_list,
            "context": self.context,
            "completed": False
        }

    async def _handle_service_selection(self, user_message: str) -> Dict[str, Any]:
        """서비스 선택 처리"""

        # 취소 체크
        if user_message.lower() in ["취소", "그만", "cancel", "quit", "exit"]:
            self.step = DomainChangeStep.CANCELLED
            return {
                "message": "도메인 변경이 취소되었습니다.",
                "step": DomainChangeStep.CANCELLED,
                "completed": True
            }

        service_list = self.context.get("service_list", [])
        selected_service = None

        # 숫자로 선택
        if user_message.strip().isdigit():
            idx = int(user_message.strip())
            if 1 <= idx <= len(service_list):
                selected_service = service_list[idx - 1]
        else:
            # 이름으로 선택
            for service in service_list:
                if user_message.lower() in service["repo"].lower():
                    selected_service = service
                    break

        if not selected_service:
            return {
                "message": f"올바른 선택이 아닙니다. 1부터 {len(service_list)} 사이의 번호를 입력하거나 서비스 이름을 입력하세요.",
                "step": DomainChangeStep.SERVICE_SELECTION,
                "options": service_list,
                "completed": False
            }

        # 선택된 서비스 저장
        self.context["owner"] = selected_service["owner"]
        self.context["repo"] = selected_service["repo"]
        self.context["current_url"] = selected_service["url"]
        self.step = DomainChangeStep.DOMAIN_INPUT

        return {
            "message": f"**{selected_service['owner']}/{selected_service['repo']}** 서비스를 선택하셨습니다.\n\n"
                      f"📍 현재 도메인: `{selected_service['url']}`\n\n"
                      f"새로운 도메인을 입력하세요.\n"
                      f"형식: `https://(원하는이름).klepaas.app`\n\n"
                      f"예시:\n"
                      f"- `myapp`\n"
                      f"- `my-service`\n"
                      f"- `test-v2`\n\n"
                      f"_(취소하려면 '취소' 또는 '그만'을 입력하세요)_",
            "step": DomainChangeStep.DOMAIN_INPUT,
            "context": self.context,
            "completed": False
        }

    async def _handle_domain_input(self, user_message: str) -> Dict[str, Any]:
        """도메인 입력 처리"""

        # 취소 체크
        if user_message.lower() in ["취소", "그만", "cancel", "quit", "exit"]:
            self.step = DomainChangeStep.CANCELLED
            return {
                "message": "도메인 변경이 취소되었습니다.",
                "step": DomainChangeStep.CANCELLED,
                "completed": True
            }

        # 도메인 형식 검증
        validation_result = validate_domain_format(user_message)

        if not validation_result["valid"]:
            return {
                "message": f"❌ {validation_result['error']}\n\n다시 입력해주세요.",
                "step": DomainChangeStep.DOMAIN_INPUT,
                "completed": False
            }

        # 중복 체크
        availability = check_domain_availability(
            self.db,
            validation_result["full_domain"],
            exclude_user_id=self.user_id,
            exclude_owner=self.context.get("owner"),
            exclude_repo=self.context.get("repo")
        )

        if not availability["available"]:
            conflict = availability.get("conflict", {})
            return {
                "message": f"❌ 이미 사용 중인 도메인입니다.\n\n"
                          f"도메인: `https://{validation_result['full_domain']}`\n"
                          f"사용 중: `{conflict.get('github_owner')}/{conflict.get('github_repo')}`\n\n"
                          f"다른 도메인을 입력해주세요.",
                "step": DomainChangeStep.DOMAIN_INPUT,
                "completed": False
            }

        # 검증 성공 - 최종 확인 단계로
        self.context["new_domain"] = validation_result["full_domain"]
        self.context["new_url"] = f"https://{validation_result['full_domain']}"
        self.step = DomainChangeStep.CONFIRMATION

        return {
            "message": f"✅ 도메인 검증 완료!\n\n"
                      f"**변경 정보**\n"
                      f"- 서비스: `{self.context['owner']}/{self.context['repo']}`\n"
                      f"- 현재: `{self.context.get('current_url', '없음')}`\n"
                      f"- 변경: `{self.context['new_url']}`\n\n"
                      f"정말로 변경하시겠습니까?\n"
                      f"(예/네/yes 또는 아니오/no)",
            "step": DomainChangeStep.CONFIRMATION,
            "context": self.context,
            "completed": False
        }

    async def _process_new_domain(self, new_domain_input: str) -> Dict[str, Any]:
        """
        사전 지정된 도메인 처리 (검증 후 확인 단계로)

        Args:
            new_domain_input: 사용자가 지정한 새 도메인

        Returns:
            검증 결과 및 다음 단계 정보
        """
        # 도메인 형식 검증
        validation_result = validate_domain_format(new_domain_input)

        if not validation_result["valid"]:
            # 검증 실패 - 도메인 입력 단계로 돌아가기
            self.step = DomainChangeStep.DOMAIN_INPUT
            return {
                "message": f"❌ {validation_result['error']}\n\n"
                          f"새로운 도메인을 다시 입력하세요.\n"
                          f"형식: `https://(원하는이름).klepaas.app`\n\n"
                          f"예시:\n"
                          f"- `myapp`\n"
                          f"- `my-service`\n"
                          f"- `test-v2`\n\n"
                          f"_(취소하려면 '취소' 또는 '그만'을 입력하세요)_",
                "step": DomainChangeStep.DOMAIN_INPUT,
                "context": self.context,
                "completed": False
            }

        # 중복 체크
        availability = check_domain_availability(
            self.db,
            validation_result["full_domain"],
            exclude_user_id=self.user_id,
            exclude_owner=self.context.get("owner"),
            exclude_repo=self.context.get("repo")
        )

        if not availability["available"]:
            # 중복 발견 - 도메인 입력 단계로
            conflict = availability.get("conflict", {})
            self.step = DomainChangeStep.DOMAIN_INPUT
            return {
                "message": f"❌ 이미 사용 중인 도메인입니다.\n\n"
                          f"도메인: `https://{validation_result['full_domain']}`\n"
                          f"사용 중: `{conflict.get('github_owner')}/{conflict.get('github_repo')}`\n\n"
                          f"다른 도메인을 입력해주세요.\n"
                          f"_(취소하려면 '취소' 또는 '그만'을 입력하세요)_",
                "step": DomainChangeStep.DOMAIN_INPUT,
                "context": self.context,
                "completed": False
            }

        # 검증 성공 - 최종 확인 단계로
        self.context["new_domain"] = validation_result["full_domain"]
        self.context["new_url"] = f"https://{validation_result['full_domain']}"
        self.step = DomainChangeStep.CONFIRMATION

        return {
            "message": f"✅ 도메인 검증 완료!\n\n"
                      f"**변경 정보**\n"
                      f"- 서비스: `{self.context['owner']}/{self.context['repo']}`\n"
                      f"- 현재: `{self.context.get('current_url', '없음')}`\n"
                      f"- 변경: `{self.context['new_url']}`\n\n"
                      f"정말로 변경하시겠습니까?\n"
                      f"(예/네/yes 또는 아니오/no)",
            "step": DomainChangeStep.CONFIRMATION,
            "context": self.context,
            "completed": False
        }

    async def _handle_confirmation(self, user_message: str) -> Dict[str, Any]:
        """최종 확인 처리"""

        user_input = user_message.lower().strip()

        # 승인
        if user_input in ["예", "네", "yes", "y", "확인", "변경", "ok"]:
            try:
                # 실제 도메인 변경 수행
                result = await change_deployment_url(
                    owner=self.context["owner"],
                    repo=self.context["repo"],
                    new_domain=self.context["new_domain"],
                    db=self.db,
                    user_id=self.user_id
                )

                self.step = DomainChangeStep.COMPLETED

                return {
                    "message": f"🎉 도메인 변경이 완료되었습니다!\n\n"
                              f"**변경 내역**\n"
                              f"- 서비스: `{self.context['owner']}/{self.context['repo']}`\n"
                              f"- 이전: `{result.get('old_domain', '없음')}`\n"
                              f"- 변경: `{result['new_url']}`\n\n"
                              f"배포가 완료되면 새 URL로 접속할 수 있습니다.",
                    "step": DomainChangeStep.COMPLETED,
                    "result": result,
                    "completed": True
                }

            except Exception as e:
                logger.error(f"Domain change failed: {e}")
                self.step = DomainChangeStep.CANCELLED
                return {
                    "message": f"❌ 도메인 변경 중 오류가 발생했습니다.\n\n"
                              f"오류: {str(e)}",
                    "step": DomainChangeStep.CANCELLED,
                    "error": str(e),
                    "completed": True
                }

        # 거부
        elif user_input in ["아니오", "no", "n", "취소", "그만"]:
            self.step = DomainChangeStep.CANCELLED
            return {
                "message": "도메인 변경이 취소되었습니다.",
                "step": DomainChangeStep.CANCELLED,
                "completed": True
            }

        # 잘못된 입력
        else:
            return {
                "message": "예(yes) 또는 아니오(no)로 답변해주세요.",
                "step": DomainChangeStep.CONFIRMATION,
                "completed": False
            }


# 대화 세션 저장소 (Redis 대신 간단한 메모리 저장소 사용)
# 실제 프로덕션에서는 Redis 사용 권장
_conversation_sessions: Dict[str, DomainChangeConversation] = {}


def get_or_create_conversation(
    db: Session,
    user_id: str,
    conversation_id: Optional[str] = None
) -> tuple[DomainChangeConversation, str]:
    """
    대화 세션 가져오기 또는 생성

    Returns:
        (conversation, conversation_id)
    """
    import uuid

    if conversation_id and conversation_id in _conversation_sessions:
        return _conversation_sessions[conversation_id], conversation_id

    # 새 대화 생성
    conv_id = conversation_id or f"domain_change_{user_id}_{uuid.uuid4().hex[:8]}"
    conversation = DomainChangeConversation(db, user_id)
    _conversation_sessions[conv_id] = conversation

    return conversation, conv_id


def clear_conversation(conversation_id: str):
    """대화 세션 삭제"""
    if conversation_id in _conversation_sessions:
        del _conversation_sessions[conversation_id]
