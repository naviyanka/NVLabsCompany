"""Plugin registry for managing NEXUS plugin lifecycle.

Provides centralized management of loaded plugins including registration,
unregistration, listing, and retrieval. Integrates with HookManager to
automatically register plugin hooks when a plugin is loaded.
"""

from __future__ import annotations

import logging
from typing import Any

from nexus.plugins.hook_system import HookManager, HookPoint
from nexus.plugins.plugin_protocol import NexusPlugin, PluginMetadata, PluginStatus

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry managing loaded plugins and their lifecycle.

    Tracks all registered plugins, handles their load/unload lifecycle,
    and integrates with the HookManager to automatically wire up
    plugin hooks on registration.

    Attributes:
        hook_manager: The HookManager instance for hook integration.
    """

    def __init__(self, hook_manager: HookManager | None = None) -> None:
        """Initialize the plugin registry.

        Args:
            hook_manager: Optional HookManager for auto-registering plugin hooks.
                If None, a new HookManager is created.
        """
        self.hook_manager = hook_manager or HookManager()
        self._plugins: dict[str, NexusPlugin] = {}
        self._statuses: dict[str, PluginStatus] = {}

    def register(self, plugin: NexusPlugin) -> bool:
        """Register and load a plugin.

        Calls the plugin's on_load() method and stores it in the registry.
        If the plugin provides hooks, they are automatically registered
        with the HookManager.

        Args:
            plugin: The plugin instance to register.

        Returns:
            True if registration was successful, False on error.
        """
        name = plugin.metadata.name

        if name in self._plugins:
            logger.warning("Plugin '%s' is already registered", name)
            return False

        try:
            plugin.on_load()
        except Exception as exc:
            logger.error("Plugin '%s' failed on_load: %s", name, exc)
            self._statuses[name] = PluginStatus.error
            return False

        self._plugins[name] = plugin
        self._statuses[name] = PluginStatus.loaded

        # Auto-register hooks from the plugin
        self._register_hooks(plugin)

        logger.info("Plugin '%s' v%s registered successfully", name, plugin.metadata.version)
        return True

    def unregister(self, name: str) -> bool:
        """Unregister and unload a plugin by name.

        Calls the plugin's on_unload() method and removes it from the
        registry. Also removes all hook handlers associated with the plugin.

        Args:
            name: The name of the plugin to unregister.

        Returns:
            True if the plugin was found and unregistered, False otherwise.
        """
        if name not in self._plugins:
            logger.warning("Plugin '%s' is not registered", name)
            return False

        plugin = self._plugins[name]

        try:
            plugin.on_unload()
        except Exception as exc:
            logger.error("Plugin '%s' failed on_unload: %s", name, exc)

        # Remove hooks registered by this plugin
        self.hook_manager.unregister_all(name)

        del self._plugins[name]
        self._statuses[name] = PluginStatus.unloaded

        logger.info("Plugin '%s' unregistered", name)
        return True

    def list_plugins(self) -> list[PluginMetadata]:
        """List metadata for all currently registered plugins.

        Returns:
            List of PluginMetadata for all loaded plugins.
        """
        return [plugin.metadata for plugin in self._plugins.values()]

    def get_plugin(self, name: str) -> NexusPlugin | None:
        """Get a registered plugin by name.

        Args:
            name: The name of the plugin to retrieve.

        Returns:
            The plugin instance, or None if not found.
        """
        return self._plugins.get(name)

    def get_status(self, name: str) -> PluginStatus | None:
        """Get the status of a plugin by name.

        Args:
            name: The name of the plugin to check.

        Returns:
            The plugin status, or None if never registered.
        """
        return self._statuses.get(name)

    @property
    def plugin_count(self) -> int:
        """Get the number of currently registered plugins.

        Returns:
            Count of loaded plugins.
        """
        return len(self._plugins)

    def _register_hooks(self, plugin: NexusPlugin) -> None:
        """Register hooks from a plugin with the HookManager.

        Extracts hook handlers from the plugin and registers them
        with the appropriate hook points.

        Args:
            plugin: The plugin whose hooks to register.
        """
        try:
            hooks = plugin.get_hooks()
        except Exception as exc:
            logger.error(
                "Plugin '%s' failed get_hooks: %s", plugin.metadata.name, exc
            )
            return

        hook_point_map = {point.value: point for point in HookPoint}

        for hook_name, handler in hooks.items():
            hook_point = hook_point_map.get(hook_name)
            if hook_point is None:
                logger.warning(
                    "Plugin '%s' registered unknown hook point: %s",
                    plugin.metadata.name,
                    hook_name,
                )
                continue

            self.hook_manager.register(
                hook_point=hook_point,
                callback=handler,
                name=plugin.metadata.name,
            )
