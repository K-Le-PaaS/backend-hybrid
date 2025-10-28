"""
Slack 템플릿 빌더 서비스
Jinja2 템플릿을 사용하여 Slack 알림을 중앙화된 방식으로 생성합니다.
"""

import json
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import structlog

logger = structlog.get_logger(__name__)


class SlackTemplateBuilder:
    """Slack 알림 템플릿 빌더 - Jinja2 기반 중앙화"""
    
    def __init__(self, template_dir: Optional[str] = None):
        """
        템플릿 빌더 초기화
        
        Args:
            template_dir: 템플릿 디렉토리 경로 (기본값: app/templates/slack)
        """
        if template_dir is None:
            # 현재 파일 기준으로 상대 경로 계산
            current_dir = Path(__file__).parent
            template_dir = current_dir.parent / "templates" / "slack"
        
        self.template_dir = Path(template_dir)
        self.logger = logger.bind(service="slack_template_builder")
        
        # Jinja2 환경 설정
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            autoescape=False
        )
        
        # 커스텀 필터 등록
        self._register_filters()
        
        self.logger.info("slack_template_builder_initialized", template_dir=str(self.template_dir))
    
    def _register_filters(self):
        """커스텀 Jinja2 필터 등록"""
        
        def pad_right(value: str, width: int) -> str:
            """문자열을 지정된 너비로 오른쪽 패딩"""
            if not isinstance(value, str):
                value = str(value)
            return value.ljust(width)
        
        def truncate(value: str, length: int, suffix: str = "...") -> str:
            """문자열을 지정된 길이로 자르기"""
            if not isinstance(value, str):
                value = str(value)
            if len(value) <= length:
                return value
            return value[:length-len(suffix)] + suffix
        
        def format_duration(seconds: int) -> str:
            """초를 MM:SS 포맷으로 변환"""
            minutes, secs = divmod(seconds, 60)
            return f"{minutes:02d}:{secs:02d}"
        
        def format_timestamp() -> int:
            """현재 시간을 Unix 타임스탬프로 반환"""
            return int(time.time())
        
        def calculate_padding(label: str, content: str, box_width: int = 60) -> int:
            """박스 내부 패딩 계산"""
            label_len = len(label)
            content_len = len(content)
            return box_width - label_len - content_len

        def display_width(value: str) -> int:
            """화면 표시 폭 계산 (emoji/CJK 포함)"""
            try:
                from wcwidth import wcwidth  # type: ignore
            except Exception:
                wcwidth = None
            width = 0
            for ch in str(value or ""):
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

        def calculate_padding_display(label: str, content: str, box_width: int = 60) -> int:
            """표시 폭 기준 패딩 계산 (emoji 안전)"""
            return box_width - len(label) - display_width(content)
        
        def get_commit_short(commit_sha: str, length: int = 7) -> str:
            """커밋 SHA를 짧게 자르기"""
            return commit_sha[:length] if commit_sha else "unknown"
        
        def get_commit_message_short(commit_message: str, length: int = 30) -> str:
            """커밋 메시지 첫 줄을 짧게 자르기"""
            if not commit_message:
                return "No commit message"
            first_line = commit_message.split('\n')[0]
            if len(first_line) <= length:
                return first_line
            return first_line[:length-3] + "..."
        
        def calculate_step_times(duration_seconds: int) -> Dict[str, int]:
            """배포 단계별 소요시간 계산"""
            return {
                "build_time": int(duration_seconds * 0.35),
                "test_time": int(duration_seconds * 0.25),
                "manifest_time": int(duration_seconds * 0.20),
                "health_time": int(duration_seconds * 0.20)
            }
        
        def format_logs_section(logs: Optional[List[str]], max_lines: int = 10) -> str:
            """로그 섹션 포맷팅"""
            if not logs or len(logs) == 0:
                return ""
            
            log_lines = logs[-max_lines:]  # 마지막 N줄
            return "\n\n[INFO] Deployment logs (last {} lines):\n".format(max_lines) + "\n".join(
                f"  │ {line[:55]}" for line in log_lines
            )
        
        def format_error_section(error_message: str, max_lines: int = 3) -> str:
            """에러 메시지 섹션 포맷팅"""
            if not error_message:
                return ""
            
            error_lines = error_message.split('\n')[:max_lines]
            return "\n".join(f"  │ {line[:55]}" for line in error_lines)
        
        # 필터 등록
        self.env.filters['pad_right'] = pad_right
        self.env.filters['truncate'] = truncate
        self.env.filters['format_duration'] = format_duration
        self.env.filters['format_timestamp'] = format_timestamp
        self.env.filters['calculate_padding'] = calculate_padding
        self.env.filters['display_width'] = display_width
        self.env.filters['calculate_padding_display'] = calculate_padding_display
        self.env.filters['get_commit_short'] = get_commit_short
        self.env.filters['get_commit_message_short'] = get_commit_message_short
        self.env.filters['calculate_step_times'] = calculate_step_times
        self.env.filters['format_logs_section'] = format_logs_section
        self.env.filters['format_error_section'] = format_error_section
    
    def build_deployment_notification(
        self,
        notification_type: str,
        **context
    ) -> Dict[str, Any]:
        """
        배포 알림 템플릿 빌드
        
        Args:
            notification_type: 알림 타입 ("started" | "success" | "failed")
            **context: 템플릿 컨텍스트 데이터
            
        Returns:
            Slack Blocks API 포맷의 딕셔너리
        """
        try:
            # 템플릿 파일명 결정
            template_name = f"deployment_{notification_type}_terminal.jinja2"
            
            # 템플릿 로드
            template = self.env.get_template(template_name)
            
            # 컨텍스트 전처리
            processed_context = self._prepare_context(context, notification_type)
            
            # 템플릿 렌더링
            rendered = template.render(**processed_context)
            
            # JSON 파싱
            result = json.loads(rendered)
            
            self.logger.info(
                "deployment_notification_built",
                notification_type=notification_type,
                deployment_id=context.get("deployment_id")
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                "template_build_failed",
                notification_type=notification_type,
                error=str(e)
            )
            raise
    
    def _prepare_context(self, context: Dict[str, Any], notification_type: str = None) -> Dict[str, Any]:
        """
        템플릿 컨텍스트 전처리
        
        Args:
            context: 원본 컨텍스트
            notification_type: 알림 타입 (선택적)
            
        Returns:
            전처리된 컨텍스트
        """
        processed = context.copy()
        
        # 기본값 설정
        processed.setdefault("branch", "main")
        processed.setdefault("duration_seconds", 0)
        processed.setdefault("timestamp", int(time.time()))
        
        # 커밋 정보 처리
        if "commit_sha" in processed:
            processed["commit_short"] = processed["commit_sha"][:7]
        
        if "commit_message" in processed:
            processed["commit_message_short"] = processed["commit_message"].split('\n')[0][:30]
        
        # 소요시간 포맷팅
        if "duration_seconds" in processed:
            processed["duration_str"] = self.env.filters['format_duration'](processed["duration_seconds"])
        
        # 박스 너비 설정
        processed["box_width"] = 60
        
        # 패딩 계산
        if "repo" in processed:
            processed["repo_padding"] = self.env.filters['calculate_padding'](
                "Repository:    ", processed["repo"], processed["box_width"]
            )
        
        if "branch" in processed:
            processed["branch_padding"] = self.env.filters['calculate_padding'](
                "Branch:        ", processed["branch"], processed["box_width"]
            )
        
        if "commit_short" in processed and "commit_message_short" in processed:
            commit_content = f"{processed['commit_short']} ({processed['commit_message_short']})"
            processed["commit_padding"] = self.env.filters['calculate_padding'](
                "Commit:        ", commit_content, processed["box_width"]
            )
        
        if "author" in processed:
            processed["author_padding"] = self.env.filters['calculate_padding'](
                "Author:        ", processed["author"], processed["box_width"]
            )
        
        if "deployment_id" in processed:
            deploy_content = f"#{processed['deployment_id']}"
            processed["deploy_padding"] = self.env.filters['calculate_padding'](
                "Deploy ID:     ", deploy_content, processed["box_width"]
            )
        
        if "duration_str" in processed and "duration_seconds" in processed:
            duration_content = f"{processed['duration_str']} ({processed['duration_seconds']}s)"
            processed["duration_padding"] = self.env.filters['calculate_padding'](
                "Duration:      ", duration_content, processed["box_width"]
            )
        
        # 단계별 시간 계산 (성공 알림용)
        if notification_type == "success" and "duration_seconds" in processed:
            processed["step_times"] = self.env.filters['calculate_step_times'](processed["duration_seconds"])
        
        # 로그 섹션 포맷팅
        if "logs" in processed:
            processed["log_section"] = self.env.filters['format_logs_section'](processed["logs"])
        else:
            processed["log_section"] = ""
        
        # 에러 섹션 포맷팅 (실패 알림용)
        if notification_type == "failed" and "error_message" in processed:
            processed["error_section"] = self.env.filters['format_error_section'](processed["error_message"])
        else:
            processed["error_section"] = ""
        
        return processed
    
    def get_available_templates(self) -> List[str]:
        """사용 가능한 템플릿 목록 반환"""
        try:
            template_files = list(self.template_dir.glob("*.jinja2"))
            return [f.stem for f in template_files]
        except Exception as e:
            self.logger.error("failed_to_list_templates", error=str(e))
            return []
    
    def validate_template(self, template_name: str, context: Dict[str, Any]) -> bool:
        """템플릿 유효성 검증"""
        try:
            template = self.env.get_template(f"{template_name}.jinja2")
            processed_context = self._prepare_context(context)
            template.render(**processed_context)
            return True
        except Exception as e:
            self.logger.error("template_validation_failed", template=template_name, error=str(e))
            return False
