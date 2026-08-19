"""Semantic memory manager: embedding-based retrieval via mempalace CLI.

Wraps the mempalace binary for mining agent memory files into vector
embeddings and performing semantic search. Degrades silently to no-op
when the mempalace binary is not available on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from enum import Enum

_NOT_CHECKED = object()  # Sentinel for "bin not yet checked"


class EmbeddingModel(str, Enum):
    """Supported embedding models for semantic memory.

    Attributes:
        MINILM: MiniLM model (lightweight, fast).
        EMBEDDINGGEMMA: Embedding Gemma model (higher quality).
    """

    MINILM = "minilm"
    EMBEDDINGGEMMA = "embeddinggemma"


class SemanticMemoryManager:
    """Manager for embedding-based semantic memory using mempalace CLI.

    Provides mine and search operations over agent memory files. All
    operations degrade gracefully to no-op results when the mempalace
    binary is not available on PATH.

    The manager tracks memory.md file modification times to avoid
    re-mining unchanged files. Concurrent mining is serialized via
    a simple flag.

    Attributes:
        palace_path: Optional path to the memory palace data directory.
        model: Embedding model to use for vectorization.
    """

    def __init__(
        self,
        palace_path: str | None = None,
        model: EmbeddingModel = EmbeddingModel.MINILM,
    ) -> None:
        """Initialize the semantic memory manager.

        Args:
            palace_path: Optional path to the memory palace data directory.
                If None, mempalace uses its default location.
            model: Embedding model to use. Defaults to MiniLM.
        """
        self.palace_path = palace_path
        self.model = model
        self._bin_cache: str | None | object = _NOT_CHECKED
        self._last_mined: dict[str, float] = {}
        self._mining: bool = False

    def bin(self) -> str | None:
        """Locate the mempalace binary on PATH.

        Caches the result after first lookup. Returns None if the binary
        is not found.

        Returns:
            Absolute path to the mempalace binary, or None if not found.
        """
        if self._bin_cache is _NOT_CHECKED:
            self._bin_cache = shutil.which("mempalace")
        return self._bin_cache  # type: ignore[return-value]

    def reset_bin_cache(self) -> None:
        """Clear the cached binary path for re-detection."""
        self._bin_cache = _NOT_CHECKED

    def available(self) -> bool:
        """Check if the mempalace binary is available.

        Returns:
            True if mempalace is found on PATH, False otherwise.
        """
        return self.bin() is not None

    def status(self) -> dict:
        """Report the current status of the semantic memory system.

        Returns:
            Dictionary with keys: available (bool), palace_path (str or None),
            model (str), bin (str or None).
        """
        return {
            "available": self.available(),
            "palace_path": self.palace_path,
            "model": self.model.value,
            "bin": self.bin(),
        }

    def mine_agent(self, agent_dir: str, agent_id: str) -> dict:
        """Index an agent's memory.md into the semantic memory store.

        Checks the modification time of memory.md to skip re-mining
        unchanged files. Runs the mempalace mine subprocess.

        Args:
            agent_dir: Path to the agent's directory containing memory.md.
            agent_id: Unique identifier for the agent.

        Returns:
            Dictionary with 'ok' (bool) and optional 'error' (str) keys.
        """
        if not self.available():
            return {"ok": True, "skipped": True, "reason": "unavailable"}

        memory_file = os.path.join(agent_dir, "memory.md")
        try:
            mtime = os.path.getmtime(memory_file)
        except OSError:
            return {"ok": True, "skipped": True, "reason": "no_memory_file"}

        # Skip if unchanged
        last = self._last_mined.get(agent_id)
        if last is not None and last >= mtime:
            return {"ok": True, "skipped": True, "reason": "unchanged"}

        # Run mine subprocess
        bin_path = self.bin()
        cmd = [
            bin_path,  # type: ignore[list-item]
            "mine",
            agent_dir,
            "--wing",
            agent_id,
            "--agent",
            agent_id,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr or "mine failed"}
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"ok": False, "error": str(exc)}

        # Update last mined timestamp
        self._last_mined[agent_id] = mtime
        return {"ok": True, "skipped": False}

    def search(
        self,
        query: str,
        wing: str | None = None,
        results: int = 5,
    ) -> dict:
        """Perform semantic search over the memory palace.

        If the mempalace binary is not available, returns a degraded
        result indicating unavailability.

        Args:
            query: Search query string.
            wing: Optional wing (agent namespace) to constrain search.
            results: Maximum number of results to return.

        Returns:
            Dictionary with 'ok' (bool), 'output' (str), and optional
            'error' (str) keys.
        """
        if not self.available():
            return {
                "ok": True,
                "output": "",
                "degraded": True,
                "reason": "unavailable",
            }

        bin_path = self.bin()
        cmd = [
            bin_path,  # type: ignore[list-item]
            "search",
            query,
            "--results",
            str(results),
        ]
        if wing:
            cmd.extend(["--wing", wing])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "output": "",
                    "error": result.stderr or "search failed",
                }
            return {"ok": True, "output": result.stdout}
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    def mine_all(self, agents_dir: str) -> None:
        """Mine all agents in a directory whose memory.md has changed.

        Serializes mining: if already mining, returns immediately.
        Iterates agent subdirectories and mines each that has an updated
        memory.md file.

        Args:
            agents_dir: Path to the directory containing agent subdirectories.
        """
        if self._mining:
            return

        self._mining = True
        try:
            if not os.path.isdir(agents_dir):
                return
            for entry in sorted(os.listdir(agents_dir)):
                agent_path = os.path.join(agents_dir, entry)
                if not os.path.isdir(agent_path):
                    continue
                memory_file = os.path.join(agent_path, "memory.md")
                if not os.path.isfile(memory_file):
                    continue
                try:
                    mtime = os.path.getmtime(memory_file)
                except OSError:
                    continue
                last = self._last_mined.get(entry)
                if last is not None and last >= mtime:
                    continue
                self.mine_agent(agent_path, entry)
        finally:
            self._mining = False


__all__ = [
    "EmbeddingModel",
    "SemanticMemoryManager",
]
