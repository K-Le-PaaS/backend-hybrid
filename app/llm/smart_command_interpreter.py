#!/usr/bin/env python3
"""
지능적 명령 해석 및 자동 수정 제안 시스템
모호한 명령을 자동으로 해석하고 개선 제안을 제공
"""

import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import difflib

logger = logging.getLogger(__name__)

class AmbiguityType(str, Enum):
    """모호함 타입"""
    MISSING_TARGET = "missing_target"
    MISSING_ACTION = "missing_action"
    MISSING_PARAMETERS = "missing_parameters"
    UNCLEAR_INTENT = "unclear_intent"
    MULTIPLE_OPTIONS = "multiple_options"
    INVALID_SYNTAX = "invalid_syntax"

class SuggestionType(str, Enum):
    """제안 타입"""
    CLARIFICATION = "clarification"
    CORRECTION = "correction"
    ALTERNATIVE = "alternative"
    EXAMPLE = "example"
    CONTEXT_BASED = "context_based"

@dataclass
class AmbiguityDetection:
    """모호함 감지 결과"""
    ambiguity_type: AmbiguityType
    confidence: float
    description: str
    affected_parts: List[str]

@dataclass
class CommandSuggestion:
    """명령 제안"""
    suggestion_type: SuggestionType
    original_text: str
    suggested_text: str
    confidence: float
    reasoning: str
    priority: int  # 1-5, 5가 가장 높은 우선순위

@dataclass
class InterpretationResult:
    """해석 결과"""
    original_command: str
    interpreted_command: Dict[str, Any]
    confidence: float
    ambiguities: List[AmbiguityDetection]
    suggestions: List[CommandSuggestion]
    alternatives: List[Dict[str, Any]]

