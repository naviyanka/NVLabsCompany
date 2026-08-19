"""Tests for the semantic memory manager module."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from nexus.memory.semantic import EmbeddingModel, SemanticMemoryManager


class TestSemanticMemoryStatus:
    """Tests for SemanticMemoryManager.status() and availability."""

    def test_status_unavailable(self) -> None:
        """Report unavailable when mempalace not on PATH."""
        with patch("shutil.which", return_value=None):
            mgr = SemanticMemoryManager(palace_path="/tmp/palace")
            status = mgr.status()

        assert status["available"] is False
        assert status["palace_path"] == "/tmp/palace"
        assert status["model"] == "minilm"
        assert status["bin"] is None

    def test_status_available(self) -> None:
        """Report available when mempalace is found."""
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            mgr = SemanticMemoryManager()
            status = mgr.status()

        assert status["available"] is True
        assert status["bin"] == "/usr/bin/mempalace"

    def test_bin_caching(self) -> None:
        """Binary lookup is cached after first call."""
        with patch("shutil.which", return_value="/usr/bin/mempalace") as mock:
            mgr = SemanticMemoryManager()
            mgr.bin()
            mgr.bin()
            mgr.bin()
            # Should only call shutil.which once
            assert mock.call_count == 1

    def test_reset_bin_cache(self) -> None:
        """reset_bin_cache allows re-detection."""
        with patch("shutil.which", return_value=None) as mock:
            mgr = SemanticMemoryManager()
            assert mgr.bin() is None

        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            mgr.reset_bin_cache()
            assert mgr.bin() == "/usr/bin/mempalace"

    def test_embedding_model_enum(self) -> None:
        """EmbeddingModel enum has correct values."""
        assert EmbeddingModel.MINILM == "minilm"
        assert EmbeddingModel.EMBEDDINGGEMMA == "embeddinggemma"

    def test_custom_model(self) -> None:
        """Can initialize with different embedding model."""
        with patch("shutil.which", return_value=None):
            mgr = SemanticMemoryManager(model=EmbeddingModel.EMBEDDINGGEMMA)
            assert mgr.status()["model"] == "embeddinggemma"


class TestMineAgent:
    """Tests for SemanticMemoryManager.mine_agent()."""

    def test_mine_when_unavailable(self) -> None:
        """Return no-op result when mempalace not available."""
        with patch("shutil.which", return_value=None):
            mgr = SemanticMemoryManager()
            result = mgr.mine_agent("/agents/test", "test-agent")

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "unavailable"

    def test_mine_no_memory_file(self, tmp_path: Path) -> None:
        """Return skipped result when no memory.md exists."""
        agent_dir = tmp_path / "agent1"
        agent_dir.mkdir()

        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            mgr = SemanticMemoryManager()
            result = mgr.mine_agent(str(agent_dir), "agent1")

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "no_memory_file"

    def test_mine_success(self, tmp_path: Path) -> None:
        """Successfully mine agent memory."""
        agent_dir = tmp_path / "agent1"
        agent_dir.mkdir()
        (agent_dir / "memory.md").write_text("# Memory\nSome facts")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                result = mgr.mine_agent(str(agent_dir), "agent1")

        assert result["ok"] is True
        assert result["skipped"] is False
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/mempalace"
        assert cmd[1] == "mine"
        assert "--wing" in cmd
        assert "--agent" in cmd

    def test_mine_failure(self, tmp_path: Path) -> None:
        """Return error result when mine subprocess fails."""
        agent_dir = tmp_path / "agent1"
        agent_dir.mkdir()
        (agent_dir / "memory.md").write_text("# Memory")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="mining error"
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result):
                mgr = SemanticMemoryManager()
                result = mgr.mine_agent(str(agent_dir), "agent1")

        assert result["ok"] is False
        assert "mining error" in result["error"]

    def test_mtime_skip_unchanged(self, tmp_path: Path) -> None:
        """Skip re-mining when memory.md has not changed."""
        agent_dir = tmp_path / "agent1"
        agent_dir.mkdir()
        mem_file = agent_dir / "memory.md"
        mem_file.write_text("# Memory")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                # First mine should run
                result1 = mgr.mine_agent(str(agent_dir), "agent1")
                assert result1["skipped"] is False
                assert mock_run.call_count == 1

                # Second mine should skip (unchanged)
                result2 = mgr.mine_agent(str(agent_dir), "agent1")
                assert result2["ok"] is True
                assert result2["skipped"] is True
                assert result2["reason"] == "unchanged"
                assert mock_run.call_count == 1  # Not called again

    def test_mine_after_file_change(self, tmp_path: Path) -> None:
        """Re-mine when memory.md modification time changes."""
        agent_dir = tmp_path / "agent1"
        agent_dir.mkdir()
        mem_file = agent_dir / "memory.md"
        mem_file.write_text("# Memory v1")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                mgr.mine_agent(str(agent_dir), "agent1")
                assert mock_run.call_count == 1

                # Simulate file change by updating mtime
                os.utime(str(mem_file), (9999999999, 9999999999))

                result = mgr.mine_agent(str(agent_dir), "agent1")
                assert result["skipped"] is False
                assert mock_run.call_count == 2


class TestSearch:
    """Tests for SemanticMemoryManager.search()."""

    def test_search_unavailable(self) -> None:
        """Return degraded result when mempalace not available."""
        with patch("shutil.which", return_value=None):
            mgr = SemanticMemoryManager()
            result = mgr.search("test query")

        assert result["ok"] is True
        assert result["output"] == ""
        assert result["degraded"] is True

    def test_search_success(self) -> None:
        """Return search output on success."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result1\nresult2\n", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                result = mgr.search("test query", wing="agent1", results=3)

        assert result["ok"] is True
        assert "result1" in result["output"]
        cmd = mock_run.call_args[0][0]
        assert "search" in cmd
        assert "test query" in cmd
        assert "--results" in cmd
        assert "3" in cmd
        assert "--wing" in cmd
        assert "agent1" in cmd

    def test_search_failure(self) -> None:
        """Return error on search subprocess failure."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="search error"
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result):
                mgr = SemanticMemoryManager()
                result = mgr.search("query")

        assert result["ok"] is False
        assert "search error" in result["error"]

    def test_search_without_wing(self) -> None:
        """Search without wing parameter omits --wing flag."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                mgr.search("query")

        cmd = mock_run.call_args[0][0]
        assert "--wing" not in cmd


