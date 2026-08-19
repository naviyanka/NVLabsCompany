"""Tests for SemanticMemoryManager embedding fallback.

Verifies that when mempalace is unavailable, the manager falls back to
LocalEmbeddingProvider for mine and search operations using a JSON store.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.memory.semantic import SemanticMemoryManager


class TestMineAgentFallback:
    """Tests for mine_agent fallback when mempalace is unavailable."""

    @patch("shutil.which", return_value=None)
    def test_mine_writes_embeddings_to_json(self, _mock_which, tmp_path):
        """When mempalace unavailable, mine_agent computes and stores embeddings."""
        agent_dir = tmp_path / "agents" / "alpha"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text(
            "First paragraph about AI systems.\n\n"
            "Second paragraph about machine learning.",
            encoding="utf-8",
        )

        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        result = mgr.mine_agent(str(agent_dir), "alpha")

        assert result["ok"] is True
        assert result["skipped"] is False
        assert result["fallback"] is True
        assert embeddings_file.exists()

        data = json.loads(embeddings_file.read_text(encoding="utf-8"))
        assert "alpha:0" in data
        assert "alpha:1" in data
        assert data["alpha:0"]["agent_id"] == "alpha"
        assert data["alpha:0"]["text"] == "First paragraph about AI systems."
        assert isinstance(data["alpha:0"]["embedding"], list)
        assert len(data["alpha:0"]["embedding"]) > 0
        assert isinstance(data["alpha:0"]["timestamp"], float)

    @patch("shutil.which", return_value=None)
    def test_mine_no_memory_file(self, _mock_which, tmp_path):
        """Returns skipped when memory.md does not exist."""
        agent_dir = tmp_path / "agents" / "beta"
        agent_dir.mkdir(parents=True)

        mgr = SemanticMemoryManager(embeddings_path=str(tmp_path / "emb.json"))
        result = mgr.mine_agent(str(agent_dir), "beta")

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "no_memory_file"

    @patch("shutil.which", return_value=None)
    def test_mine_empty_memory_file(self, _mock_which, tmp_path):
        """Returns skipped for empty memory.md."""
        agent_dir = tmp_path / "agents" / "gamma"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("", encoding="utf-8")

        mgr = SemanticMemoryManager(embeddings_path=str(tmp_path / "emb.json"))
        result = mgr.mine_agent(str(agent_dir), "gamma")

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "empty_memory_file"

    @patch("shutil.which", return_value=None)
    def test_mine_no_embeddings_path(self, _mock_which, tmp_path):
        """Returns skipped with 'unavailable' reason if no embeddings path is configured."""
        agent_dir = tmp_path / "agents" / "delta"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Some content", encoding="utf-8")

        # Neither embeddings_path nor palace_path set
        mgr = SemanticMemoryManager()
        result = mgr.mine_agent(str(agent_dir), "delta")

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "unavailable"

    @patch("shutil.which", return_value=None)
    def test_mine_uses_palace_path_default(self, _mock_which, tmp_path):
        """When palace_path is set but embeddings_path is not, uses palace_path/embeddings.json."""
        palace_dir = tmp_path / "palace"
        palace_dir.mkdir()
        agent_dir = tmp_path / "agents" / "epsilon"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Content for testing.", encoding="utf-8")

        mgr = SemanticMemoryManager(palace_path=str(palace_dir))
        result = mgr.mine_agent(str(agent_dir), "epsilon")

        assert result["ok"] is True
        assert result["fallback"] is True
        assert (palace_dir / "embeddings.json").exists()

    @patch("shutil.which", return_value=None)
    def test_mine_removes_stale_entries(self, _mock_which, tmp_path):
        """Re-mining with fewer chunks removes stale entries."""
        agent_dir = tmp_path / "agents" / "zeta"
        agent_dir.mkdir(parents=True)
        memory_file = agent_dir / "memory.md"
        embeddings_file = tmp_path / "embeddings.json"

        # First mine with two chunks
        memory_file.write_text("Chunk one.\n\nChunk two.", encoding="utf-8")
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))
        mgr.mine_agent(str(agent_dir), "zeta")

        data = json.loads(embeddings_file.read_text(encoding="utf-8"))
        assert "zeta:0" in data
        assert "zeta:1" in data

        # Re-mine with only one chunk
        memory_file.write_text("Only one chunk now.", encoding="utf-8")
        mgr.mine_agent(str(agent_dir), "zeta")

        data = json.loads(embeddings_file.read_text(encoding="utf-8"))
        assert "zeta:0" in data
        assert "zeta:1" not in data


class TestSearchFallback:
    """Tests for search fallback when mempalace is unavailable."""

    @patch("shutil.which", return_value=None)
    def test_search_returns_results_from_cosine_similarity(self, _mock_which, tmp_path):
        """Fallback search returns relevant results via cosine similarity."""
        agent_dir = tmp_path / "agents" / "alpha"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text(
            "Python programming is great for AI.\n\n"
            "Cooking recipes for dinner tonight.\n\n"
            "Machine learning with Python and TensorFlow.",
            encoding="utf-8",
        )

        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        # Mine first
        mgr.mine_agent(str(agent_dir), "alpha")

        # Search for Python-related content
        result = mgr.search("Python programming AI")

        assert result["ok"] is True
        assert result["fallback"] is True
        assert "Python" in result["output"]

    @patch("shutil.which", return_value=None)
    def test_search_empty_embeddings(self, _mock_which, tmp_path):
        """Search with empty embeddings file returns empty output."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        result = mgr.search("test query")

        assert result["ok"] is True
        assert result["output"] == ""
        assert result["fallback"] is True

    @patch("shutil.which", return_value=None)
    def test_search_missing_embeddings_file(self, _mock_which, tmp_path):
        """Search with non-existent file returns empty output."""
        embeddings_file = tmp_path / "nonexistent" / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        result = mgr.search("test query")

        assert result["ok"] is True
        assert result["output"] == ""
        assert result["fallback"] is True

    @patch("shutil.which", return_value=None)
    def test_search_no_embeddings_path(self, _mock_which):
        """Search without embeddings path returns degraded result."""
        mgr = SemanticMemoryManager()
        result = mgr.search("test")

        assert result["ok"] is True
        assert result["output"] == ""
        assert result["degraded"] is True
        assert result["reason"] == "no_embeddings_path"

    @patch("shutil.which", return_value=None)
    def test_search_filters_by_wing(self, _mock_which, tmp_path):
        """Search with wing parameter filters results by agent_id."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        # Mine two agents
        agent1_dir = tmp_path / "agents" / "agent1"
        agent1_dir.mkdir(parents=True)
        (agent1_dir / "memory.md").write_text(
            "Python AI deep learning neural networks.", encoding="utf-8"
        )
        mgr.mine_agent(str(agent1_dir), "agent1")

        agent2_dir = tmp_path / "agents" / "agent2"
        agent2_dir.mkdir(parents=True)
        (agent2_dir / "memory.md").write_text(
            "Cooking Italian pasta carbonara.", encoding="utf-8"
        )
        mgr.mine_agent(str(agent2_dir), "agent2")

        # Search with wing filter for agent1
        result = mgr.search("Python AI", wing="agent1")
        assert result["ok"] is True
        assert result["fallback"] is True
        # Should contain agent1 content but not agent2 content
        assert "Python" in result["output"]
        assert "carbonara" not in result["output"]

        # Search with wing filter for agent2
        result = mgr.search("cooking", wing="agent2")
        assert result["ok"] is True
        assert "Cooking" in result["output"] or "carbonara" in result["output"]

    @patch("shutil.which", return_value=None)
    def test_search_respects_results_limit(self, _mock_which, tmp_path):
        """Search respects the results parameter to limit output."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        # Mine an agent with many chunks
        agent_dir = tmp_path / "agents" / "multi"
        agent_dir.mkdir(parents=True)
        content = "\n\n".join(f"Paragraph number {i} about testing." for i in range(10))
        (agent_dir / "memory.md").write_text(content, encoding="utf-8")
        mgr.mine_agent(str(agent_dir), "multi")

        # Search with limit of 2
        result = mgr.search("testing paragraph", results=2)
        assert result["ok"] is True
        # Output should contain at most 2 chunks separated by double-newline
        chunks = [c for c in result["output"].split("\n\n") if c.strip()]
        assert len(chunks) <= 2