class SmartCommandInterpreter:
    """지능적 명령 해석기"""
    
    def __init__(self):
        # 일반적인 Kubernetes 액션 패턴
        self.action_patterns = {
            "deploy": [
                r"배포", r"deploy", r"올리", r"실행", r"시작", r"run", r"start"
            ],
            "scale": [
                r"스케일", r"scale", r"확장", r"축소", r"복제", r"replica"
            ],
            "rollback": [
                r"롤백", r"rollback", r"되돌리", r"이전", r"복구", r"restore"
            ],
            "delete": [
                r"삭제", r"delete", r"제거", r"지워", r"remove", r"destroy"
            ],
            "update": [
                r"업데이트", r"update", r"수정", r"변경", r"modify", r"change"
            ],
            "status": [
                r"상태", r"status", r"확인", r"조회", r"보여", r"show", r"get"
            ]
        }
        
        # 환경 패턴
        self.environment_patterns = {
            "staging": [r"스테이징", r"staging", r"테스트", r"test", r"dev"],
            "production": [r"프로덕션", r"production", r"운영", r"prod", r"live"],
            "development": [r"개발", r"development", r"dev", r"local"]
        }
        
        # 리소스 타입 패턴
        self.resource_patterns = {
            "deployment": [r"배포", r"deployment", r"앱", r"app", r"서비스", r"service"],
            "service": [r"서비스", r"service", r"API", r"api"],
            "configmap": [r"설정", r"config", r"configmap", r"환경변수"],
            "secret": [r"시크릿", r"secret", r"비밀", r"암호", r"password"]
        }
    
    async def interpret_command(self, command: str, context: Dict[str, Any] = None) -> InterpretationResult:
        """명령 해석"""
        if context is None:
            context = {}
        
        logger.info(f"Interpreting command: {command}")
        
        # 1. 기본 파싱
        parsed = await self._parse_command(command)
        
        # 2. 모호함 감지
        ambiguities = await self._detect_ambiguities(parsed, command, context)
        
        # 3. 제안 생성
        suggestions = await self._generate_suggestions(command, parsed, ambiguities, context)
        
        # 4. 대안 생성
        alternatives = await self._generate_alternatives(command, parsed, context)
        
        # 5. 신뢰도 계산
        confidence = self._calculate_confidence(parsed, ambiguities, suggestions)
        
        return InterpretationResult(
            original_command=command,
            interpreted_command=parsed,
            confidence=confidence,
            ambiguities=ambiguities,
            suggestions=suggestions,
            alternatives=alternatives
        )
    
    async def _parse_command(self, command: str) -> Dict[str, Any]:
        """기본 명령 파싱"""
        parsed = {
            "action": "unknown",
            "target": "unknown",
            "environment": "unknown",
            "parameters": {},
            "raw_command": command
        }
        
        # 액션 추출
        for action, patterns in self.action_patterns.items():
            for pattern in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    parsed["action"] = action
                    break
            if parsed["action"] != "unknown":
                break
        
        # 환경 추출
        for env, patterns in self.environment_patterns.items():
            for pattern in patterns:
                if re.search(pattern, command, re.IGNORECASE):
                    parsed["environment"] = env
                    break
        
        # 타겟 추출 (간단한 휴리스틱)
        words = command.split()
        for word in words:
            if len(word) > 2 and not word.lower() in ["앱", "app", "서비스", "service"]:
                if not any(re.search(pattern, word, re.IGNORECASE) for patterns in self.action_patterns.values() for pattern in patterns):
                    parsed["target"] = word
                    break
        
        # 숫자 파라미터 추출
        numbers = re.findall(r'\d+', command)
        if numbers:
            parsed["parameters"]["replicas"] = int(numbers[0])
        
        return parsed
    
    async def _detect_ambiguities(self, parsed: Dict[str, Any], command: str, context: Dict[str, Any]) -> List[AmbiguityDetection]:
        """모호함 감지"""
        ambiguities = []
        
        # 액션이 불명확한 경우
        if parsed["action"] == "unknown":
            ambiguities.append(AmbiguityDetection(
                ambiguity_type=AmbiguityType.MISSING_ACTION,
                confidence=0.9,
                description="수행할 작업이 명확하지 않습니다",
                affected_parts=["action"]
            ))
        
        # 타겟이 불명확한 경우
        if parsed["target"] == "unknown":
            ambiguities.append(AmbiguityDetection(
                ambiguity_type=AmbiguityType.MISSING_TARGET,
                confidence=0.8,
                description="대상 앱이나 서비스가 명시되지 않았습니다",
                affected_parts=["target"]
            ))
        
        # 환경이 불명확한 경우
        if parsed["environment"] == "unknown" and parsed["action"] in ["deploy", "scale", "update"]:
            ambiguities.append(AmbiguityDetection(
                ambiguity_type=AmbiguityType.MISSING_PARAMETERS,
                confidence=0.7,
                description="배포 환경이 명시되지 않았습니다",
                affected_parts=["environment"]
            ))
        
        # 컨텍스트 기반 모호함 감지
        if context.get("current_deployments"):
            available_apps = [dep.get("name", "") for dep in context["current_deployments"]]
            if parsed["target"] != "unknown" and parsed["target"] not in available_apps:
                # 비슷한 앱 이름 찾기
                similar_apps = difflib.get_close_matches(parsed["target"], available_apps, n=3, cutoff=0.6)
                if similar_apps:
                    ambiguities.append(AmbiguityDetection(
                        ambiguity_type=AmbiguityType.MULTIPLE_OPTIONS,
                        confidence=0.6,
                        description=f"'{parsed['target']}'와 비슷한 앱이 있습니다: {', '.join(similar_apps)}",
                        affected_parts=["target"]
                    ))
        
        return ambiguities
    
    async def _generate_suggestions(self, command: str, parsed: Dict[str, Any], ambiguities: List[AmbiguityDetection], context: Dict[str, Any]) -> List[CommandSuggestion]:
        """제안 생성"""
        suggestions = []
        
        for ambiguity in ambiguities:
            if ambiguity.ambiguity_type == AmbiguityType.MISSING_ACTION:
                suggestions.extend(self._suggest_actions(command, context))
            elif ambiguity.ambiguity_type == AmbiguityType.MISSING_TARGET:
                suggestions.extend(self._suggest_targets(command, context))
            elif ambiguity.ambiguity_type == AmbiguityType.MISSING_PARAMETERS:
                suggestions.extend(self._suggest_parameters(command, parsed, context))
            elif ambiguity.ambiguity_type == AmbiguityType.MULTIPLE_OPTIONS:
                suggestions.extend(self._suggest_corrections(command, ambiguity, context))
        
        # 우선순위별 정렬
        suggestions.sort(key=lambda x: x.priority, reverse=True)
        return suggestions[:5]  # 최대 5개 제안
    
    def _suggest_actions(self, command: str, context: Dict[str, Any]) -> List[CommandSuggestion]:
        """액션 제안"""
        suggestions = []
        
        # 컨텍스트 기반 액션 제안
        if context.get("current_deployments"):
            suggestions.append(CommandSuggestion(
                suggestion_type=SuggestionType.CONTEXT_BASED,
                original_text=command,
                suggested_text=f"{command} (배포된 앱들을 관리하려면 '상태 확인', '스케일링', '롤백' 등을 사용하세요)",
                confidence=0.8,
                reasoning="현재 배포된 앱이 있어서 관리 액션을 제안합니다",
                priority=4
            ))
        
        # 일반적인 액션 제안
        common_actions = ["배포", "스케일링", "롤백", "상태 확인", "삭제"]
        for action in common_actions:
            suggestions.append(CommandSuggestion(
                suggestion_type=SuggestionType.EXAMPLE,
                original_text=command,
                suggested_text=f"'{action}'를 사용해보세요",
                confidence=0.6,
                reasoning=f"일반적으로 사용되는 액션입니다",
                priority=3
            ))
        
        return suggestions
    
    def _suggest_targets(self, command: str, context: Dict[str, Any]) -> List[CommandSuggestion]:
        """타겟 제안"""
        suggestions = []
        
        # 컨텍스트에서 사용 가능한 앱들
        if context.get("current_deployments"):
            available_apps = [dep.get("name", "") for dep in context["current_deployments"]]
            for app in available_apps[:3]:  # 최대 3개
                suggestions.append(CommandSuggestion(
                    suggestion_type=SuggestionType.CONTEXT_BASED,
                    original_text=command,
                    suggested_text=f"'{app}'을 대상으로 하려면: {command.replace('앱', app)}",
                    confidence=0.9,
                    reasoning=f"현재 배포된 앱 '{app}'을 제안합니다",
                    priority=5
                ))
        
        # 일반적인 타겟 제안
        suggestions.append(CommandSuggestion(
            suggestion_type=SuggestionType.CLARIFICATION,
            original_text=command,
            suggested_text="앱 이름을 명시해주세요. 예: 'my-app을 배포해줘'",
            confidence=0.7,
            reasoning="구체적인 앱 이름이 필요합니다",
            priority=4
        ))
        
        return suggestions
    
    def _suggest_parameters(self, command: str, parsed: Dict[str, Any], context: Dict[str, Any]) -> List[CommandSuggestion]:
        """파라미터 제안"""
        suggestions = []
        
        if parsed["action"] in ["deploy", "scale"]:
            # 환경 제안
            suggestions.append(CommandSuggestion(
                suggestion_type=SuggestionType.CLARIFICATION,
                original_text=command,
                suggested_text=f"{command} (환경을 명시하려면: '{command} staging에' 또는 '{command} production에')",
                confidence=0.8,
                reasoning="배포 환경을 명시해야 합니다",
                priority=4
            ))
            
            # 복제본 수 제안
            if parsed["action"] == "scale":
                suggestions.append(CommandSuggestion(
                    suggestion_type=SuggestionType.EXAMPLE,
                    original_text=command,
                    suggested_text=f"{command} (복제본 수를 명시하려면: '{command} 3개로')",
                    confidence=0.7,
                    reasoning="스케일링 시 복제본 수가 필요합니다",
                    priority=3
                ))
        
        return suggestions
    
    def _suggest_corrections(self, command: str, ambiguity: AmbiguityDetection, context: Dict[str, Any]) -> List[CommandSuggestion]:
        """수정 제안"""
        suggestions = []
        
        # 유사한 앱 이름 제안
        if "비슷한 앱이 있습니다" in ambiguity.description:
            similar_apps = ambiguity.description.split(": ")[1].split(", ")
            for app in similar_apps:
                corrected_command = command.replace(parsed["target"], app)
                suggestions.append(CommandSuggestion(
                    suggestion_type=SuggestionType.CORRECTION,
                    original_text=command,
                    suggested_text=corrected_command,
                    confidence=0.8,
                    reasoning=f"'{app}'로 수정하는 것을 제안합니다",
                    priority=5
                ))
        
        return suggestions
    
    async def _generate_alternatives(self, command: str, parsed: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """대안 생성"""
        alternatives = []
        
        # 액션별 대안
        if parsed["action"] == "deploy":
            alternatives.extend([
                {
                    "action": "deploy",
                    "target": parsed["target"],
                    "environment": "staging",
                    "description": "스테이징 환경에 배포"
                },
                {
                    "action": "deploy",
                    "target": parsed["target"],
                    "environment": "production",
                    "description": "프로덕션 환경에 배포"
                }
            ])
        elif parsed["action"] == "scale":
            alternatives.extend([
                {
                    "action": "scale",
                    "target": parsed["target"],
                    "parameters": {"replicas": 2},
                    "description": "2개 복제본으로 스케일링"
                },
                {
                    "action": "scale",
                    "target": parsed["target"],
                    "parameters": {"replicas": 5},
                    "description": "5개 복제본으로 스케일링"
                }
            ])
        
        return alternatives
    
    def _calculate_confidence(self, parsed: Dict[str, Any], ambiguities: List[AmbiguityDetection], suggestions: List[CommandSuggestion]) -> float:
        """신뢰도 계산"""
        base_confidence = 1.0
        
        # 모호함에 따른 신뢰도 감소
        for ambiguity in ambiguities:
            base_confidence -= ambiguity.confidence * 0.2
        
        # 제안이 많을수록 신뢰도 감소
        if len(suggestions) > 3:
            base_confidence -= 0.1
        
        # 액션이 명확한 경우 신뢰도 증가
        if parsed["action"] != "unknown":
            base_confidence += 0.2
        
        # 타겟이 명확한 경우 신뢰도 증가
        if parsed["target"] != "unknown":
            base_confidence += 0.2
        
        return max(0.0, min(1.0, base_confidence))

# 사용 예시
async def main():
    interpreter = SmartCommandInterpreter()
    
    # 테스트 명령들
    test_commands = [
        "앱 배포해줘",
        "스케일링",
        "my-app을 staging에 3개로 배포해줘",
        "상태 확인",
        "롤백"
    ]
    
    context = {
        "current_deployments": [
            {"name": "my-web-app", "environment": "staging"},
            {"name": "my-api", "environment": "production"}
        ]
    }
    
    for command in test_commands:
        print(f"\n명령: {command}")
        result = await interpreter.interpret_command(command, context)
        
        print(f"해석: {result.interpreted_command}")
        print(f"신뢰도: {result.confidence:.2f}")
        print(f"모호함: {len(result.ambiguities)}개")
        print(f"제안: {len(result.suggestions)}개")
        
        for suggestion in result.suggestions[:2]:
            print(f"  - {suggestion.suggested_text}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
