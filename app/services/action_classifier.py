"""
작업 위험도 분류 및 확인 필요 여부 판단

명령어의 위험도를 분류하고, 사용자 확인 및 비용 추정이
필요한지 판단하는 모듈입니다.
"""

from enum import Enum
from typing import Dict, Any
import structlog

logger = structlog.get_logger(__name__)


class ActionRiskLevel(Enum):
    """작업 위험도"""
    LOW = "low"          # 조회만 (확인 불필요)
    MEDIUM = "medium"    # 스케일링, 재시작 (확인 + 비용 추정)
    HIGH = "high"        # 삭제, 롤백 (강력한 확인)


class ActionClassifier:
    """작업 위험도 분류기"""

    # 명령어별 위험도 매핑
    RISK_MAPPING: Dict[str, ActionRiskLevel] = {
        # 조회 명령어 (확인 불필요, LOW 위험)
        "status": ActionRiskLevel.LOW,
        "logs": ActionRiskLevel.LOW,
        "list_pods": ActionRiskLevel.LOW,
        "list_apps": ActionRiskLevel.LOW,
        "list_deployments": ActionRiskLevel.LOW,
        "list_services": ActionRiskLevel.LOW,
        "list_ingresses": ActionRiskLevel.LOW,
        "list_namespaces": ActionRiskLevel.LOW,
        "list_rollback": ActionRiskLevel.LOW,
        "get_service": ActionRiskLevel.LOW,
        "get_deployment": ActionRiskLevel.LOW,
        "endpoint": ActionRiskLevel.LOW,
        "overview": ActionRiskLevel.LOW,
        "cost_analysis": ActionRiskLevel.LOW,  # 비용 분석 (조회만)

        # 중간 위험 (비용 추정 + 확인, MEDIUM 위험)
        "scale": ActionRiskLevel.MEDIUM,
        "deploy": ActionRiskLevel.MEDIUM,
        "restart": ActionRiskLevel.MEDIUM,

        # 높은 위험 (강력한 확인 + 비용 추정, HIGH 위험)
        "rollback": ActionRiskLevel.HIGH,
        "delete": ActionRiskLevel.HIGH,
        "delete_service": ActionRiskLevel.HIGH,
        "delete_deployment": ActionRiskLevel.HIGH,
        "delete_pod": ActionRiskLevel.HIGH,
    }

    # 비용 추정이 필요한 명령어
    COST_ESTIMATION_COMMANDS = {
        "scale",      # 리소스 증가/감소
        "deploy",     # 새 배포 (빌드 비용)
        "delete",     # 리소스 제거 (절감 비용)
    }

    # 확인 메시지 템플릿
    CONFIRMATION_TEMPLATES = {
        "scale": {
            "title": "스케일링 확인",
            "icon": "📊",
            "message_template": "{deployment_name}을(를) {replicas}개로 조정하시겠습니까?"
        },
        "deploy": {
            "title": "배포 확인",
            "icon": "🚀",
            "message_template": "{owner}/{repo}를 배포하시겠습니까?"
        },
        "restart": {
            "title": "재시작 확인",
            "icon": "🔄",
            "message_template": "{deployment_name}을(를) 재시작하시겠습니까?"
        },
        "rollback": {
            "title": "롤백 확인",
            "icon": "⚠️",
            "message_template": "이전 버전으로 롤백하시겠습니까? 현재 서비스에 영향을 줄 수 있습니다."
        },
        "delete": {
            "title": "삭제 확인",
            "icon": "⛔",
            "message_template": "정말로 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다."
        }
    }

    def classify(self, command: str) -> ActionRiskLevel:
        """
        명령어 위험도 분류

        Args:
            command: 명령어 (예: "scale", "deploy")

        Returns:
            위험도 레벨
        """
        risk_level = self.RISK_MAPPING.get(
            command,
            ActionRiskLevel.MEDIUM  # 기본값: 중간 위험
        )

        logger.debug(
            "action_classified",
            command=command,
            risk_level=risk_level.value
        )

        return risk_level

    def requires_confirmation(self, command: str) -> bool:
        """
        확인 필요 여부 판단

        Args:
            command: 명령어

        Returns:
            확인이 필요하면 True
        """
        risk = self.classify(command)
        needs_confirmation = risk in [
            ActionRiskLevel.MEDIUM,
            ActionRiskLevel.HIGH
        ]

        logger.debug(
            "confirmation_check",
            command=command,
            requires_confirmation=needs_confirmation
        )

        return needs_confirmation

    def requires_cost_estimation(self, command: str) -> bool:
        """
        비용 추정 필요 여부 판단

        Args:
            command: 명령어

        Returns:
            비용 추정이 필요하면 True
        """
        needs_estimation = command in self.COST_ESTIMATION_COMMANDS

        logger.debug(
            "cost_estimation_check",
            command=command,
            requires_estimation=needs_estimation
        )

        return needs_estimation

    def get_confirmation_message(
        self,
        command: str,
        parameters: Dict[str, Any],
        cost_estimate: Dict[str, Any] = None
    ) -> str:
        """
        확인 메시지 생성

        Args:
            command: 명령어
            parameters: 명령어 파라미터
            cost_estimate: 비용 추정 결과 (선택)

        Returns:
            확인 메시지 문자열
        """
        template_info = self.CONFIRMATION_TEMPLATES.get(command)

        if not template_info:
            # 기본 메시지
            return f"{command} 작업을 진행하시겠습니까?"

        # 제목과 아이콘
        message_parts = [
            f"{template_info['icon']} **{template_info['title']}**\n"
        ]

        # 기본 메시지 (파라미터 포맷팅)
        try:
            formatted_message = template_info["message_template"].format(**parameters)
            message_parts.append(formatted_message)
        except KeyError:
            message_parts.append(template_info["message_template"])

        # 비용 정보 추가
        if cost_estimate:
            message_parts.append("\n\n**예상 비용:**")

            if "current" in cost_estimate and "target" in cost_estimate:
                message_parts.append(
                    f"- 현재: {cost_estimate.get('current')}대"
                )
                message_parts.append(
                    f"- 변경 후: {cost_estimate.get('target')}대"
                )

            if "additional_cost" in cost_estimate:
                additional = cost_estimate["additional_cost"]
                if additional > 0:
                    message_parts.append(
                        f"- 추가 비용: 월 {additional:,}원"
                    )
                elif additional < 0:
                    message_parts.append(
                        f"- 절감 비용: 월 {abs(additional):,}원"
                    )

            if "total_monthly" in cost_estimate:
                message_parts.append(
                    f"- 총 비용: 월 {cost_estimate['total_monthly']:,}원"
                )

        # 위험도별 추가 경고
        risk_level = self.classify(command)
        if risk_level == ActionRiskLevel.HIGH:
            message_parts.append(
                "\n\n⚠️ **주의**: 이 작업은 되돌릴 수 없습니다."
            )

        # 확인 안내
        message_parts.append(
            "\n\n계속 진행하시려면 '확인' 또는 '네'를 입력해주세요."
        )

        return "\n".join(message_parts)

    def validate_high_risk_confirmation(
        self,
        command: str,
        user_response: str
    ) -> bool:
        """
        고위험 작업의 확인 응답 검증

        HIGH 위험도 작업의 경우 더 엄격한 확인을 요구합니다.

        Args:
            command: 명령어
            user_response: 사용자 응답

        Returns:
            확인이 유효하면 True
        """
        risk_level = self.classify(command)

        # LOW, MEDIUM 위험은 간단한 확인
        if risk_level != ActionRiskLevel.HIGH:
            positive_responses = ["확인", "네", "yes", "y", "ok", "ㅇㅋ"]
            return user_response.strip().lower() in positive_responses

        # HIGH 위험은 정확한 확인 문구 요구
        if command == "delete":
            # 삭제는 "삭제 확인"을 정확히 입력해야 함
            return user_response.strip() == "삭제 확인"
        else:
            # 롤백 등은 "확인" 입력
            return user_response.strip() in ["확인", "롤백 확인"]

    def get_action_metadata(self, command: str) -> Dict[str, Any]:
        """
        작업 메타데이터 조회

        Args:
            command: 명령어

        Returns:
            메타데이터 딕셔너리
        """
        return {
            "risk_level": self.classify(command).value,
            "requires_confirmation": self.requires_confirmation(command),
            "requires_cost_estimation": self.requires_cost_estimation(command),
            "confirmation_template": self.CONFIRMATION_TEMPLATES.get(command)
        }
