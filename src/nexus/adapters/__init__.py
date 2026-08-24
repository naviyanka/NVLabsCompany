"""NEXUS Agent Adapters - concrete implementations of the AgentAdapter Protocol.

This module provides adapter implementations for various AI systems:
- OpenAIAdapter: OpenAI chat completions (GPT-4o, o1, o3, etc.)
- AnthropicAdapter: Anthropic Claude models
- OllamaAdapter: Local Ollama models
- ClaudeCodeAdapter: Claude Code CLI as subprocess
- HTTPAdapter: Generic HTTP agent endpoints
- MCPAgentAdapter: MCP server-based execution
- AzureOpenAIAdapter: Azure-hosted OpenAI models
- BedrockAdapter: AWS Bedrock models (Claude, Titan)
- GoogleGeminiAdapter: Google Gemini generative AI models

Additionally provides:
- BaseAdapter: Abstract base class with common adapter logic
- AdapterRegistry: Factory pattern for creating and managing adapters
- AgentProviderID: Enum of supported agent CLI providers
- AgentProviderPreset: Frozen dataclass describing provider spawn metadata
- PROVIDER_PRESETS: Complete mapping of all provider presets
- get_preset: Lookup function with Claude fallback
"""

from nexus.adapters.anthropic_adapter import AnthropicAdapter
from nexus.adapters.azure_adapter import AzureOpenAIAdapter
from nexus.adapters.base import BaseAdapter
from nexus.adapters.bedrock_adapter import BedrockAdapter
from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter
from nexus.adapters.google_adapter import GoogleGeminiAdapter
from nexus.adapters.hermes_adapter import HermesAdapter
from nexus.adapters.http_adapter import HTTPAdapter
from nexus.adapters.mcp_adapter import MCPAgentAdapter
from nexus.adapters.ollama_adapter import OllamaAdapter
from nexus.adapters.openai_adapter import OpenAIAdapter
from nexus.adapters.provider_presets import (
    AgentProviderID,
    AgentProviderPreset,
    PROVIDER_PRESETS,
    get_preset,
)
from nexus.adapters.registry import AdapterRegistry

__all__ = [
    "BaseAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "OllamaAdapter",
    "HermesAdapter",
    "ClaudeCodeAdapter",
    "HTTPAdapter",
    "MCPAgentAdapter",
    "AzureOpenAIAdapter",
    "BedrockAdapter",
    "GoogleGeminiAdapter",
    "AdapterRegistry",
    "AgentProviderID",
    "AgentProviderPreset",
    "PROVIDER_PRESETS",
    "get_preset",
]
