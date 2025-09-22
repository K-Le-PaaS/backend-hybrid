from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .errors import MCPExternalError


@dataclass
class MCPMessage:
    """Standard MCP message format."""
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class MCPMessageConverter:
    """Converts between internal and external MCP message formats."""
    
    @staticmethod
    def to_external_tool_call(tool_name: str, arguments: Dict[str, Any]) -> MCPMessage:
        """Convert internal tool call to external MCP format."""
        return MCPMessage(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments
            }
        )
    
    @staticmethod
    def to_external_list_tools() -> MCPMessage:
        """Convert list tools request to external MCP format."""
        return MCPMessage(
            method="tools/list"
        )
    
    @staticmethod
    def to_external_health_check() -> MCPMessage:
        """Convert health check to external MCP format."""
        return MCPMessage(
            method="ping"
        )
    
    @staticmethod
    def from_external_response(message: MCPMessage) -> Dict[str, Any]:
        """Convert external MCP response to internal format."""
        if message.error:
            raise MCPExternalError(
                code="bad_request",
                message=message.error.get("message", "External MCP error"),
                details=message.error
            )
        
        if message.method == "tools/list":
            return {
                "tools": message.result.get("tools", []) if message.result else []
            }
        
        if message.method == "tools/call":
            return {
                "ok": True,
                "content": message.result
            }
        
        if message.method == "pong":
            return {
                "ok": True,
                "connected": True,
                "server_status": "healthy"
            }
        
        return {
            "ok": True,
            "content": message.result
        }
    
    @staticmethod
    def parse_external_message(data: str) -> MCPMessage:
        """Parse external MCP message from JSON string."""
        try:
            parsed = json.loads(data)
            return MCPMessage(
                jsonrpc=parsed.get("jsonrpc", "2.0"),
                id=parsed.get("id"),
                method=parsed.get("method"),
                params=parsed.get("params"),
                result=parsed.get("result"),
                error=parsed.get("error")
            )
        except json.JSONDecodeError as e:
            raise MCPExternalError(
                code="bad_request",
                message=f"Invalid JSON in MCP message: {e}"
            )
    
    @staticmethod
    def to_external_json(message: MCPMessage) -> str:
        """Convert MCP message to JSON string."""
        data = {
            "jsonrpc": message.jsonrpc
        }
        
        if message.id is not None:
            data["id"] = message.id
        
        if message.method is not None:
            data["method"] = message.method
        
        if message.params is not None:
            data["params"] = message.params
        
        if message.result is not None:
            data["result"] = message.result
        
        if message.error is not None:
            data["error"] = message.error
        
        return json.dumps(data, ensure_ascii=False)


class MCPRequestHandler:
    """Handles MCP requests and responses."""
    
    def __init__(self, external_client):
        self.external_client = external_client
        self.converter = MCPMessageConverter()
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool call request."""
        # Convert to external format
        external_message = self.converter.to_external_tool_call(tool_name, arguments)
        
        # Send to external MCP server
        response_data = await self.external_client.call_tool(tool_name, arguments)
        
        # Convert response back to internal format
        return response_data
    
    async def handle_list_tools(self) -> List[Dict[str, Any]]:
        """Handle list tools request."""
        # Convert to external format
        external_message = self.converter.to_external_list_tools()
        
        # Send to external MCP server
        tools = await self.external_client.list_tools()
        
        # Return tools in internal format
        return tools
    
    async def handle_health_check(self) -> Dict[str, Any]:
        """Handle health check request."""
        # Convert to external format
        external_message = self.converter.to_external_health_check()
        
        # Send to external MCP server
        health = await self.external_client.health()
        
        # Return health status in internal format
        return health

