"""
슬랙 통합 알림 서비스 (터미널 스타일)
모든 Slack 알림을 통합 관리하고 터미널 스타일 UI로 표시합니다.
"""

from typing import Dict, Any, Optional, List
from enum import Enum
import time
import requests
import structlog
from datetime import datetime
import httpx

from ..core.config import get_settings
from ..models.slack_events import (
    SlackEventType,
    SlackChannelType,
    SlackNotificationRequest,
    SlackNotificationResponse,
)
from .slack_template_builder import SlackTemplateBuilder

logger = structlog.get_logger(__name__)


class NotificationPriority(str, Enum):
    """알림 우선순위"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SlackNotificationService:
    """슬랙 통합 알림 서비스 - 터미널 스타일"""

    def __init__(self, webhook_url: Optional[str] = None):
        self.settings = get_settings()
        self.webhook_url = webhook_url or self.settings.slack_webhook_url
        self.logger = logger.bind(service="slack_notification")
        self.template_builder = SlackTemplateBuilder()

    # ============================================================
    # 배포 관련 알림 (터미널 스타일)
    # ============================================================

    def send_deployment_started(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        branch: str = "main",
        channel: Optional[str] = None
    ) -> None:
        """배포 시작 알림 전송 (터미널 스타일)"""
        try:
            # Use Jinja template for consistent fixed-width rendering
            payload = self.template_builder.build_deployment_notification(
                notification_type="started",
                repo=repo,
                commit_sha=commit_sha,
                commit_message=commit_message,
                author=author,
                deployment_id=deployment_id,
                branch=branch,
                timestamp=int(time.time())
            )
            self._send_to_slack(payload, channel)
            self.logger.info(
                "deployment_started_notification_sent",
                deployment_id=deployment_id,
                repo=repo
            )
        except Exception as e:
            self.logger.error(
                "failed_to_send_deployment_started",
                error=str(e),
                deployment_id=deployment_id
            )

    def send_deployment_success(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        duration_seconds: int,
        branch: str = "main",
        app_url: Optional[str] = None,
        logs: Optional[List[str]] = None,
        channel: Optional[str] = None
    ) -> None:
        """배포 성공 알림 전송 (터미널 스타일)"""
        try:
            # Prefer Jinja template for consistent alignment across fonts
            payload = self.template_builder.build_deployment_notification(
                notification_type="success",
                repo=repo,
                commit_sha=commit_sha,
                commit_message=commit_message,
                author=author,
                deployment_id=deployment_id,
                duration_seconds=duration_seconds,
                branch=branch,
                app_url=app_url,
                logs=logs,
                timestamp=int(time.time())
            )
            self._send_to_slack(payload, channel)
            self.logger.info(
                "deployment_success_notification_sent",
                deployment_id=deployment_id,
                repo=repo,
                duration=duration_seconds
            )
        except Exception as e:
            self.logger.error(
                "failed_to_send_deployment_success",
                error=str(e),
                deployment_id=deployment_id
            )

    def send_deployment_failed(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        duration_seconds: int,
        error_message: str,
        branch: str = "main",
        logs: Optional[List[str]] = None,
        channel: Optional[str] = None
    ) -> None:
        """배포 실패 알림 전송 (터미널 스타일)"""
        try:
            # Use centralized template to avoid width drift
            payload = self.template_builder.build_deployment_notification(
                notification_type="failed",
                repo=repo,
                commit_sha=commit_sha,
                commit_message=commit_message,
                author=author,
                deployment_id=deployment_id,
                duration_seconds=duration_seconds,
                error_message=error_message,
                branch=branch,
                logs=logs,
                timestamp=int(time.time())
            )
            self._send_to_slack(payload, channel)
            self.logger.info(
                "deployment_failed_notification_sent",
                deployment_id=deployment_id,
                repo=repo,
                error=error_message[:100]
            )
        except Exception as e:
            self.logger.error(
                "failed_to_send_deployment_failed",
                error=str(e),
                deployment_id=deployment_id
            )

    # ============================================================
    # 이벤트 기반 알림 (통합 API)
    # ============================================================

    async def send_notification(
        self,
        event_type: SlackEventType,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
        channel_type: Optional[SlackChannelType] = None,
        priority: str = "normal"
    ) -> SlackNotificationResponse:
        """통합 알림 전송 (이벤트 기반 라우팅)"""
        try:
            # 배포 이벤트는 터미널 스타일로 변환
            if event_type in [SlackEventType.DEPLOYMENT_STARTED,
                            SlackEventType.DEPLOYMENT_SUCCESS,
                            SlackEventType.DEPLOYMENT_FAILED]:
                return await self._send_deployment_event(
                    event_type, title, message, context, channel
                )

            # 기타 이벤트는 기본 포맷
            return await self.send_custom_notification(
                event_type, title, message, context, channel, channel_type, priority
            )

        except Exception as e:
            self.logger.error(
                "notification_failed",
                error=str(e),
                event_type=event_type
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_custom_notification(
        self,
        event_type: SlackEventType,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
        channel_type: Optional[SlackChannelType] = None,
        priority: str = "normal"
    ) -> SlackNotificationResponse:
        """사용자 정의 알림을 전송합니다."""
        try:
            # 채널 결정
            target_channel = channel or self._determine_channel(channel_type, event_type)

            # 메시지 포맷팅
            formatted_message = f"*{title}*\n\n{message}"

            # 컨텍스트 정보 추가
            if context:
                for key, value in context.items():
                    if key not in ["title", "message"]:
                        formatted_message += f"\n**{key}**: {value}"

            # 웹훅으로 전송
            payload = {
                "text": formatted_message,
                "channel": target_channel
            }

            self._send_to_slack(payload, target_channel)

            self.logger.info(
                "custom_notification_sent",
                event_type=event_type,
                title=title,
                success=True
            )

            return SlackNotificationResponse(
                success=True,
                channel=target_channel,
                message_ts="webhook_success"
            )

        except Exception as e:
            self.logger.error(
                "custom_notification_failed",
                error=str(e),
                event_type=event_type,
                title=title
            )
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    async def send_simple_message(
        self,
        title: str,
        message: str,
        channel: Optional[str] = None
    ) -> SlackNotificationResponse:
        """간단한 메시지를 직접 전송합니다."""
        try:
            # 채널 결정
            target_channel = channel or self.settings.slack_alert_channel_default or "#general"

            # 메시지 포맷팅
            formatted_message = f"*{title}*\n\n{message}"

            # 웹훅으로 전송
            payload = {
                "text": formatted_message,
                "channel": target_channel
            }

            self._send_to_slack(payload, target_channel)

            self.logger.info("simple_message_sent", title=title, success=True)
            return SlackNotificationResponse(
                success=True,
                channel=target_channel,
                message_ts="webhook_success"
            )

        except Exception as e:
            self.logger.error("simple_message_failed", title=title, error=str(e))
            return SlackNotificationResponse(
                success=False,
                channel=channel or "unknown",
                error=f"Unexpected error: {e}"
            )

    # ============================================================
    # 내부 헬퍼 메서드
    # ============================================================

    async def _send_deployment_event(
        self,
        event_type: SlackEventType,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]],
        channel: Optional[str]
    ) -> SlackNotificationResponse:
        """배포 이벤트를 터미널 스타일로 변환하여 전송"""
        ctx = context or {}

        # 필수 정보 추출
        repo = ctx.get("app_name", "unknown")
        commit_sha = ctx.get("deployment_id", "latest")
        commit_message = message
        author = ctx.get("user", "system")
        deployment_id = ctx.get("deployment_id", 0)
        branch = ctx.get("environment", "main")

        try:
            if event_type == SlackEventType.DEPLOYMENT_STARTED:
                self.send_deployment_started(
                    repo=repo,
                    commit_sha=str(commit_sha),
                    commit_message=commit_message,
                    author=author,
                    deployment_id=deployment_id,
                    branch=branch,
                    channel=channel
                )
            elif event_type == SlackEventType.DEPLOYMENT_SUCCESS:
                self.send_deployment_success(
                    repo=repo,
                    commit_sha=str(commit_sha),
                    commit_message=commit_message,
                    author=author,
                    deployment_id=deployment_id,
                    duration_seconds=ctx.get("duration", 0),
                    branch=branch,
                    app_url=ctx.get("app_url"),
                    channel=channel
                )
            elif event_type == SlackEventType.DEPLOYMENT_FAILED:
                self.send_deployment_failed(
                    repo=repo,
                    commit_sha=str(commit_sha),
                    commit_message=commit_message,
                    author=author,
                    deployment_id=deployment_id,
                    duration_seconds=ctx.get("duration", 0),
                    error_message=ctx.get("error_message", "Unknown error"),
                    branch=branch,
                    channel=channel
                )

            return SlackNotificationResponse(
                success=True,
                channel=channel or "#general",
                message_ts="webhook_success"
            )
        except Exception as e:
            return SlackNotificationResponse(
                success=False,
                channel=channel or "#general",
                error=str(e)
            )

    def _determine_channel(
        self,
        channel_type: Optional[SlackChannelType],
        event_type: SlackEventType
    ) -> str:
        """알림을 보낼 채널을 결정합니다."""
        # 이벤트 타입별 채널 매핑
        if event_type in [SlackEventType.RATE_LIMITED] and self.settings.slack_alert_channel_rate_limited:
            return self.settings.slack_alert_channel_rate_limited

        if event_type in [SlackEventType.UNAUTHORIZED] and self.settings.slack_alert_channel_unauthorized:
            return self.settings.slack_alert_channel_unauthorized

        # 채널 타입별 기본 채널
        if channel_type == SlackChannelType.ERRORS:
            return self.settings.slack_alert_channel_rate_limited or "#alerts"
        elif channel_type == SlackChannelType.SECURITY:
            return self.settings.slack_alert_channel_unauthorized or "#security"

        # 기본 채널
        return self.settings.slack_alert_channel_default or "#general"

    def _get_priority_for_event(self, event_type: SlackEventType) -> str:
        """이벤트 타입에 따른 우선순위를 반환합니다."""
        high_priority_events = {
            SlackEventType.DEPLOYMENT_FAILED,
            SlackEventType.BUILD_FAILED,
            SlackEventType.UNAUTHORIZED,
            SlackEventType.SYSTEM_ERROR,
            SlackEventType.HEALTH_DOWN
        }

        urgent_events = {
            SlackEventType.UNAUTHORIZED,
            SlackEventType.SYSTEM_ERROR
        }

        if event_type in urgent_events:
            return NotificationPriority.URGENT.value
        elif event_type in high_priority_events:
            return NotificationPriority.HIGH.value
        else:
            return NotificationPriority.NORMAL.value

    # ============================================================
    # 터미널 스타일 페이로드 빌더
    # ============================================================

    @staticmethod
    def _display_width(text: str) -> int:
        """Return display width using wcwidth if available, else fallback.
        This handles emoji and East Asian widths more accurately.
        """
        try:
            from wcwidth import wcwidth  # type: ignore
        except Exception:
            wcwidth = None
        width = 0
        for ch in text or "":
            if ch in ('\u200d', '\ufe0f'):
                continue
            if wcwidth:
                w = wcwidth(ch)
                width += max(w, 0)
            else:
                import unicodedata
                eaw = unicodedata.east_asian_width(ch)
                width += 2 if eaw in ('W', 'F') else 1
        return width

    def _build_deployment_started(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        branch: str
    ) -> Dict[str, Any]:
        """배포 시작 알림 페이로드 생성 (터미널 스타일) - DEPRECATED: Use template_builder instead"""
        import warnings
        warnings.warn(
            "_build_deployment_started is deprecated. Use template_builder.build_deployment_notification instead.",
            DeprecationWarning,
            stacklevel=2
        )
        commit_short = commit_sha[:7]
        timestamp = int(time.time())

        # 커밋 메시지 첫 줄만 추출
        commit_first_line = commit_message.split('\n')[0] if commit_message else "No commit message"

        # 각 줄의 내용 구성 (박스 내부 너비: 60자)
        box_width = 60
        # 동적 헤더/푸터: 본문 폭과 정확히 일치하도록 생성
        title = "DEPLOYMENT INITIATED"
        title_segment = f" {title} "
        left = "┌"  # 헤더 좌측 선은 추가 ─ 없이 시작
        fill = "─" * (box_width - len(title_segment))
        header_line = f"{left}{title_segment}{fill}┐"
        # 헤더가 좌측 추가 ─ 없이 생성되므로, 푸터도 동일 길이가 되도록 box_width 만큼 + 오른쪽 경계만 추가
        footer_line = "└" + ("─" * (box_width)) + "┘"

        # Repository 줄
        repo_label = "Repository:    "
        repo_content = repo
        repo_padding = max(0, box_width - len(repo_label) - self._display_width(repo_content))
        repo_line = f"│ {repo_label}{repo_content}{' ' * repo_padding}│"

        # Branch 줄
        branch_label = "Branch:        "
        branch_content = branch
        branch_padding = max(0, box_width - len(branch_label) - self._display_width(branch_content))
        branch_line = f"│ {branch_label}{branch_content}{' ' * branch_padding}│"

        # Commit 줄 (특수 처리 - 괄호 안 메시지)
        commit_label = "Commit:        "
        commit_content = f"{commit_short} ({commit_first_line[:30]})"
        if len(commit_content) > 44:
            commit_content = commit_content[:41] + "..."
        commit_padding = max(0, box_width - len(commit_label) - self._display_width(commit_content))
        commit_line = f"│ {commit_label}{commit_content}{' ' * commit_padding}│"

        # Author 줄
        author_label = "Author:        "
        author_content = author
        author_padding = max(0, box_width - len(author_label) - self._display_width(author_content))
        author_line = f"│ {author_label}{author_content}{' ' * author_padding}│"

        # Deploy ID 줄
        deploy_label = "Deploy ID:     "
        deploy_content = f"#{deployment_id}"
        deploy_padding = max(0, box_width - len(deploy_label) - self._display_width(deploy_content))
        deploy_line = f"│ {deploy_label}{deploy_content}{' ' * deploy_padding}│"

        # Status 줄 (emoji 포함 유지)
        status_label = "Status:        "
        status_content = "🔄 IN PROGRESS"
        status_padding = max(0, box_width - len(status_label) - self._display_width(status_content))
        status_line = f"│ {status_label}{status_content}{' ' * status_padding}│"

        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "```\n╔════════════════════════════════════════════════════════════╗\n║               K-LE-PAAS DEPLOYMENT SYSTEM                  ║\n╚════════════════════════════════════════════════════════════╝\n```"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"```\n$ k-le-paas deploy start --repo {repo} --branch {branch}\n\n{header_line}\n{repo_line}\n{branch_line}\n{commit_line}\n{author_line}\n{deploy_line}\n{status_line}\n{footer_line}\n\n[INFO] Initializing deployment pipeline...\n[INFO] ⠿ Validating configuration\n[INFO] ⠿ Building container image\n[INFO] ⠿ Running pre-deployment tests\n[INFO] ⠿ Preparing deployment manifest\n\n⏳ Deployment in progress... Please wait.\n```"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"🚀 Started <!date^{timestamp}^{{date_short_pretty}} at {{time}}|just now> | Track progress in real-time"
                        }
                    ]
                }
            ]
        }

    def _build_deployment_success(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        duration_seconds: int,
        branch: str,
        app_url: Optional[str],
        logs: Optional[List[str]]
    ) -> Dict[str, Any]:
        """배포 성공 알림 페이로드 생성 (터미널 스타일) - DEPRECATED: Use template_builder instead"""
        import warnings
        warnings.warn(
            "_build_deployment_success is deprecated. Use template_builder.build_deployment_notification instead.",
            DeprecationWarning,
            stacklevel=2
        )
        commit_short = commit_sha[:7]
        timestamp = int(time.time())

        # 소요시간 포맷팅
        minutes, seconds = divmod(duration_seconds, 60)
        duration_str = f"{minutes:02d}:{seconds:02d}" if minutes > 0 else f"00:{seconds:02d}"

        # 커밋 메시지 첫 줄만 추출
        commit_first_line = commit_message.split('\n')[0] if commit_message else "No commit message"

        # 각 줄의 내용 구성 (박스 내부 너비: 60자)
        box_width = 60

        # Repository 줄
        repo_label = "Repository:    "
        repo_content = repo
        repo_padding = box_width - len(repo_label) - len(repo_content)
        repo_line = f"│ {repo_label}{repo_content}{' ' * repo_padding}│"

        # Branch 줄
        branch_label = "Branch:        "
        branch_content = branch
        branch_padding = box_width - len(branch_label) - len(branch_content)
        branch_line = f"│ {branch_label}{branch_content}{' ' * branch_padding}│"

        # Commit 줄
        commit_label = "Commit:        "
        commit_content = f"{commit_short} ({commit_first_line[:30]})"
        if len(commit_content) > 44:
            commit_content = commit_content[:41] + "..."
        commit_padding = box_width - len(commit_label) - len(commit_content)
        commit_line = f"│ {commit_label}{commit_content}{' ' * commit_padding}│"

        # Author 줄
        author_label = "Author:        "
        author_content = author
        author_padding = box_width - len(author_label) - len(author_content)
        author_line = f"│ {author_label}{author_content}{' ' * author_padding}│"

        # Deploy ID 줄
        deploy_label = "Deploy ID:     "
        deploy_content = f"#{deployment_id}"
        deploy_padding = box_width - len(deploy_label) - len(deploy_content)
        deploy_line = f"│ {deploy_label}{deploy_content}{' ' * deploy_padding}│"

        # Duration 줄
        duration_label = "Duration:      "
        duration_content = f"{duration_str} ({duration_seconds}s)"
        duration_padding = box_width - len(duration_label) - self._display_width(duration_content)
        duration_line = f"│ {duration_label}{duration_content}{' ' * duration_padding}│"

        # 로그 포맷팅 (최근 10줄만)
        log_section = ""
        if logs and len(logs) > 0:
            log_lines = logs[-10:]  # 마지막 10줄
            log_section = "\n\n[INFO] Deployment logs (last 10 lines):\n" + "\n".join(
                f"  │ {line[:55]}" for line in log_lines
            )

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "```\n╔════════════════════════════════════════════════════════════╗\n║               K-LE-PAAS DEPLOYMENT SYSTEM                  ║\n╚════════════════════════════════════════════════════════════╝\n```"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```\n$ k-le-paas deploy complete --id {deployment_id}\n\n┌─ ✅ DEPLOYMENT SUCCESSFUL ─────────────────────────────────┐\n{repo_line}\n{branch_line}\n{commit_line}\n{author_line}\n{deploy_line}\n{duration_line}\n└────────────────────────────────────────────────────────────┘\n\n[SUCCESS] ✓ Configuration validated      (5s)\n[SUCCESS] ✓ Container image built        ({int(duration_seconds * 0.35)}s)\n[SUCCESS] ✓ Tests passed                 ({int(duration_seconds * 0.25)}s)\n[SUCCESS] ✓ Deployment manifest applied  ({int(duration_seconds * 0.20)}s)\n[SUCCESS] ✓ Health checks passed         ({int(duration_seconds * 0.20)}s){log_section}\n\n[INFO] Application is LIVE and serving traffic ✨\n[INFO] All monitoring checks: PASSED 💚\n\nExit code: 0 (SUCCESS)\n```"
                }
            }
        ]

        # 앱 URL 버튼 추가
        if app_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🌐 Launch Application",
                            "emoji": True
                        },
                        "url": app_url,
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 View Metrics",
                            "emoji": True
                        },
                        "url": f"{app_url}/metrics" if app_url else "https://monitoring.example.com"
                    }
                ]
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"✅ Completed <!date^{timestamp}^{{date_short_pretty}} at {{time}}|just now> by *{author}* | Deployment #{deployment_id}"
                }
            ]
        })

        return {"blocks": blocks}

    def _build_deployment_failed(
        self,
        repo: str,
        commit_sha: str,
        commit_message: str,
        author: str,
        deployment_id: int,
        duration_seconds: int,
        error_message: str,
        branch: str,
        logs: Optional[List[str]]
    ) -> Dict[str, Any]:
        """배포 실패 알림 페이로드 생성 (터미널 스타일) - DEPRECATED: Use template_builder instead"""
        import warnings
        warnings.warn(
            "_build_deployment_failed is deprecated. Use template_builder.build_deployment_notification instead.",
            DeprecationWarning,
            stacklevel=2
        )
        commit_short = commit_sha[:7]
        timestamp = int(time.time())

        # 소요시간 포맷팅
        minutes, seconds = divmod(duration_seconds, 60)
        duration_str = f"{minutes:02d}:{seconds:02d}" if minutes > 0 else f"00:{seconds:02d}"

        # 커밋 메시지 첫 줄만 추출
        commit_first_line = commit_message.split('\n')[0] if commit_message else "No commit message"

        # 각 줄의 내용 구성 (박스 내부 너비: 60자)
        box_width = 60

        # Repository 줄
        repo_label = "Repository:    "
        repo_content = repo
        repo_padding = box_width - len(repo_label) - len(repo_content)
        repo_line = f"│ {repo_label}{repo_content}{' ' * repo_padding}│"

        # Branch 줄
        branch_label = "Branch:        "
        branch_content = branch
        branch_padding = box_width - len(branch_label) - len(branch_content)
        branch_line = f"│ {branch_label}{branch_content}{' ' * branch_padding}│"

        # Commit 줄
        commit_label = "Commit:        "
        commit_content = f"{commit_short} ({commit_first_line[:30]})"
        if len(commit_content) > 44:
            commit_content = commit_content[:41] + "..."
        commit_padding = box_width - len(commit_label) - len(commit_content)
        commit_line = f"│ {commit_label}{commit_content}{' ' * commit_padding}│"

        # Author 줄
        author_label = "Author:        "
        author_content = author
        author_padding = box_width - len(author_label) - len(author_content)
        author_line = f"│ {author_label}{author_content}{' ' * author_padding}│"

        # Deploy ID 줄
        deploy_label = "Deploy ID:     "
        deploy_content = f"#{deployment_id}"
        deploy_padding = box_width - len(deploy_label) - len(deploy_content)
        deploy_line = f"│ {deploy_label}{deploy_content}{' ' * deploy_padding}│"

        # Duration 줄
        duration_label = "Duration:      "
        duration_content = f"{duration_str} ({duration_seconds}s)"
        duration_padding = box_width - len(duration_label) - len(duration_content)
        duration_line = f"│ {duration_label}{duration_content}{' ' * duration_padding}│"

        # 에러 메시지 포맷팅 (첫 3줄만)
        error_lines = error_message.split('\n')[:3]
        error_display = "\n".join(f"  │ {line[:55]}" for line in error_lines)

        # 로그 포맷팅 (최근 5줄만)
        log_section = ""
        if logs and len(logs) > 0:
            log_lines = logs[-5:]  # 마지막 5줄
            log_section = "\n\n[ERROR] Recent logs:\n" + "\n".join(
                f"  │ {line[:55]}" for line in log_lines
            )

        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "```\n╔════════════════════════════════════════════════════════════╗\n║               K-LE-PAAS DEPLOYMENT SYSTEM                  ║\n╚════════════════════════════════════════════════════════════╝\n```"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"```\n$ k-le-paas deploy failed --id {deployment_id}\n\n┌─ ❌ DEPLOYMENT FAILED ─────────────────────────────────────┐\n{repo_line}\n{branch_line}\n{commit_line}\n{author_line}\n{deploy_line}\n{duration_line}\n└────────────────────────────────────────────────────────────┘\n\n[ERROR] Deployment failed with errors:\n{error_display}{log_section}\n\n[ERROR] Deployment aborted 💥\n[INFO] Rolling back to previous stable version...\n\nExit code: 1 (FAILED)\n```"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"❌ Failed <!date^{timestamp}^{{date_short_pretty}} at {{time}}|just now> by *{author}* | Deployment #{deployment_id}"
                        }
                    ]
                }
            ]
        }

    def _send_to_slack(self, payload: Dict[str, Any], channel: Optional[str] = None) -> None:
        """슬랙 웹훅으로 전송"""
        if not self.webhook_url:
            self.logger.warning("slack_webhook_url_not_configured")
            return

        try:
            # 채널 지정이 있으면 추가
            if channel:
                payload["channel"] = channel

            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            self.logger.debug("slack_message_sent", status_code=response.status_code)
        except requests.exceptions.RequestException as e:
            self.logger.error("slack_send_failed", error=str(e))
            raise


# ============================================================
# 전역 서비스 인스턴스
# ============================================================

_slack_notification_service: Optional[SlackNotificationService] = None


def get_slack_notification_service() -> SlackNotificationService:
    """Slack 알림 서비스 인스턴스를 반환합니다."""
    global _slack_notification_service
    if _slack_notification_service is None:
        _slack_notification_service = SlackNotificationService()
    return _slack_notification_service


def init_slack_notification_service(webhook_url: Optional[str] = None) -> SlackNotificationService:
    """Slack 알림 서비스를 초기화합니다."""
    global _slack_notification_service
    _slack_notification_service = SlackNotificationService(webhook_url)
    return _slack_notification_service


# ============================================================
# 헬퍼 함수들
# ============================================================

def format_duration(seconds: int) -> str:
    """초를 MM:SS 포맷으로 변환"""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def truncate_text(text: str, max_length: int) -> str:
    """텍스트를 지정된 길이로 자르기"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."