class TestMineAll:
    """Tests for SemanticMemoryManager.mine_all()."""

    def test_mine_all_agents(self, tmp_path: Path) -> None:
        """Mine all agent directories with memory.md files."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        for name in ("agent-a", "agent-b"):
            d = agents_dir / name
            d.mkdir()
            (d / "memory.md").write_text(f"# {name} memory")

        # Non-agent file (should be skipped)
        (agents_dir / "readme.txt").write_text("not an agent")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                mgr.mine_all(str(agents_dir))

        # Should mine both agents
        assert mock_run.call_count == 2

    def test_mine_all_serialization(self, tmp_path: Path) -> None:
        """Mining flag prevents concurrent mine_all calls."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        d = agents_dir / "agent-x"
        d.mkdir()
        (d / "memory.md").write_text("# memory")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                # Simulate being in mining state
                mgr._mining = True
                mgr.mine_all(str(agents_dir))
                # Should not mine anything because flag is set
                assert mock_run.call_count == 0

                # Reset flag and try again
                mgr._mining = False
                mgr.mine_all(str(agents_dir))
                assert mock_run.call_count == 1

    def test_mine_all_nonexistent_dir(self) -> None:
        """Handle non-existent agents directory gracefully."""
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            mgr = SemanticMemoryManager()
            # Should not raise
            mgr.mine_all("/nonexistent/agents")

    def test_mine_all_skips_unchanged(self, tmp_path: Path) -> None:
        """mine_all skips agents whose memory.md has not changed."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        d = agents_dir / "agent-y"
        d.mkdir()
        (d / "memory.md").write_text("# memory")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("shutil.which", return_value="/usr/bin/mempalace"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                mgr = SemanticMemoryManager()
                mgr.mine_all(str(agents_dir))
                assert mock_run.call_count == 1

                # Second call should skip (unchanged)
                mgr.mine_all(str(agents_dir))
                assert mock_run.call_count == 1
