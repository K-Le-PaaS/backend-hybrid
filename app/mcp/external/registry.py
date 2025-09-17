from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass

from .interfaces import ExternalMCPClient
from .handlers import MCPHandler, MCPHandlerPool, MCPHandlerConfig
from .providers.github import GitHubMCPClient
from .providers.slack import SlackMCPClient
from .errors import MCPExternalError


@dataclass
class MCPProviderConfig:
    """Configuration for MCP provider."""
    name: str
    provider_type: str
    base_url: str
    config: Dict[str, Any]
    enabled: bool = True


class MCPProviderRegistry:
    """Registry for MCP providers and their configurations."""
    
    _providers: Dict[str, Type[ExternalMCPClient]] = {
        "github": GitHubMCPClient,
        "slack": SlackMCPClient,
        # Add more providers as they are implemented
    }
    
    def __init__(self):
        self.configs: Dict[str, MCPProviderConfig] = {}
        self.handler_pool = MCPHandlerPool()
    
    def register_provider(self, provider_type: str, client_class: Type[ExternalMCPClient]) -> None:
        """Register a new provider type."""
        self._providers[provider_type] = client_class
    
    def add_provider_config(self, config: MCPProviderConfig) -> None:
        """Add a provider configuration."""
        self.configs[config.name] = config
    
    def get_provider_config(self, name: str) -> Optional[MCPProviderConfig]:
        """Get provider configuration by name."""
        return self.configs.get(name)
    
    def list_providers(self) -> List[str]:
        """List all configured providers."""
        return [name for name, config in self.configs.items() if config.enabled]
    
    async def create_handler(self, name: str) -> Optional[MCPHandler]:
        """Create a handler for a provider."""
        config = self.get_provider_config(name)
        if not config or not config.enabled:
            return None
        
        provider_class = self._providers.get(config.provider_type)
        if not provider_class:
            raise MCPExternalError(
                code="internal",
                message=f"Unknown provider type: {config.provider_type}"
            )
        
        # Create external client
        external_client = provider_class(
            base_url=config.base_url,
            **config.config
        )
        
        # Create handler
        handler = MCPHandler(external_client)
        
        # Add to pool
        self.handler_pool.add_handler(name, handler)
        
        return handler
    
    async def initialize_provider(self, name: str) -> bool:
        """Initialize a specific provider."""
        try:
            handler = await self.create_handler(name)
            if handler:
                await handler.initialize()
                return True
            return False
        except Exception as e:
            raise MCPExternalError(
                code="internal",
                message=f"Failed to initialize provider {name}: {e}"
            )
    
    async def initialize_all_providers(self) -> Dict[str, bool]:
        """Initialize all enabled providers."""
        results = {}
        for name in self.list_providers():
            try:
                results[name] = await self.initialize_provider(name)
            except Exception as e:
                results[name] = False
        return results
    
    async def cleanup_all_providers(self) -> None:
        """Cleanup all providers."""
        await self.handler_pool.cleanup_all()
    
    def get_handler(self, name: str) -> Optional[MCPHandler]:
        """Get handler by name."""
        return self.handler_pool.get_handler(name)
    
    async def call_tool(self, provider_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a specific provider."""
        handler = self.get_handler(provider_name)
        if not handler:
            raise MCPExternalError(
                code="not_found",
                message=f"Provider {provider_name} not found"
            )
        
        return await handler.call_tool(tool_name, arguments)
    
    async def list_tools(self, provider_name: str) -> List[Dict[str, Any]]:
        """List tools for a specific provider."""
        handler = self.get_handler(provider_name)
        if not handler:
            raise MCPExternalError(
                code="not_found",
                message=f"Provider {provider_name} not found"
            )
        
        return await handler.list_tools()
    
    async def health_check(self, provider_name: str) -> Dict[str, Any]:
        """Check health of a specific provider."""
        handler = self.get_handler(provider_name)
        if not handler:
            raise MCPExternalError(
                code="not_found",
                message=f"Provider {provider_name} not found"
            )
        
        return await handler.health_check()
    
    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Check health of all providers."""
        return await self.handler_pool.health_check_all()


# Global registry instance
mcp_registry = MCPProviderRegistry()
