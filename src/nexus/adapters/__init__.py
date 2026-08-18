"""NEXUS Agent Adapters - concrete implementations of the AgentAdapter Protocol.

This module provides adapter implementations for various AI systems:
- OpenAIAdapter: OpenAI chat completions (GPT-4o, o1, o3, etc.)
- AnthropicAdapter: Anthropic Claude models
- OllamaAdapter: Local Ollama models
- ClaudeCodeAdapter: Claude Code CLI as subprocess
- HTTPAdapter: Generic HTTP agent endpoints
- MCPAgentAdapter: MCP server-based execution

Additionally provides:
- BaseAdapter: Abstract base class with common adapter logic
- AdapterRegistry: Factory pattern for creating and managing adapters
"""

from nexus.adapters.anthropic_adapter import AnthropicAdapter
from nexus.adapters.base import BaseAdapter
from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter
from nexus.adapters.http_adapter import HTTPAdapter
from nexus.adapters.mcp_adapter import MCPAgentAdapter
from nexus.adapters.ollama_adapter import OllamaAdapter
from nexus.adapters.openai_adapter import OpenAIAdapter
from nexus.adapters.registry import AdapterRegistry

__all__ = [
    "BaseAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "OllamaAdapter",
    "ClaudeCodeAdapter",
    "HTTPAdapter",
    "MCPAgentAdapter",
    "AdapterRegistry",
]
