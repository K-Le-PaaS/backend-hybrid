"""
K-Le-PaaS 튜토리얼 MCP 도구
1분 플로우: 배포 → 상태 확인 → 롤백
"""

from typing import Any, Dict, List, Optional
from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from ...services.tutorial_script import tutorial_state_manager, TutorialStep


def create_tutorial_tools() -> List[types.Tool]:
    """튜토리얼 관련 MCP 도구 생성"""
    
    return [
        types.Tool(
            name="start_tutorial",
            description="K-Le-PaaS 인터랙티브 튜토리얼을 시작합니다. 1분 플로우(배포→상태 확인→롤백)를 경험할 수 있습니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        
        types.Tool(
            name="get_tutorial_status",
            description="현재 튜토리얼 진행 상태를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        
        types.Tool(
            name="next_tutorial_step",
            description="튜토리얼의 다음 단계로 진행합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        
        types.Tool(
            name="add_tutorial_input",
            description="튜토리얼에서 사용자의 자연어 입력을 처리합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    },
                    "user_input": {
                        "type": "string",
                        "description": "사용자의 자연어 입력"
                    }
                },
                "required": ["session_id", "user_input"]
            }
        ),
        
        types.Tool(
            name="complete_tutorial",
            description="튜토리얼을 완료합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        
        types.Tool(
            name="reset_tutorial",
            description="튜토리얼을 처음부터 다시 시작합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "튜토리얼 세션 ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        
        types.Tool(
            name="get_tutorial_script",
            description="튜토리얼 스크립트의 모든 단계와 메시지를 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "description": "특정 단계 조회 (welcome, deploy_app, check_status, rollback, complete)",
                        "enum": ["welcome", "deploy_app", "check_status", "rollback", "complete"]
                    }
                }
            }
        )
    ]


