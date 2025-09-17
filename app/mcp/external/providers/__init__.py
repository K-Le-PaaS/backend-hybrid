"""External MCP provider clients."""

from .github import GitHubMCPClient
from .slack import SlackMCPClient

__all__ = ["GitHubMCPClient", "SlackMCPClient"]


