"""Plugin SDK for NEXUS extensibility.

Provides a protocol-based plugin system with lifecycle hooks for extending
NEXUS capabilities. Plugins can register tools, hook into task execution,
tool calls, and agent lifecycle events.

Components:
- NexusPlugin: Protocol defining the plugin interface
- PluginMetadata: Metadata about a plugin (name, version, author, etc.)
- PluginStatus: Enum for plugin lifecycle states
- HookPoint: Enum of available hook points in the system
- HookContext: Context object passed to hook handlers
- HookManager: Manages hook registration and execution
- PluginLoader: Discovers and loads plugins from the filesystem
- PluginRegistry: Manages plugin lifecycle (register/unregister/list/get)
"""

from __future__ import annotations

from nexus.plugins.hook_system import HookContext, HookManager, HookPoint
from nexus.plugins.plugin_loader import PluginLoader
from nexus.plugins.plugin_protocol import NexusPlugin, PluginMetadata, PluginStatus
from nexus.plugins.plugin_registry import PluginRegistry

__all__ = [
    "HookContext",
    "HookManager",
    "HookPoint",
    "NexusPlugin",
    "PluginLoader",
    "PluginMetadata",
    "PluginRegistry",
    "PluginStatus",
]
