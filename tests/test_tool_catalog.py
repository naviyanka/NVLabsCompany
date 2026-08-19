"""Tests for the Tool Catalog module."""

from unittest.mock import patch

from nexus.tools.tool_catalog import (
    BASE_TOOLS,
    ToolKind,
    ToolSpec,
    get_setup_status,
    probe_tool,
    tool_catalog,
)


class TestToolKindEnum:
    """Tests for the ToolKind enumeration."""

    def test_prerequisite_value(self) -> None:
        """ToolKind.prerequisite has correct string value."""
        assert ToolKind.prerequisite == "prerequisite"
        assert ToolKind.prerequisite.value == "prerequisite"

    def test_memory_value(self) -> None:
        """ToolKind.memory has correct string value."""
        assert ToolKind.memory == "memory"
        assert ToolKind.memory.value == "memory"

    def test_engine_value(self) -> None:
        """ToolKind.engine has correct string value."""
        assert ToolKind.engine == "engine"
        assert ToolKind.engine.value == "engine"

    def test_is_str_enum(self) -> None:
        """ToolKind members are strings."""
        assert isinstance(ToolKind.prerequisite, str)
        assert isinstance(ToolKind.memory, str)
        assert isinstance(ToolKind.engine, str)


class TestToolSpec:
    """Tests for the ToolSpec dataclass."""

    def test_frozen(self) -> None:
        """ToolSpec instances are immutable."""
        spec = ToolSpec(
            id="test",
            bin="test-bin",
            label="Test",
            kind=ToolKind.prerequisite,
            why="Testing.",
            essential=True,
            install_posix="apt install test",
            install_win32="winget install test",
        )
        try:
            spec.id = "changed"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass

    def test_docs_url_defaults_none(self) -> None:
        """ToolSpec.docs_url defaults to None."""
        spec = ToolSpec(
            id="test",
            bin=None,
            label="Test",
            kind=ToolKind.memory,
            why="Testing.",
            essential=False,
            install_posix="",
            install_win32="",
        )
        assert spec.docs_url is None

    def test_all_fields(self) -> None:
        """ToolSpec stores all fields correctly."""
        spec = ToolSpec(
            id="my-tool",
            bin="mytool",
            label="My Tool",
            kind=ToolKind.engine,
            why="Does things.",
            essential=True,
            install_posix="install-it",
            install_win32="install-it-win",
            docs_url="https://example.com",
        )
        assert spec.id == "my-tool"
        assert spec.bin == "mytool"
        assert spec.label == "My Tool"
        assert spec.kind == ToolKind.engine
        assert spec.why == "Does things."
        assert spec.essential is True
        assert spec.install_posix == "install-it"
        assert spec.install_win32 == "install-it-win"
        assert spec.docs_url == "https://example.com"


class TestBaseTool:
    """Tests for the BASE_TOOLS list."""

    def test_base_tools_has_four_entries(self) -> None:
        """BASE_TOOLS contains exactly 4 entries."""
        assert len(BASE_TOOLS) == 4

    def test_uv_entry(self) -> None:
        """uv tool entry has correct properties."""
        uv = next(t for t in BASE_TOOLS if t.id == "uv")
        assert uv.bin == "uv"
        assert uv.kind == ToolKind.prerequisite
        assert uv.essential is True
        assert "astral.sh" in uv.install_posix
        assert "astral.sh" in uv.install_win32
        assert uv.docs_url == "https://docs.astral.sh/uv/"

    def test_mempalace_entry(self) -> None:
        """mempalace tool entry has correct properties."""
        mp = next(t for t in BASE_TOOLS if t.id == "mempalace")
        assert mp.bin is None
        assert mp.kind == ToolKind.memory
        assert mp.essential is True
        assert "uv tool install mempalace" in mp.install_posix

    def test_git_entry(self) -> None:
        """git tool entry has correct properties."""
        git = next(t for t in BASE_TOOLS if t.id == "git")
        assert git.bin == "git"
        assert git.kind == ToolKind.prerequisite
        assert git.essential is True
        assert git.docs_url == "https://git-scm.com/downloads"

    def test_node_entry(self) -> None:
        """node tool entry has correct properties."""
        node = next(t for t in BASE_TOOLS if t.id == "node")
        assert node.bin == "node"
        assert node.kind == ToolKind.prerequisite
        assert node.essential is False
        assert node.docs_url == "https://nodejs.org"


