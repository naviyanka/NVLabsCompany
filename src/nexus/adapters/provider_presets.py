"""Agent Provider Presets - structured descriptors for all supported CLI agent providers.

Each provider declares how to build its spawn command (model/auto-mode flags) and
whether it accepts the hive's Claude-specific identity injection. Ported from
the upstream TypeScript AGENT_PROVIDER_PRESETS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentProviderID(str, Enum):
    """Identifier for each supported agent CLI provider."""

    claude = "claude"
    codex = "codex"
    grok = "grok"
    kimi = "kimi"
    antigravity = "antigravity"
    qwen = "qwen"
    opencode = "opencode"
    crush = "crush"
    pi = "pi"
    copilot = "copilot"
    custom = "custom"


@dataclass(frozen=True)
class AgentProviderPreset:
    """Structured descriptor for how a provider CLI is spawned and managed.

    Contains all metadata needed to build spawn commands, determine hive
    compatibility, and manage agent lifecycle.
    """

    id: AgentProviderID
    label: str
    default_command: str
    auto_mode_flag: str
    supports_model: bool = True
    model_flag: Optional[str] = None
    hive_aware: bool = False
    can_receive_inbox: bool = False
    hook_bridge: Optional[str] = None
    recommended_orchestrator_model: Optional[str] = None
    resume_flag: Optional[str] = None
    install_command: Optional[str] = None
    docs_url: Optional[str] = None
    non_interactive_env: dict[str, str] = field(default_factory=dict)


PROVIDER_PRESETS: dict[AgentProviderID, AgentProviderPreset] = {
    AgentProviderID.claude: AgentProviderPreset(
        id=AgentProviderID.claude,
        label="Claude Code",
        default_command="claude",
        auto_mode_flag="--permission-mode bypassPermissions",
        supports_model=True,
        model_flag="--model",
        hive_aware=True,
        can_receive_inbox=True,
        recommended_orchestrator_model="claude-opus-4-8[1m]",
        resume_flag="--resume",
        install_command="npm install -g @anthropic-ai/claude-code",
        docs_url="https://docs.claude.com/en/docs/claude-code",
    ),
    AgentProviderID.codex: AgentProviderPreset(
        id=AgentProviderID.codex,
        label="Codex \u00b7 GPT",
        default_command="codex",
        auto_mode_flag="--dangerously-bypass-approvals-and-sandbox",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        hook_bridge="codex",
        recommended_orchestrator_model="gpt-5-codex",
        non_interactive_env={"CODEX_NON_INTERACTIVE": "1"},
        install_command="npm install -g @openai/codex",
        docs_url="https://github.com/openai/codex",
    ),
    AgentProviderID.grok: AgentProviderPreset(
        id=AgentProviderID.grok,
        label="Grok \u00b7 xAI",
        default_command="grok",
        auto_mode_flag="--permission-mode bypassPermissions",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        hook_bridge="grok",
        resume_flag="--resume",
    ),
    AgentProviderID.kimi: AgentProviderPreset(
        id=AgentProviderID.kimi,
        label="Kimi Code",
        default_command="kimi",
        auto_mode_flag="--auto",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=False,
    ),
    AgentProviderID.antigravity: AgentProviderPreset(
        id=AgentProviderID.antigravity,
        label="Antigravity \u00b7 Gemini",
        default_command="agy",
        auto_mode_flag="--dangerously-skip-permissions",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        hook_bridge="agy",
        recommended_orchestrator_model="Gemini 3.1 Pro (High)",
        resume_flag="--conversation",
    ),
    AgentProviderID.qwen: AgentProviderPreset(
        id=AgentProviderID.qwen,
        label="Qwen (local available)",
        default_command="qwen",
        auto_mode_flag="--yolo",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        recommended_orchestrator_model="qwen3-coder-plus",
    ),
    AgentProviderID.opencode: AgentProviderPreset(
        id=AgentProviderID.opencode,
        label="OpenCode",
        default_command="opencode",
        auto_mode_flag="",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        install_command="npm install -g opencode-ai@latest",
        docs_url="https://opencode.ai/docs",
    ),
    AgentProviderID.crush: AgentProviderPreset(
        id=AgentProviderID.crush,
        label="Crush \u00b7 Charm",
        default_command="crush",
        auto_mode_flag="--yolo",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        recommended_orchestrator_model="openai/gpt-4o",
        resume_flag="--session",
        install_command="npm install -g @charmland/crush",
        docs_url="https://github.com/charmbracelet/crush",
    ),
    AgentProviderID.pi: AgentProviderPreset(
        id=AgentProviderID.pi,
        label="Pi",
        default_command="pi",
        auto_mode_flag="--approve",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=True,
        recommended_orchestrator_model="anthropic/claude-sonnet-4-5",
        resume_flag="--session",
        install_command="npm install -g --ignore-scripts @earendil-works/pi-coding-agent",
        docs_url="https://pi.dev/docs/latest",
        non_interactive_env={"PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"},
    ),
    AgentProviderID.copilot: AgentProviderPreset(
        id=AgentProviderID.copilot,
        label="Copilot",
        default_command="copilot",
        auto_mode_flag="-s --allow-all-tools --no-ask-user",
        supports_model=True,
        model_flag="--model",
        hive_aware=False,
        can_receive_inbox=False,
        recommended_orchestrator_model="claude-sonnet-4.5",
        resume_flag="--resume",
        install_command="npm install -g @github/copilot",
        docs_url="https://docs.github.com/copilot/concepts/agents/about-copilot-cli",
    ),
    AgentProviderID.custom: AgentProviderPreset(
        id=AgentProviderID.custom,
        label="Custom",
        default_command="",
        auto_mode_flag="",
        supports_model=False,
        hive_aware=False,
        can_receive_inbox=False,
    ),
}


def get_preset(provider_id: AgentProviderID) -> AgentProviderPreset:
    """Look up a provider preset by ID, falling back to Claude for unknown IDs.

    Args:
        provider_id: The provider identifier to look up.

    Returns:
        The matching AgentProviderPreset, or the Claude preset as fallback.
    """
    return PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS[AgentProviderID.claude])
