"""Adapter Registry - factory pattern for creating and managing adapter instances.

Provides registration of adapter types by name, configuration validation,
dynamic adapter loading, health checking, and capability advertisement.
"""

import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, AgentStatus


class AdapterRegistry:
    """Registry and factory for agent adapters.

    Manages adapter type registration, instantiation via factory pattern,
    configuration validation, health checking, and capability advertisement.
    Supports dynamic adapter loading (plugin-style) via register_adapter.
    """

    def __init__(self, auto_register: bool = True) -> None:
        """Initialize the adapter registry.

        Args:
            auto_register: If True, register all default adapters on init.
        """
        self._adapters: dict[str, type[BaseAdapter]] = {}
        self._instances: dict[str, BaseAdapter] = {}

        if auto_register:
            self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all built-in adapter types."""
        from nexus.adapters.anthropic_adapter import AnthropicAdapter
        from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter
        from nexus.adapters.cli_adapter import CLIAdapter
        from nexus.adapters.http_adapter import HTTPAdapter
        from nexus.adapters.mcp_adapter import MCPAgentAdapter
        from nexus.adapters.ollama_adapter import OllamaAdapter
        from nexus.adapters.openai_adapter import OpenAIAdapter

        self.register_adapter("openai", OpenAIAdapter)
        self.register_adapter("anthropic", AnthropicAdapter)
        self.register_adapter("ollama", OllamaAdapter)
        self.register_adapter("claude_code", ClaudeCodeAdapter)
        self.register_adapter("cli", CLIAdapter)
        self.register_adapter("http", HTTPAdapter)
        self.register_adapter("mcp", MCPAgentAdapter)

    def register_adapter(
        self, adapter_type: str, adapter_class: type[BaseAdapter]
    ) -> None:
        """Register an adapter type with the registry.

        Args:
            adapter_type: The string identifier for the adapter type.
            adapter_class: The adapter class to register.

        Raises:
            TypeError: If adapter_class is not a subclass of BaseAdapter.
        """
        if not (
            isinstance(adapter_class, type) and issubclass(adapter_class, BaseAdapter)
        ):
            raise TypeError(
                f"adapter_class must be a subclass of BaseAdapter, "
                f"got {adapter_class}"
            )
        self._adapters[adapter_type] = adapter_class

    def create_adapter(
        self, adapter_type: str, config: dict[str, Any] | None = None
    ) -> BaseAdapter:
        """Create a new adapter instance of the specified type.

        Args:
            adapter_type: The registered adapter type name.
            config: Optional configuration to validate against.

        Returns:
            A new instance of the requested adapter type.

        Raises:
            ValueError: If the adapter type is not registered.
        """
        if adapter_type not in self._adapters:
            raise ValueError(
                f"Unknown adapter type: '{adapter_type}'. "
                f"Available types: {list(self._adapters.keys())}"
            )

        adapter_class = self._adapters[adapter_type]
        instance = adapter_class()

        # Validate config if provided
        if config is not None:
            instance.validate_config(config)

        return instance

    def get_adapter_types(self) -> list[str]:
        """Get all registered adapter type names.

        Returns:
            List of registered adapter type identifiers.
        """
        return list(self._adapters.keys())

    def is_registered(self, adapter_type: str) -> bool:
        """Check if an adapter type is registered.

        Args:
            adapter_type: The adapter type to check.

        Returns:
            True if the adapter type is registered.
        """
        return adapter_type in self._adapters

    def validate_config(
        self, adapter_type: str, config: dict[str, Any]
    ) -> bool:
        """Validate configuration for a specific adapter type.

        Args:
            adapter_type: The adapter type to validate against.
            config: The configuration dictionary to validate.

        Returns:
            True if validation passes.

        Raises:
            ValueError: If the adapter type is unknown or config is invalid.
        """
        if adapter_type not in self._adapters:
            raise ValueError(f"Unknown adapter type: '{adapter_type}'")

        adapter = self._adapters[adapter_type]()
        adapter.validate_config(config)
        return True

    async def health_check(
        self, adapter_type: str, config: dict[str, Any]
    ) -> bool:
        """Perform a health check on an adapter by creating and terminating a session.

        Creates a temporary session and immediately terminates it as a
        smoke test to verify the adapter can function.

        Args:
            adapter_type: The adapter type to health check.
            config: Configuration for the test session.

        Returns:
            True if the health check passes.
        """
        try:
            adapter = self.create_adapter(adapter_type, config)
            agent_id = uuid.uuid4()
            session = await adapter.create_session(agent_id, config)
            await adapter.terminate(session)
            return True
        except Exception:
            return False

    def get_capabilities(self, adapter_type: str) -> list[str]:
        """Get the capabilities advertised by an adapter type.

        Args:
            adapter_type: The adapter type to query.

        Returns:
            List of capability identifiers.

        Raises:
            ValueError: If the adapter type is unknown.
        """
        if adapter_type not in self._adapters:
            raise ValueError(f"Unknown adapter type: '{adapter_type}'")

        adapter = self._adapters[adapter_type]()
        return adapter._get_capabilities()

    def unregister_adapter(self, adapter_type: str) -> bool:
        """Unregister an adapter type from the registry.

        Args:
            adapter_type: The adapter type to remove.

        Returns:
            True if the adapter was removed, False if it was not registered.
        """
        if adapter_type in self._adapters:
            del self._adapters[adapter_type]
            return True
        return False