class TestToolCatalog:
    """Tests for the tool_catalog() function."""

    def test_includes_base_tools(self) -> None:
        """tool_catalog() includes all BASE_TOOLS entries."""
        catalog = tool_catalog()
        base_ids = {t.id for t in BASE_TOOLS}
        catalog_ids = {t.id for t in catalog}
        assert base_ids.issubset(catalog_ids)

    def test_includes_engine_entries(self) -> None:
        """tool_catalog() includes engine entries from provider presets."""
        catalog = tool_catalog()
        engine_entries = [t for t in catalog if t.kind == ToolKind.engine]
        assert len(engine_entries) > 0

    def test_engine_entries_have_prefix(self) -> None:
        """Engine entries have 'engine:' ID prefix."""
        catalog = tool_catalog()
        engine_entries = [t for t in catalog if t.kind == ToolKind.engine]
        for entry in engine_entries:
            assert entry.id.startswith("engine:")

    def test_excludes_custom_provider(self) -> None:
        """tool_catalog() excludes the 'custom' provider preset."""
        catalog = tool_catalog()
        ids = {t.id for t in catalog}
        assert "engine:custom" not in ids

    def test_claude_engine_is_essential(self) -> None:
        """Claude engine entry is marked essential."""
        catalog = tool_catalog()
        claude = next(t for t in catalog if t.id == "engine:claude")
        assert claude.essential is True
        assert claude.bin == "claude"

    def test_non_claude_engines_not_essential(self) -> None:
        """Non-Claude engine entries are not essential."""
        catalog = tool_catalog()
        engines = [
            t for t in catalog
            if t.kind == ToolKind.engine and t.id != "engine:claude"
        ]
        for entry in engines:
            assert entry.essential is False

    def test_engine_why_format(self) -> None:
        """Engine entries have 'Agent engine - <bin>.' as why."""
        catalog = tool_catalog()
        engines = [t for t in catalog if t.kind == ToolKind.engine]
        for entry in engines:
            assert entry.why == f"Agent engine - {entry.bin}."

    def test_catalog_size(self) -> None:
        """Catalog has BASE_TOOLS + engine entries (total > 4)."""
        catalog = tool_catalog()
        assert len(catalog) > len(BASE_TOOLS)


class TestProbeTool:
    """Tests for the probe_tool() function."""

    def test_probe_finds_existing_binary(self) -> None:
        """probe_tool returns path when binary exists."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/git"
            result = probe_tool("git")
            assert result == "/usr/bin/git"
            mock_which.assert_called_once_with("git")

    def test_probe_returns_none_for_missing(self) -> None:
        """probe_tool returns None when binary is not found."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = None
            result = probe_tool("nonexistent-tool")
            assert result is None
            mock_which.assert_called_once_with("nonexistent-tool")


class TestGetSetupStatus:
    """Tests for the get_setup_status() function."""

    def test_returns_all_catalog_entries(self) -> None:
        """get_setup_status() returns one entry per catalog tool."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = None
            status = get_setup_status()
            catalog = tool_catalog()
            assert len(status) == len(catalog)

    def test_found_true_when_binary_exists(self) -> None:
        """Entry shows found=True when probe finds the binary."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/git"
            status = get_setup_status()
            git_entry = next(e for e in status if e["id"] == "git")
            assert git_entry["found"] is True
            assert git_entry["path"] == "/usr/bin/git"

    def test_found_false_when_binary_missing(self) -> None:
        """Entry shows found=False when probe cannot find the binary."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = None
            status = get_setup_status()
            git_entry = next(e for e in status if e["id"] == "git")
            assert git_entry["found"] is False
            assert git_entry["path"] is None

    def test_no_bin_entry_always_not_found(self) -> None:
        """Entries with bin=None always show found=False."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/something"
            status = get_setup_status()
            mp_entry = next(e for e in status if e["id"] == "mempalace")
            assert mp_entry["found"] is False
            assert mp_entry["path"] is None

    def test_entry_contains_expected_fields(self) -> None:
        """Each status entry has all expected fields."""
        with patch("nexus.tools.tool_catalog.shutil.which") as mock_which:
            mock_which.return_value = None
            status = get_setup_status()
            expected_keys = {
                "id", "bin", "label", "kind", "why", "essential",
                "install_posix", "install_win32", "docs_url", "found", "path",
            }
            for entry in status:
                assert set(entry.keys()) == expected_keys
