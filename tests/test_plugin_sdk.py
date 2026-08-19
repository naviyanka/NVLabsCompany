"""Tests for the NEXUS Plugin SDK.

Validates plugin protocol conformance, HookManager registration/execution/error-isolation,
PluginLoader discovery and sandboxed import, and PluginRegistry lifecycle management.
"""

from __future__ import annotations

import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nexus.plugins import (
    HookContext,
    HookManager,
    HookPoint,
    NexusPlugin,
    PluginLoader,
    PluginMetadata,
    PluginRegistry,
    PluginStatus,
)
from nexus.plugins.plugin_loader import (
    discover_plugins,
    load_plugin,
    sandboxed_import,
)


# ---------------------------------------------------------------------------
# Sample plugin implementations for testing
# ---------------------------------------------------------------------------


class SamplePlugin:
    """A minimal plugin that conforms to the NexusPlugin protocol."""

    metadata = PluginMetadata(
        name="sample-plugin",
        version="1.0.0",
        author="Test Author",
        description="A sample plugin for testing",
        dependencies=[],
    )

    def __init__(self) -> None:
        self.loaded = False
        self.unloaded = False

    def on_load(self) -> None:
        self.loaded = True

    def on_unload(self) -> None:
        self.unloaded = True

    def get_tools(self) -> list[dict[str, Any]]:
        return [{"name": "sample_tool", "description": "A sample tool"}]

    def get_hooks(self) -> dict[str, Callable[..., Any]]:
        return {"pre_task_execute": self._pre_task_hook}

    def _pre_task_hook(self, context: HookContext) -> str:
        return "pre_task_executed"


class FailingPlugin:
    """A plugin that raises exceptions during lifecycle methods."""

    metadata = PluginMetadata(
        name="failing-plugin",
        version="0.1.0",
        author="Fail Author",
        description="A plugin that fails on load",
    )

    def on_load(self) -> None:
        raise RuntimeError("Plugin load failed intentionally")

    def on_unload(self) -> None:
        raise RuntimeError("Plugin unload failed intentionally")

    def get_tools(self) -> list[dict[str, Any]]:
        return []

    def get_hooks(self) -> dict[str, Callable[..., Any]]:
        return {}


class MultiHookPlugin:
    """A plugin with multiple hooks at different priorities."""

    metadata = PluginMetadata(
        name="multi-hook-plugin",
        version="2.0.0",
        author="Multi Author",
        description="A plugin with multiple hooks",
    )

    def __init__(self) -> None:
        self.call_log: list[str] = []

    def on_load(self) -> None:
        pass

    def on_unload(self) -> None:
        pass

    def get_tools(self) -> list[dict[str, Any]]:
        return []

    def get_hooks(self) -> dict[str, Callable[..., Any]]:
        return {
            "pre_task_execute": self._pre_task,
            "post_task_execute": self._post_task,
            "on_agent_create": self._on_agent_create,
        }

    def _pre_task(self, context: HookContext) -> str:
        self.call_log.append("pre_task")
        return "pre_task"

    def _post_task(self, context: HookContext) -> str:
        self.call_log.append("post_task")
        return "post_task"

    def _on_agent_create(self, context: HookContext) -> str:
        self.call_log.append("on_agent_create")
        return "on_agent_create"


# ---------------------------------------------------------------------------
# Test: Plugin Protocol Conformance
# ---------------------------------------------------------------------------