async def handle_tutorial_tool(server: Server, name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    """튜토리얼 도구 처리"""
    
    if name == "start_tutorial":
        session_id = arguments.get("session_id")
        if not session_id:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID가 필요합니다."
            )]
        
        result = tutorial_state_manager.start_tutorial(session_id)
        if result:
            return [types.TextContent(
                type="text",
                text=f"✅ 튜토리얼이 시작되었습니다!\n\n"
                     f"**{result['title']}**\n\n"
                     f"{result['content']}\n\n"
                     f"진행률: {result['step_index'] + 1}/{result['total_steps']}\n"
                     f"상태: {result['state']}"
            )]
        else:
            return [types.TextContent(
                type="text",
                text="❌ 튜토리얼을 시작할 수 없습니다."
            )]
    
    elif name == "get_tutorial_status":
        session_id = arguments.get("session_id")
        if not session_id:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID가 필요합니다."
            )]
        
        result = tutorial_state_manager.get_current_step(session_id)
        if result:
            return [types.TextContent(
                type="text",
                text=f"📊 **튜토리얼 상태**\n\n"
                     f"**{result['title']}**\n\n"
                     f"{result['content']}\n\n"
                     f"진행률: {result['step_index'] + 1}/{result['total_steps']}\n"
                     f"상태: {result['state']}\n"
                     f"완료된 단계: {', '.join(result['completed_steps']) if result['completed_steps'] else '없음'}\n"
                     f"사용자 입력 수: {len(result['user_inputs'])}\n"
                     f"에러 수: {len(result['errors'])}"
            )]
        else:
            return [types.TextContent(
                type="text",
                text="❌ 튜토리얼 세션을 찾을 수 없습니다."
            )]
    
    elif name == "next_tutorial_step":
        session_id = arguments.get("session_id")
        if not session_id:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID가 필요합니다."
            )]
        
        result = tutorial_state_manager.next_step(session_id)
        if result:
            return [types.TextContent(
                type="text",
                text=f"➡️ **다음 단계로 진행**\n\n"
                     f"**{result['title']}**\n\n"
                     f"{result['content']}\n\n"
                     f"진행률: {result['step_index'] + 1}/{result['total_steps']}\n"
                     f"상태: {result['state']}"
            )]
        else:
            return [types.TextContent(
                type="text",
                text="❌ 다음 단계로 진행할 수 없습니다. 튜토리얼이 완료되었거나 세션을 찾을 수 없습니다."
            )]
    
    elif name == "add_tutorial_input":
        session_id = arguments.get("session_id")
        user_input = arguments.get("user_input")
        
        if not session_id or not user_input:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID와 사용자 입력이 필요합니다."
            )]
        
        success = tutorial_state_manager.add_user_input(session_id, user_input)
        if success:
            result = tutorial_state_manager.get_current_step(session_id)
            if result:
                return [types.TextContent(
                    type="text",
                    text=f"💬 **사용자 입력 처리됨**\n\n"
                         f"입력: \"{user_input}\"\n\n"
                         f"현재 단계: {result['title']}\n"
                         f"상태: {result['state']}"
                )]
        
        return [types.TextContent(
            type="text",
            text="❌ 사용자 입력을 처리할 수 없습니다."
        )]
    
    elif name == "complete_tutorial":
        session_id = arguments.get("session_id")
        if not session_id:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID가 필요합니다."
            )]
        
        result = tutorial_state_manager.complete_tutorial(session_id)
        if result:
            return [types.TextContent(
                type="text",
                text=f"🎉 **튜토리얼 완료!**\n\n"
                     f"**{result['title']}**\n\n"
                     f"{result['content']}\n\n"
                     f"완료된 단계: {', '.join(result['completed_steps'])}\n"
                     f"축하합니다! K-Le-PaaS의 핵심 기능을 모두 경험해보셨습니다."
            )]
        else:
            return [types.TextContent(
                type="text",
                text="❌ 튜토리얼을 완료할 수 없습니다."
            )]
    
    elif name == "reset_tutorial":
        session_id = arguments.get("session_id")
        if not session_id:
            return [types.TextContent(
                type="text",
                text="❌ 세션 ID가 필요합니다."
            )]
        
        success = tutorial_state_manager.reset_session(session_id)
        if success:
            return [types.TextContent(
                type="text",
                text="🔄 튜토리얼이 리셋되었습니다. 새로운 세션으로 다시 시작할 수 있습니다."
            )]
        else:
            return [types.TextContent(
                type="text",
                text="❌ 튜토리얼을 리셋할 수 없습니다."
            )]
    
    elif name == "get_tutorial_script":
        step_name = arguments.get("step")
        
        if step_name:
            try:
                step = TutorialStep(step_name)
                script = tutorial_state_manager.script
                step_message = script.get_step_message(step)
                
                return [types.TextContent(
                    type="text",
                    text=f"📋 **튜토리얼 스크립트 - {step_name}**\n\n"
                         f"**제목:** {step_message.title}\n\n"
                         f"**내용:**\n{step_message.content}\n\n"
                         f"**액션 텍스트:** {step_message.action_text or '없음'}\n\n"
                         f"**자연어 예시:**\n" + 
                         "\n".join([f"• {example}" for example in step_message.natural_language_examples])
                )]
            except ValueError:
                return [types.TextContent(
                    type="text",
                    text="❌ 잘못된 단계 이름입니다. 사용 가능한 단계: welcome, deploy_app, check_status, rollback, complete"
                )]
        else:
            # 모든 단계 정보 반환
            script = tutorial_state_manager.script
            all_steps = script.get_all_steps()
            
            script_info = "📋 **전체 튜토리얼 스크립트**\n\n"
            
            for i, step in enumerate(all_steps):
                step_message = script.get_step_message(step)
                script_info += f"**{i+1}. {step.value}**\n"
                script_info += f"제목: {step_message.title}\n"
                script_info += f"내용: {step_message.content[:100]}...\n\n"
            
            return [types.TextContent(
                type="text",
                text=script_info
            )]
    
    else:
        return [types.TextContent(
            type="text",
            text=f"❌ 알 수 없는 도구: {name}"
        )]