class TestSearchWithEmbeddings:
    """Tests for search_with_embeddings always using in-process path."""

    @patch("shutil.which", return_value="/usr/bin/mempalace")
    def test_uses_inprocess_even_when_mempalace_available(self, _mock_which, tmp_path):
        """search_with_embeddings uses in-process path regardless of mempalace."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        # Manually create embeddings data (simulating prior mine)
        from nexus.knowledge.embeddings import LocalEmbeddingProvider

        provider = LocalEmbeddingProvider()
        text = "Python deep learning neural networks"
        embedding = provider._compute_embedding(text)

        data = {
            "test:0": {
                "text": text,
                "embedding": embedding,
                "agent_id": "test",
                "timestamp": 1000.0,
            }
        }
        embeddings_file.write_text(json.dumps(data), encoding="utf-8")

        # mempalace is "available" but search_with_embeddings should still work
        assert mgr.available() is True
        result = mgr.search_with_embeddings("Python learning")

        assert result["ok"] is True
        assert result["fallback"] is True
        assert "Python" in result["output"]

    @patch("shutil.which", return_value=None)
    def test_uses_inprocess_when_mempalace_unavailable(self, _mock_which, tmp_path):
        """search_with_embeddings works when mempalace is unavailable."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        # Mine content
        agent_dir = tmp_path / "agents" / "eta"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text(
            "Quantum computing qubits superposition.", encoding="utf-8"
        )
        mgr.mine_agent(str(agent_dir), "eta")

        result = mgr.search_with_embeddings("quantum computing")
        assert result["ok"] is True
        assert result["fallback"] is True
        assert "Quantum" in result["output"] or "quantum" in result["output"].lower()


