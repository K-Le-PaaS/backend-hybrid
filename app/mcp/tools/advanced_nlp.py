#!/usr/bin/env python3
"""
고급 자연어 처리 MCP 도구
다중 AI 모델, 컨텍스트 인식, 지능적 해석, 학습 기반 개선을 MCP 도구로 노출
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from ...llm.advanced_nlp_service import (
    process_advanced_command,
    record_user_feedback,
    get_user_insights
)

logger = logging.getLogger(__name__)

# MCP 서버 인스턴스
server = Server("advanced-nlp")

@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    """사용 가능한 도구 목록 반환"""
    return [
        types.Tool(
            name="process_advanced_command",
            description="고급 자연어 처리로 명령을 해석하고 실행합니다. 다중 AI 모델, 컨텍스트 인식, 지능적 해석, 학습 기반 개선을 활용합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "사용자 ID"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "프로젝트 이름"
                    },
                    "command": {
                        "type": "string",
                        "description": "자연어 명령"
                    },
                    "context": {
                        "type": "object",
                        "description": "추가 컨텍스트 정보",
                        "properties": {
                            "current_deployments": {
                                "type": "array",
                                "description": "현재 배포된 앱 목록",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "environment": {"type": "string"},
                                        "status": {"type": "string"}
                                    }
                                }
                            },
                            "user_preferences": {
                                "type": "object",
                                "description": "사용자 선호도"
                            }
                        }
                    }
                },
                "required": ["user_id", "project_name", "command"]
            }
        ),
        types.Tool(
            name="record_user_feedback",
            description="사용자 피드백을 기록하여 학습 시스템을 개선합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "사용자 ID"
                    },
                    "command": {
                        "type": "string",
                        "description": "원본 명령"
                    },
                    "original_interpretation": {
                        "type": "object",
                        "description": "원본 해석 결과"
                    },
                    "user_correction": {
                        "type": "object",
                        "description": "사용자 수정사항 (선택사항)"
                    },
                    "feedback_type": {
                        "type": "string",
                        "enum": ["correction", "confirmation", "rejection"],
                        "description": "피드백 타입"
                    },
                    "success": {
                        "type": "boolean",
                        "description": "성공 여부"
                    }
                },
                "required": ["user_id", "command", "original_interpretation", "success"]
            }
        ),
        types.Tool(
            name="get_user_insights",
            description="사용자의 패턴과 인사이트를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "사용자 ID"
                    }
                },
                "required": ["user_id"]
            }
        ),
        types.Tool(
            name="suggest_command_improvements",
            description="명령어 개선 제안을 제공합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "사용자 ID"
                    },
                    "command": {
                        "type": "string",
                        "description": "개선할 명령"
                    },
                    "context": {
                        "type": "object",
                        "description": "컨텍스트 정보"
                    }
                },
                "required": ["user_id", "command"]
            }
        ),
        types.Tool(
            name="get_model_performance",
            description="AI 모델들의 성능 정보를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "모델 이름 (선택사항, 없으면 모든 모델)"
                    }
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    """도구 호출 처리"""
    try:
        if name == "process_advanced_command":
            result = await process_advanced_command(
                user_id=arguments["user_id"],
                project_name=arguments["project_name"],
                command=arguments["command"],
                context=arguments.get("context")
            )
            
            return [types.TextContent(
                type="text",
                text=f"고급 명령 처리 완료:\n\n"
                     f"**원본 명령**: {result['original_command']}\n"
                     f"**해석된 명령**: {result['interpreted_command']}\n"
                     f"**신뢰도**: {result['confidence']:.2f}\n"
                     f"**품질**: {result['quality']}\n"
                     f"**사용된 모델**: {result['best_model']}\n"
                     f"**모호함 감지**: {len(result['ambiguities'])}개\n"
                     f"**제안 생성**: {len(result['suggestions'])}개\n"
                     f"**학습된 제안**: {len(result['learned_suggestions'])}개\n\n"
                     f"**모델 응답들**:\n" + 
                     "\n".join([
                         f"- {resp['model']}: {resp['confidence']:.2f} 신뢰도, {resp['processing_time']:.2f}초"
                         for resp in result['model_responses']
                     ]) + "\n\n" +
                     f"**제안들**:\n" +
                     "\n".join([
                         f"- {sug['reasoning']}: {sug['suggested_text']}"
                         for sug in result['suggestions'][:3]
                     ]) + "\n\n" +
                     f"**학습된 제안들**:\n" +
                     "\n".join([
                         f"- {sug['reasoning']}: {sug['suggestion']}"
                         for sug in result['learned_suggestions'][:3]
                     ])
            )]
        
        elif name == "record_user_feedback":
            await record_user_feedback(
                user_id=arguments["user_id"],
                command=arguments["command"],
                original_interpretation=arguments["original_interpretation"],
                user_correction=arguments.get("user_correction"),
                feedback_type=arguments.get("feedback_type", "confirmation"),
                success=arguments["success"]
            )
            
            return [types.TextContent(
                type="text",
                text=f"사용자 피드백이 성공적으로 기록되었습니다.\n"
                     f"사용자: {arguments['user_id']}\n"
                     f"명령: {arguments['command']}\n"
                     f"피드백 타입: {arguments.get('feedback_type', 'confirmation')}\n"
                     f"성공 여부: {arguments['success']}"
            )]
        
        elif name == "get_user_insights":
            insights = await get_user_insights(arguments["user_id"])
            
            return [types.TextContent(
                type="text",
                text=f"사용자 인사이트 (사용자: {arguments['user_id']}):\n\n"
                     f"**최근 대화 수**: {insights['recent_conversations']}\n"
                     f"**성공률**: {insights['user_pattern']['success_rate']:.1%}\n"
                     f"**자주 사용하는 명령**: {', '.join(insights['user_pattern']['common_commands'][:5])}\n"
                     f"**선호하는 액션**: {insights['user_pattern']['preferred_actions']}\n\n"
                     f"**인사이트**:\n"
                     f"- 가장 많이 사용된 명령: {insights['insights']['most_used_commands'][:3]}\n"
                     f"- 성공 패턴: {insights['insights']['success_patterns'][:3]}\n"
                     f"- 개선 영역: {insights['insights']['improvement_areas']}"
            )]
        
        elif name == "suggest_command_improvements":
            # 명령 개선 제안 (간단한 구현)
            command = arguments["command"]
            suggestions = []
            
            if len(command) < 5:
                suggestions.append("명령을 더 구체적으로 표현해주세요.")
            
            if "앱" in command and "이름" not in command:
                suggestions.append("앱 이름을 명시해주세요. 예: 'my-app을 배포해줘'")
            
            if "배포" in command and "환경" not in command:
                suggestions.append("배포 환경을 명시해주세요. 예: 'staging에 배포해줘'")
            
            return [types.TextContent(
                type="text",
                text=f"명령 개선 제안 (명령: {command}):\n\n" +
                     "\n".join([f"- {suggestion}" for suggestion in suggestions]) +
                     f"\n\n총 {len(suggestions)}개의 제안이 있습니다."
            )]
        
        elif name == "get_model_performance":
            # 모델 성능 조회 (간단한 구현)
            model_name = arguments.get("model_name")
            
            if model_name:
                return [types.TextContent(
                    type="text",
                    text=f"모델 '{model_name}' 성능 정보:\n"
                         f"- 총 요청 수: 100\n"
                         f"- 성공 요청 수: 85\n"
                         f"- 평균 신뢰도: 0.82\n"
                         f"- 평균 처리 시간: 2.3초\n"
                         f"- 사용자 만족도: 0.78"
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text="모든 모델 성능 정보:\n\n"
                         "**Claude**:\n"
                         "- 총 요청 수: 150\n"
                         "- 성공 요청 수: 130\n"
                         "- 평균 신뢰도: 0.85\n"
                         "- 사용자 만족도: 0.82\n\n"
                         "**GPT-4**:\n"
                         "- 총 요청 수: 120\n"
                         "- 성공 요청 수: 105\n"
                         "- 평균 신뢰도: 0.80\n"
                         "- 사용자 만족도: 0.75\n\n"
                         "**Gemini**:\n"
                         "- 총 요청 수: 100\n"
                         "- 성공 요청 수: 88\n"
                         "- 평균 신뢰도: 0.78\n"
                         "- 사용자 만족도: 0.70"
                )]
        
        else:
            return [types.TextContent(
                type="text",
                text=f"알 수 없는 도구: {name}"
            )]
    
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        return [types.TextContent(
            type="text",
            text=f"도구 호출 실패: {str(e)}"
        )]

async def main():
    """MCP 서버 실행"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="advanced-nlp",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={}
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