class TestNexusPluginProtocol:
    """Tests for NexusPlugin protocol conformance."""

    def test_sample_plugin_conforms_to_protocol(self):
        """SamplePlugin instances satisfy the NexusPlugin protocol."""
        plugin = SamplePlugin()
        assert isinstance(plugin, NexusPlugin)

    def test_failing_plugin_conforms_to_protocol(self):
        """FailingPlugin instances satisfy the NexusPlugin protocol."""
        plugin = FailingPlugin()
        assert isinstance(plugin, NexusPlugin)

    def test_multi_hook_plugin_conforms_to_protocol(self):
        """MultiHookPlugin instances satisfy the NexusPlugin protocol."""
        plugin = MultiHookPlugin()
        assert isinstance(plugin, NexusPlugin)

    def test_non_plugin_does_not_conform(self):
        """Non-plugin objects do not satisfy the protocol."""

        class NotAPlugin:
            pass

        obj = NotAPlugin()
        assert not isinstance(obj, NexusPlugin)

    def test_plugin_metadata_dataclass(self):
        """PluginMetadata stores all required fields."""
        meta = PluginMetadata(
            name="test",
            version="1.2.3",
            author="Author",
            description="Desc",
            dependencies=["dep1", "dep2"],
        )
        assert meta.name == "test"
        assert meta.version == "1.2.3"
        assert meta.author == "Author"
        assert meta.description == "Desc"
        assert meta.dependencies == ["dep1", "dep2"]

    def test_plugin_metadata_defaults(self):
        """PluginMetadata has sensible defaults."""
        meta = PluginMetadata(name="minimal")
        assert meta.version == "0.1.0"
        assert meta.author == ""
        assert meta.description == ""
        assert meta.dependencies == []

    def test_plugin_status_enum_values(self):
        """PluginStatus enum has all expected values."""
        assert PluginStatus.loaded.value == "loaded"
        assert PluginStatus.unloaded.value == "unloaded"
        assert PluginStatus.error.value == "error"


# ---------------------------------------------------------------------------
# Test: Hook System
# ---------------------------------------------------------------------------


class TestHookPoint:
    """Tests for the HookPoint enum."""

    def test_all_hook_points_exist(self):
        """All six hook points are defined."""
        expected = {
            "pre_task_execute",
            "post_task_execute",
            "pre_tool_call",
            "post_tool_call",
            "on_agent_create",
            "on_agent_terminate",
        }
        actual = {hp.value for hp in HookPoint}
        assert actual == expected

    def test_hook_point_count(self):
        """Exactly 6 hook points are defined."""
        assert len(HookPoint) == 6


class TestHookContext:
    """Tests for the HookContext dataclass."""

    def test_default_values(self):
        """HookContext has sensible defaults."""
        ctx = HookContext()
        assert ctx.agent_id is None
        assert ctx.task_id is None
        assert ctx.tool_name is None
        assert ctx.timestamp is not None
        assert ctx.metadata == {}

    def test_custom_values(self):
        """HookContext accepts custom values."""
        ctx = HookContext(
            agent_id="agent-1",
            task_id="task-1",
            tool_name="my_tool",
            metadata={"key": "value"},
        )
        assert ctx.agent_id == "agent-1"
        assert ctx.task_id == "task-1"
        assert ctx.tool_name == "my_tool"
        assert ctx.metadata == {"key": "value"}