class TestExistingBehaviorUnchanged:
    """Tests verifying existing behavior when mempalace IS available."""

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/mempalace")
    def test_mine_agent_uses_subprocess(self, _mock_which, mock_run, tmp_path):
        """When mempalace is available, mine_agent uses subprocess as before."""
        agent_dir = tmp_path / "agents" / "theta"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Some memory content.", encoding="utf-8")

        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "mined ok",
            "stderr": "",
        })()

        mgr = SemanticMemoryManager(palace_path=str(tmp_path / "palace"))
        result = mgr.mine_agent(str(agent_dir), "theta")

        assert result["ok"] is True
        assert result["skipped"] is False
        assert "fallback" not in result
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/mempalace"
        assert "mine" in call_args

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/mempalace")
    def test_search_uses_subprocess(self, _mock_which, mock_run, tmp_path):
        """When mempalace is available, search uses subprocess as before."""
        mock_run.return_value = type("Result", (), {
            "returncode": 0,
            "stdout": "found result 1\nfound result 2",
            "stderr": "",
        })()

        mgr = SemanticMemoryManager(palace_path=str(tmp_path / "palace"))
        result = mgr.search("test query", wing="alpha", results=3)

        assert result["ok"] is True
        assert result["output"] == "found result 1\nfound result 2"
        assert "fallback" not in result
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "--wing" in call_args
        assert "alpha" in call_args


