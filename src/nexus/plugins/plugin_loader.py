"""Plugin loader for discovering and loading NEXUS plugins.

Provides safe, sandboxed plugin loading from the filesystem. Validates
that loaded modules contain classes implementing the NexusPlugin protocol
before making them available to the system.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from nexus.plugins.plugin_protocol import NexusPlugin, PluginMetadata

logger = logging.getLogger(__name__)


def sandboxed_import(path: Path) -> Any | None:
    """Import a Python module from a file path in a restricted namespace.

    Catches ImportError and AttributeError gracefully, returning None
    if the module cannot be loaded. Does not expose the module to the
    global sys.modules namespace permanently on failure.

    Args:
        path: Path to the Python file to import.

    Returns:
        The loaded module object, or None if loading failed.
    """
    module_name = f"_nexus_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for %s", path)
            return None

        module = importlib.util.module_from_spec(spec)
        # Temporarily add to sys.modules for relative imports within the plugin
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except ImportError as exc:
        logger.warning("ImportError loading plugin from %s: %s", path, exc)
        # Clean up sys.modules on failure
        sys.modules.pop(module_name, None)
        return None
    except AttributeError as exc:
        logger.warning("AttributeError loading plugin from %s: %s", path, exc)
        sys.modules.pop(module_name, None)
        return None
    except Exception as exc:
        logger.warning("Unexpected error loading plugin from %s: %s", path, exc)
        sys.modules.pop(module_name, None)
        return None


def _find_plugin_class(module: Any) -> type | None:
    """Find a class in a module that implements the NexusPlugin protocol.

    Scans all attributes in the module looking for a class that has
    the required protocol methods (on_load, on_unload, get_tools, get_hooks)
    and a metadata attribute.

    Args:
        module: The imported module to scan.

    Returns:
        The plugin class, or None if no conforming class is found.
    """
    for attr_name in dir(module):
        attr = getattr(module, attr_name, None)
        if attr is None or not isinstance(attr, type):
            continue
        # Check for required protocol methods and metadata
        has_on_load = callable(getattr(attr, "on_load", None))
        has_on_unload = callable(getattr(attr, "on_unload", None))
        has_get_tools = callable(getattr(attr, "get_tools", None))
        has_get_hooks = callable(getattr(attr, "get_hooks", None))
        has_metadata = hasattr(attr, "metadata")
        if has_on_load and has_on_unload and has_get_tools and has_get_hooks and has_metadata:
            return attr
    return None


def discover_plugins(directory: Path) -> list[PluginMetadata]:
    """Discover plugins from a directory by scanning Python files.

    Looks for Python files that contain a class implementing the
    NexusPlugin protocol and extracts their metadata.

    Args:
        directory: Path to the directory to scan for plugins.

    Returns:
        List of PluginMetadata for discovered plugins.
    """
    discovered: list[PluginMetadata] = []

    if not directory.is_dir():
        logger.warning("Plugin directory does not exist: %s", directory)
        return discovered

    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module = sandboxed_import(py_file)
        if module is None:
            continue

        plugin_class = _find_plugin_class(module)
        if plugin_class is None:
            continue

        # Extract metadata from the class
        metadata = getattr(plugin_class, "metadata", None)
        if isinstance(metadata, PluginMetadata):
            discovered.append(metadata)
        else:
            # Try to construct metadata from class name
            discovered.append(
                PluginMetadata(
                    name=plugin_class.__name__,
                    description=plugin_class.__doc__ or "",
                )
            )

    return discovered


def load_plugin(path: Path) -> NexusPlugin | None:
    """Load a plugin from a Python file path.

    Imports the module, finds the plugin class, instantiates it,
    and returns the instance if it conforms to the NexusPlugin protocol.

    Args:
        path: Path to the Python file containing the plugin.

    Returns:
        An instantiated NexusPlugin, or None if loading failed.
    """
    module = sandboxed_import(path)
    if module is None:
        return None

    plugin_class = _find_plugin_class(module)
    if plugin_class is None:
        logger.warning("No NexusPlugin-conforming class found in %s", path)
        return None

    try:
        instance = plugin_class()
        return instance
    except Exception as exc:
        logger.warning("Failed to instantiate plugin from %s: %s", path, exc)
        return None


class PluginLoader:
    """High-level plugin loader for managing plugin discovery and loading.

    Wraps the module-level functions with state management for
    tracking which plugins have been discovered and loaded.

    Attributes:
        plugin_directory: The directory to scan for plugins.
    """

    def __init__(self, plugin_directory: Path | None = None) -> None:
        """Initialize the plugin loader.

        Args:
            plugin_directory: Optional directory path to scan for plugins.
                If None, discovery will return empty results until set.
        """
        self.plugin_directory = plugin_directory
        self._discovered: list[PluginMetadata] = []

    def discover(self) -> list[PluginMetadata]:
        """Discover available plugins in the configured directory.

        Returns:
            List of PluginMetadata for discovered plugins.
        """
        if self.plugin_directory is None:
            return []
        self._discovered = discover_plugins(self.plugin_directory)
        return self._discovered

    def load(self, path: Path) -> NexusPlugin | None:
        """Load a plugin from a specific file path.

        Args:
            path: Path to the Python file containing the plugin.

        Returns:
            An instantiated NexusPlugin, or None if loading failed.
        """
        return load_plugin(path)

    @property
    def discovered_plugins(self) -> list[PluginMetadata]:
        """Get the list of previously discovered plugin metadata.

        Returns:
            List of PluginMetadata from the last discover() call.
        """
        return list(self._discovered)