class TestHookManager:
    """Tests for the HookManager class."""

    @pytest.fixture
    def hook_manager(self):
        """Provide a fresh HookManager instance."""
        return HookManager()

    def test_register_handler(self, hook_manager):
        """Registering a handler increments the handler count."""
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: None, name="test"
        )
        assert hook_manager.get_handler_count(HookPoint.pre_task_execute) == 1

    def test_register_multiple_handlers(self, hook_manager):
        """Multiple handlers can be registered for the same hook point."""
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: "a", name="handler_a"
        )
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: "b", name="handler_b"
        )
        assert hook_manager.get_handler_count(HookPoint.pre_task_execute) == 2

    def test_execute_calls_handlers(self, hook_manager):
        """Execute invokes all registered handlers."""
        results_log = []
        hook_manager.register(
            HookPoint.pre_task_execute,
            lambda ctx: results_log.append("called"),
            name="test",
        )
        ctx = HookContext(task_id="task-1")
        hook_manager.execute(HookPoint.pre_task_execute, ctx)
        assert results_log == ["called"]

    def test_execute_returns_results(self, hook_manager):
        """Execute returns results from all handlers."""
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: "result_1", name="h1"
        )
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: "result_2", name="h2"
        )
        ctx = HookContext()
        results = hook_manager.execute(HookPoint.pre_task_execute, ctx)
        assert results == ["result_1", "result_2"]

    def test_execute_error_isolation(self, hook_manager):
        """One handler crashing does not prevent others from running."""

        def failing_handler(ctx):
            raise ValueError("I crashed")

        def good_handler(ctx):
            return "success"

        hook_manager.register(
            HookPoint.pre_task_execute, failing_handler, name="bad"
        )
        hook_manager.register(
            HookPoint.pre_task_execute, good_handler, name="good"
        )

        ctx = HookContext()
        results = hook_manager.execute(HookPoint.pre_task_execute, ctx)
        # The good handler should still return its result
        assert results == ["success"]

    def test_execute_priority_ordering(self, hook_manager):
        """Handlers execute in priority order (lower number first)."""
        call_order = []

        hook_manager.register(
            HookPoint.pre_task_execute,
            lambda ctx: call_order.append("high"),
            priority=10,
            name="high_priority",
        )
        hook_manager.register(
            HookPoint.pre_task_execute,
            lambda ctx: call_order.append("low"),
            priority=1,
            name="low_priority",
        )
        hook_manager.register(
            HookPoint.pre_task_execute,
            lambda ctx: call_order.append("mid"),
            priority=5,
            name="mid_priority",
        )

        ctx = HookContext()
        hook_manager.execute(HookPoint.pre_task_execute, ctx)
        assert call_order == ["low", "mid", "high"]

    def test_unregister_handler(self, hook_manager):
        """Unregistering a handler removes it from the hook point."""
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: None, name="remove_me"
        )
        assert hook_manager.get_handler_count(HookPoint.pre_task_execute) == 1

        result = hook_manager.unregister(HookPoint.pre_task_execute, "remove_me")
        assert result is True
        assert hook_manager.get_handler_count(HookPoint.pre_task_execute) == 0

    def test_unregister_nonexistent_handler(self, hook_manager):
        """Unregistering a non-existent handler returns False."""
        result = hook_manager.unregister(HookPoint.pre_task_execute, "ghost")
        assert result is False

    def test_unregister_all(self, hook_manager):
        """unregister_all removes handlers from all hook points."""
        hook_manager.register(
            HookPoint.pre_task_execute, lambda ctx: None, name="plugin_a"
        )
        hook_manager.register(
            HookPoint.post_task_execute, lambda ctx: None, name="plugin_a"
        )
        hook_manager.register(
            HookPoint.on_agent_create, lambda ctx: None, name="plugin_b"
        )

        removed = hook_manager.unregister_all("plugin_a")
        assert removed == 2
        assert hook_manager.get_handler_count(HookPoint.pre_task_execute) == 0
        assert hook_manager.get_handler_count(HookPoint.post_task_execute) == 0
        assert hook_manager.get_handler_count(HookPoint.on_agent_create) == 1

    def test_empty_hook_point_returns_empty_results(self, hook_manager):
        """Executing a hook point with no handlers returns empty list."""
        ctx = HookContext()
        results = hook_manager.execute(HookPoint.post_tool_call, ctx)
        assert results == []


# ---------------------------------------------------------------------------
# Test: Plugin Loader
# ---------------------------------------------------------------------------


class TestSandboxedImport:
    """Tests for the sandboxed_import function."""

    def test_import_valid_module(self):
        """sandboxed_import loads a valid Python module."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("VALUE = 42\n")
            f.flush()
            path = Path(f.name)

        module = sandboxed_import(path)
        assert module is not None
        assert module.VALUE == 42
        path.unlink()

    def test_import_module_with_import_error(self):
        """sandboxed_import returns None for modules with import errors."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("import nonexistent_module_xyz_123\n")
            f.flush()
            path = Path(f.name)

        module = sandboxed_import(path)
        assert module is None
        path.unlink()

    def test_import_nonexistent_file(self):
        """sandboxed_import returns None for non-existent files."""
        path = Path("/tmp/nonexistent_plugin_xyz.py")
        module = sandboxed_import(path)
        assert module is None

    def test_import_syntax_error_module(self):
        """sandboxed_import returns None for modules with syntax errors."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def broken(:\n    pass\n")
            f.flush()
            path = Path(f.name)

        module = sandboxed_import(path)
        assert module is None
        path.unlink()


class TestPluginDiscovery:
    """Tests for plugin discovery from directories."""

    def test_discover_plugins_in_directory(self):
        """discover_plugins finds plugins in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "my_plugin.py"
            plugin_file.write_text(textwrap.dedent("""\
                from dataclasses import dataclass, field

                @dataclass
                class PluginMetadata:
                    name: str
                    version: str = "0.1.0"
                    author: str = ""
                    description: str = ""
                    dependencies: list = field(default_factory=list)

                class MyPlugin:
                    metadata = PluginMetadata(
                        name="my-plugin",
                        version="1.0.0",
                        author="Tester",
                        description="A test plugin",
                    )

                    def on_load(self):
                        pass

                    def on_unload(self):
                        pass

                    def get_tools(self):
                        return []

                    def get_hooks(self):
                        return {}
            """))

            discovered = discover_plugins(Path(tmpdir))
            assert len(discovered) == 1
            assert discovered[0].name == "my-plugin"

    def test_discover_skips_underscore_files(self):
        """discover_plugins skips files starting with underscore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hidden_file = Path(tmpdir) / "_hidden_plugin.py"
            hidden_file.write_text("class Hidden: pass\n")

            discovered = discover_plugins(Path(tmpdir))
            assert len(discovered) == 0

    def test_discover_nonexistent_directory(self):
        """discover_plugins returns empty list for non-existent directory."""
        discovered = discover_plugins(Path("/tmp/nonexistent_dir_xyz_abc"))
        assert discovered == []

    def test_discover_skips_non_plugin_files(self):
        """discover_plugins skips files without NexusPlugin classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            non_plugin = Path(tmpdir) / "not_a_plugin.py"
            non_plugin.write_text("x = 42\n")

            discovered = discover_plugins(Path(tmpdir))
            assert len(discovered) == 0


