"""Plugin protocol and metadata definitions.

Defines the NexusPlugin Protocol that all plugins must implement,
the PluginMetadata dataclass for describing plugins, and the
PluginStatus enum for tracking plugin lifecycle states.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PluginStatus(Enum):
    """Lifecycle status of a plugin.

    Attributes:
        loaded: Plugin is loaded and active.
        unloaded: Plugin has been unloaded or not yet loaded.
        error: Plugin encountered an error during loading or execution.
    """

    loaded = "loaded"
    unloaded = "unloaded"
    error = "error"


@dataclass
class PluginMetadata:
    """Metadata describing a NEXUS plugin.

    Attributes:
        name: Unique identifier for the plugin.
        version: Semantic version string (e.g., "1.0.0").
        author: Author or organization name.
        description: Human-readable description of what the plugin does.
        dependencies: List of other plugin names this plugin depends on.
    """

    name: str
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)


@runtime_checkable
class NexusPlugin(Protocol):
    """Protocol defining the interface for NEXUS plugins.

    All plugins must implement these lifecycle methods to be loadable
    by the PluginLoader and manageable by the PluginRegistry.
    """

    metadata: PluginMetadata

    def on_load(self) -> None:
        """Called when the plugin is loaded and registered.

        Perform any initialization, resource allocation, or setup needed
        for the plugin to function.
        """
        ...

    def on_unload(self) -> None:
        """Called when the plugin is unloaded and unregistered.

        Perform any cleanup, resource release, or teardown needed
        before the plugin is removed.
        """
        ...

    def get_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions provided by this plugin.

        Each tool is a dictionary describing the tool's name, description,
        parameters, and callable implementation.

        Returns:
            List of tool definition dictionaries.
        """
        ...

    def get_hooks(self) -> dict[str, Callable[..., Any]]:
        """Return hook handlers provided by this plugin.

        Keys are hook point names (matching HookPoint enum values),
        values are callable handlers to be invoked at those points.

        Returns:
            Dictionary mapping hook point names to handler callables.
        """
        ...