class TestAtomicWrite:
    """Tests for the atomic write mechanism of embeddings."""

    @patch("shutil.which", return_value=None)
    def test_atomic_write_creates_file(self, _mock_which, tmp_path):
        """Atomic write creates the embeddings file correctly."""
        embeddings_file = tmp_path / "store" / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        agent_dir = tmp_path / "agents" / "iota"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Test content here.", encoding="utf-8")

        mgr.mine_agent(str(agent_dir), "iota")

        # File should exist and be valid JSON
        assert embeddings_file.exists()
        data = json.loads(embeddings_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "iota:0" in data

    @patch("shutil.which", return_value=None)
    def test_atomic_write_no_temp_files_left(self, _mock_which, tmp_path):
        """After successful write, no temp files should remain."""
        embeddings_file = tmp_path / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        agent_dir = tmp_path / "agents" / "kappa"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Temp test content.", encoding="utf-8")

        mgr.mine_agent(str(agent_dir), "kappa")

        # Check no temp files remain in directory
        files = list(tmp_path.iterdir())
        temp_files = [f for f in files if f.name.startswith(".embeddings_")]
        assert len(temp_files) == 0

    @patch("shutil.which", return_value=None)
    def test_save_embeddings_creates_parent_dirs(self, _mock_which, tmp_path):
        """Atomic write creates parent directories if needed."""
        embeddings_file = tmp_path / "deep" / "nested" / "dir" / "embeddings.json"
        mgr = SemanticMemoryManager(embeddings_path=str(embeddings_file))

        agent_dir = tmp_path / "agents" / "lambda"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.md").write_text("Nested dir test.", encoding="utf-8")

        result = mgr.mine_agent(str(agent_dir), "lambda")

        assert result["ok"] is True
        assert embeddings_file.exists()


class TestLoadEmbeddings:
    """Tests for loading embeddings gracefully."""

    @patch("shutil.which", return_value=None)
    def test_handles_missing_file(self, _mock_which, tmp_path):
        """Loading non-existent file returns empty dict."""
        mgr = SemanticMemoryManager(embeddings_path=str(tmp_path / "nope.json"))
        data = mgr._load_embeddings()
        assert data == {}

    @patch("shutil.which", return_value=None)
    def test_handles_invalid_json(self, _mock_which, tmp_path):
        """Loading invalid JSON returns empty dict."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")

        mgr = SemanticMemoryManager(embeddings_path=str(bad_file))
        data = mgr._load_embeddings()
        assert data == {}

    @patch("shutil.which", return_value=None)
    def test_handles_non_dict_json(self, _mock_which, tmp_path):
        """Loading JSON that is not a dict returns empty dict."""
        list_file = tmp_path / "list.json"
        list_file.write_text("[1, 2, 3]", encoding="utf-8")

        mgr = SemanticMemoryManager(embeddings_path=str(list_file))
        data = mgr._load_embeddings()
        assert data == {}

    @patch("shutil.which", return_value=None)
    def test_handles_valid_embeddings_file(self, _mock_which, tmp_path):
        """Loading valid embeddings returns the dict."""
        valid_file = tmp_path / "valid.json"
        expected = {
            "agent:0": {
                "text": "hello",
                "embedding": [0.1, 0.2],
                "agent_id": "agent",
                "timestamp": 1000.0,
            }
        }
        valid_file.write_text(json.dumps(expected), encoding="utf-8")

        mgr = SemanticMemoryManager(embeddings_path=str(valid_file))
        data = mgr._load_embeddings()
        assert data == expected


class TestChunkText:
    """Tests for the text chunking logic."""

    def test_splits_on_double_newline(self):
        """Text is split on double-newline boundaries."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird."
        chunks = SemanticMemoryManager._chunk_text(text)
        assert chunks == ["First paragraph.", "Second paragraph.", "Third."]

    def test_large_paragraph_split_by_size(self):
        """Paragraphs exceeding chunk_size are further split."""
        # Create a paragraph longer than the default chunk size
        large = "x" * 1200
        chunks = SemanticMemoryManager._chunk_text(large, chunk_size=500)
        assert len(chunks) == 3  # 500 + 500 + 200
        assert chunks[0] == "x" * 500
        assert chunks[1] == "x" * 500
        assert chunks[2] == "x" * 200

    def test_empty_text(self):
        """Empty text returns empty list."""
        chunks = SemanticMemoryManager._chunk_text("")
        assert chunks == []

    def test_whitespace_only_text(self):
        """Whitespace-only text returns empty list."""
        chunks = SemanticMemoryManager._chunk_text("   \n\n   \n\n   ")
        assert chunks == []


class TestGetEmbeddingsPath:
    """Tests for _get_embeddings_path resolution."""

    def test_explicit_embeddings_path(self):
        """Explicit embeddings_path is used directly."""
        mgr = SemanticMemoryManager(embeddings_path="/tmp/my_emb.json")
        assert mgr._get_embeddings_path() == Path("/tmp/my_emb.json")

    def test_palace_path_derived(self):
        """When only palace_path is set, derives embeddings path."""
        mgr = SemanticMemoryManager(palace_path="/data/palace")
        assert mgr._get_embeddings_path() == Path("/data/palace/embeddings.json")

    def test_no_paths_returns_none(self):
        """When neither path is set, returns None."""
        mgr = SemanticMemoryManager()
        assert mgr._get_embeddings_path() is None

    def test_embeddings_path_takes_precedence(self):
        """embeddings_path takes precedence over palace_path derivation."""
        mgr = SemanticMemoryManager(
            palace_path="/data/palace",
            embeddings_path="/custom/path.json",
        )
        assert mgr._get_embeddings_path() == Path("/custom/path.json")