class TestLoadPlugin:
    """Tests for plugin loading from files."""

    def test_load_valid_plugin(self):
        """load_plugin loads and instantiates a valid plugin."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                from dataclasses import dataclass, field

                @dataclass
                class PluginMetadata:
                    name: str
                    version: str = "0.1.0"
                    author: str = ""
                    description: str = ""
                    dependencies: list = field(default_factory=list)

                class TestPlugin:
                    metadata = PluginMetadata(name="test-plugin", version="1.0.0")

                    def on_load(self):
                        pass

                    def on_unload(self):
                        pass

                    def get_tools(self):
                        return [{"name": "tool1"}]

                    def get_hooks(self):
                        return {}
            """))
            f.flush()
            path = Path(f.name)

        plugin = load_plugin(path)
        assert plugin is not None
        assert plugin.metadata.name == "test-plugin"
        assert plugin.get_tools() == [{"name": "tool1"}]
        path.unlink()

    def test_load_nonexistent_plugin(self):
        """load_plugin returns None for non-existent files."""
        plugin = load_plugin(Path("/tmp/nonexistent_xyz.py"))
        assert plugin is None

    def test_load_invalid_plugin(self):
        """load_plugin returns None for files without a plugin class."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("x = 42\n")
            f.flush()
            path = Path(f.name)

        plugin = load_plugin(path)
        assert plugin is None
        path.unlink()


class TestPluginLoaderClass:
    """Tests for the PluginLoader class."""

    def test_discover_with_directory(self):
        """PluginLoader.discover finds plugins in configured directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "sample.py"
            plugin_file.write_text(textwrap.dedent("""\
                from dataclasses import dataclass, field

                @dataclass
                class PluginMetadata:
                    name: str
                    version: str = "0.1.0"
                    author: str = ""
                    description: str = ""
                    dependencies: list = field(default_factory=list)

                class SamplePlugin:
                    metadata = PluginMetadata(name="sample", version="0.5.0")

                    def on_load(self): pass
                    def on_unload(self): pass
                    def get_tools(self): return []
                    def get_hooks(self): return {}
            """))

            loader = PluginLoader(plugin_directory=Path(tmpdir))
            discovered = loader.discover()
            assert len(discovered) == 1
            assert discovered[0].name == "sample"
            assert loader.discovered_plugins == discovered

    def test_discover_no_directory(self):
        """PluginLoader.discover returns empty when no directory is set."""
        loader = PluginLoader(plugin_directory=None)
        discovered = loader.discover()
        assert discovered == []

    def test_load_plugin(self):
        """PluginLoader.load loads a specific plugin file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                from dataclasses import dataclass, field

                @dataclass
                class PluginMetadata:
                    name: str
                    version: str = "0.1.0"
                    author: str = ""
                    description: str = ""
                    dependencies: list = field(default_factory=list)

                class LoaderTestPlugin:
                    metadata = PluginMetadata(name="loader-test", version="1.0.0")

                    def on_load(self): pass
                    def on_unload(self): pass
                    def get_tools(self): return []
                    def get_hooks(self): return {}
            """))
            f.flush()
            path = Path(f.name)

        loader = PluginLoader()
        plugin = loader.load(path)
        assert plugin is not None
        assert plugin.metadata.name == "loader-test"
        path.unlink()


# ---------------------------------------------------------------------------
# Test: Plugin Registry
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    """Tests for the PluginRegistry class."""

    @pytest.fixture
    def registry(self):
        """Provide a fresh PluginRegistry with a HookManager."""
        hook_manager = HookManager()
        return PluginRegistry(hook_manager=hook_manager)

    def test_register_plugin(self, registry):
        """Register loads and stores a plugin."""
        plugin = SamplePlugin()
        result = registry.register(plugin)
        assert result is True
        assert plugin.loaded is True
        assert registry.plugin_count == 1

    def test_register_duplicate_plugin(self, registry):
        """Registering the same plugin name twice fails."""
        plugin1 = SamplePlugin()
        plugin2 = SamplePlugin()
        registry.register(plugin1)
        result = registry.register(plugin2)
        assert result is False
        assert registry.plugin_count == 1

    def test_register_failing_plugin(self, registry):
        """Registering a plugin that fails on_load marks it as error."""
        plugin = FailingPlugin()
        result = registry.register(plugin)
        assert result is False
        assert registry.get_status("failing-plugin") == PluginStatus.error

    def test_unregister_plugin(self, registry):
        """Unregister calls on_unload and removes the plugin."""
        plugin = SamplePlugin()
        registry.register(plugin)
        result = registry.unregister("sample-plugin")
        assert result is True
        assert plugin.unloaded is True
        assert registry.plugin_count == 0
        assert registry.get_status("sample-plugin") == PluginStatus.unloaded

    def test_unregister_nonexistent(self, registry):
        """Unregistering a non-existent plugin returns False."""
        result = registry.unregister("ghost")
        assert result is False

    def test_list_plugins(self, registry):
        """list_plugins returns metadata for all registered plugins."""
        plugin = SamplePlugin()
        registry.register(plugin)
        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "sample-plugin"
        assert plugins[0].version == "1.0.0"

    def test_get_plugin(self, registry):
        """get_plugin retrieves a registered plugin by name."""
        plugin = SamplePlugin()
        registry.register(plugin)
        retrieved = registry.get_plugin("sample-plugin")
        assert retrieved is plugin

    def test_get_plugin_not_found(self, registry):
        """get_plugin returns None for non-existent plugins."""
        result = registry.get_plugin("ghost")
        assert result is None

    def test_hook_integration_on_register(self, registry):
        """Registering a plugin auto-registers its hooks."""
        plugin = SamplePlugin()
        registry.register(plugin)
        count = registry.hook_manager.get_handler_count(
            HookPoint.pre_task_execute
        )
        assert count == 1

    def test_hook_removal_on_unregister(self, registry):
        """Unregistering a plugin removes its hooks."""
        plugin = SamplePlugin()
        registry.register(plugin)
        registry.unregister("sample-plugin")
        count = registry.hook_manager.get_handler_count(
            HookPoint.pre_task_execute
        )
        assert count == 0

    def test_multi_hook_plugin_registers_all_hooks(self, registry):
        """A plugin with multiple hooks has them all registered."""
        plugin = MultiHookPlugin()
        registry.register(plugin)
        assert (
            registry.hook_manager.get_handler_count(HookPoint.pre_task_execute)
            == 1
        )
        assert (
            registry.hook_manager.get_handler_count(HookPoint.post_task_execute)
            == 1
        )
        assert (
            registry.hook_manager.get_handler_count(HookPoint.on_agent_create)
            == 1
        )

    def test_hook_execution_through_registry(self, registry):
        """Hooks registered via plugin can be executed through the hook manager."""
        plugin = SamplePlugin()
        registry.register(plugin)

        ctx = HookContext(task_id="task-42")
        results = registry.hook_manager.execute(
            HookPoint.pre_task_execute, ctx
        )
        assert results == ["pre_task_executed"]

    def test_registry_creates_default_hook_manager(self):
        """PluginRegistry creates a HookManager if none is provided."""
        registry = PluginRegistry()
        assert registry.hook_manager is not None
        assert isinstance(registry.hook_manager, HookManager)
