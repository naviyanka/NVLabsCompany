"""Semantic memory manager: embedding-based retrieval via mempalace CLI.

Wraps the mempalace binary for mining agent memory files into vector
embeddings and performing semantic search. When the mempalace binary is
not available on PATH, falls back to an in-process embedding provider
(LocalEmbeddingProvider) with cosine similarity search over a JSON store.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from enum import Enum
from pathlib import Path

from nexus.knowledge.embeddings import LocalEmbeddingProvider, cosine_similarity

_NOT_CHECKED = object()  # Sentinel for "bin not yet checked"

# Default chunk size for splitting memory content
_CHUNK_SIZE = 500


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

    Provides mine and search operations over agent memory files. When the
    mempalace binary is not available on PATH, uses LocalEmbeddingProvider
    as an in-process fallback with a JSON-backed embeddings store.

    The manager tracks memory.md file modification times to avoid
    re-mining unchanged files. Concurrent mining is serialized via
    a simple flag.

    Attributes:
        palace_path: Optional path to the memory palace data directory.
        model: Embedding model to use for vectorization.
        embeddings_path: Optional path to the JSON embeddings store file.
    """

    def __init__(
        self,
        palace_path: str | None = None,
        model: EmbeddingModel = EmbeddingModel.MINILM,
        embeddings_path: str | None = None,
    ) -> None:
        """Initialize the semantic memory manager.

        Args:
            palace_path: Optional path to the memory palace data directory.
                If None, mempalace uses its default location.
            model: Embedding model to use. Defaults to MiniLM.
            embeddings_path: Optional path for the JSON embeddings store.
                If None and palace_path is set, defaults to
                '<palace_path>/embeddings.json'. If both are None, the
                fallback embedding features are disabled.
        """
        self.palace_path = palace_path
        self.model = model
        self.embeddings_path = embeddings_path
        self._bin_cache: str | None | object = _NOT_CHECKED
        self._last_mined: dict[str, float] = {}
        self._mining: bool = False
        self._embedding_provider = LocalEmbeddingProvider()

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

    def _get_embeddings_path(self) -> Path | None:
        """Resolve the path to the JSON embeddings file.

        Uses embeddings_path if explicitly set. Otherwise derives from
        palace_path. Returns None if neither is configured.

        Returns:
            Path to the embeddings JSON file, or None if not resolvable.
        """
        if self.embeddings_path is not None:
            return Path(self.embeddings_path)
        if self.palace_path is not None:
            return Path(self.palace_path) / "embeddings.json"
        return None

    def _load_embeddings(self) -> dict[str, dict]:
        """Load stored embeddings from the JSON file.

        Returns an empty dict if the file does not exist or is invalid.

        Returns:
            Dictionary mapping keys to embedding records. Each record
            contains: text (str), embedding (list[float]), agent_id (str),
            timestamp (float).
        """
        path = self._get_embeddings_path()
        if path is None or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_embeddings(self, data: dict) -> None:
        """Atomically write embeddings data to the JSON file.

        Writes to a temporary file in the same directory then renames
        to ensure atomicity and prevent partial writes.

        Args:
            data: The embeddings dictionary to persist.
        """
        path = self._get_embeddings_path()
        if path is None:
            return

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file + rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".embeddings_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.rename(tmp_path, str(path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE) -> list[str]:
        """Split text into chunks by double-newline or fixed size.

        First attempts to split on double-newline boundaries. Chunks
        that exceed chunk_size are further split at the size boundary.
        Empty chunks are discarded.

        Args:
            text: The text content to split.
            chunk_size: Maximum characters per chunk.

        Returns:
            List of non-empty text chunks.
        """
        # First split by double-newline
        paragraphs = text.split("\n\n")
        chunks: list[str] = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # If paragraph fits in one chunk, add it directly
            if len(para) <= chunk_size:
                chunks.append(para)
            else:
                # Split large paragraphs by fixed size
                for i in range(0, len(para), chunk_size):
                    segment = para[i:i + chunk_size].strip()
                    if segment:
                        chunks.append(segment)

        return chunks

    def mine_agent(self, agent_dir: str, agent_id: str) -> dict:
        """Index an agent's memory.md into the semantic memory store.

        Checks the modification time of memory.md to skip re-mining
        unchanged files. When mempalace is available, runs the subprocess.
        When unavailable, falls back to in-process embedding computation
        and stores results in the JSON embeddings file.

        Args:
            agent_dir: Path to the agent's directory containing memory.md.
            agent_id: Unique identifier for the agent.

        Returns:
            Dictionary with 'ok' (bool) and optional 'error' (str) keys.
        """
        if not self.available():
            return self._mine_agent_fallback(agent_dir, agent_id)

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

    def _mine_agent_fallback(self, agent_dir: str, agent_id: str) -> dict:
        """Fallback mine using LocalEmbeddingProvider when mempalace is unavailable.

        Reads the agent's memory.md, splits into chunks, computes embeddings,
        and stores them in the JSON embeddings file. If no embeddings path is
        configured, returns the original unavailable response for backward
        compatibility.

        Args:
            agent_dir: Path to the agent's directory containing memory.md.
            agent_id: Unique identifier for the agent.

        Returns:
            Dictionary with mining results including fallback indicator.
        """
        # Check if embeddings path is configured first
        if self._get_embeddings_path() is None:
            return {"ok": True, "skipped": True, "reason": "unavailable"}

        memory_file = os.path.join(agent_dir, "memory.md")
        try:
            content = Path(memory_file).read_text(encoding="utf-8")
        except OSError:
            return {"ok": True, "skipped": True, "reason": "no_memory_file"}

        if not content.strip():
            return {"ok": True, "skipped": True, "reason": "empty_memory_file"}

        chunks = self._chunk_text(content)
        if not chunks:
            return {"ok": True, "skipped": True, "reason": "no_chunks"}

        # Load existing embeddings and update with new ones
        embeddings = self._load_embeddings()
        now = time.time()

        for idx, chunk in enumerate(chunks):
            key = f"{agent_id}:{idx}"
            # Using _compute_embedding directly because it is a deterministic pure
            # function with no I/O, and the public embed() method is async. Making
            # the mine/search paths async would break the existing synchronous API
            # contract used by background workers.
            embedding = self._embedding_provider._compute_embedding(chunk)
            embeddings[key] = {
                "text": chunk,
                "embedding": embedding,
                "agent_id": agent_id,
                "timestamp": now,
            }

        # Remove stale entries for this agent beyond current chunk count
        stale_keys = [
            k for k in embeddings
            if k.startswith(f"{agent_id}:") and k not in {
                f"{agent_id}:{i}" for i in range(len(chunks))
            }
        ]
        for k in stale_keys:
            del embeddings[k]

        self._save_embeddings(embeddings)
        return {"ok": True, "skipped": False, "fallback": True}

    def search(
        self,
        query: str,
        wing: str | None = None,
        results: int = 5,
    ) -> dict:
        """Perform semantic search over the memory palace.

        When the mempalace binary is available, delegates to the CLI.
        When unavailable, falls back to in-process cosine similarity
        search over the JSON embeddings store.

        Args:
            query: Search query string.
            wing: Optional wing (agent namespace) to constrain search.
            results: Maximum number of results to return.

        Returns:
            Dictionary with 'ok' (bool), 'output' (str), and optional
            'error' (str) keys.
        """
        if not self.available():
            return self._search_fallback(query, wing=wing, results=results)

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

    def _search_fallback(
        self,
        query: str,
        wing: str | None = None,
        results: int = 5,
    ) -> dict:
        """Fallback search using cosine similarity over stored embeddings.

        Computes a query embedding and ranks all stored embeddings by
        cosine similarity. Optionally filters by wing (agent_id).

        Args:
            query: Search query string.
            wing: Optional agent_id to filter results.
            results: Maximum number of results to return.

        Returns:
            Dictionary with search results and fallback indicator.
        """
        if self._get_embeddings_path() is None:
            return {
                "ok": True,
                "output": "",
                "degraded": True,
                "reason": "no_embeddings_path",
            }

        embeddings = self._load_embeddings()
        if not embeddings:
            return {"ok": True, "output": "", "fallback": True}

        # Compute query embedding
        # Using _compute_embedding directly because it is a deterministic pure
        # function with no I/O, and the public embed() method is async. Making
        # the mine/search paths async would break the existing synchronous API
        # contract used by background workers.
        query_embedding = self._embedding_provider._compute_embedding(query)

        # Score all entries
        scored: list[tuple[float, str]] = []
        for key, entry in embeddings.items():
            # Filter by wing (agent_id) if specified
            if wing and entry.get("agent_id") != wing:
                continue
            entry_embedding = entry.get("embedding", [])
            if not entry_embedding:
                continue
            score = cosine_similarity(query_embedding, entry_embedding)
            scored.append((score, entry.get("text", "")))

        # Sort by score descending and take top results
        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:results]

        output = "\n\n".join(text for _, text in top_results if text)
        return {"ok": True, "output": output, "fallback": True}

    def search_with_embeddings(
        self,
        query: str,
        wing: str | None = None,
        results: int = 5,
    ) -> dict:
        """Search using in-process embedding provider regardless of mempalace availability.

        Always uses LocalEmbeddingProvider and cosine similarity over the
        JSON embeddings store, bypassing the mempalace binary entirely.

        Args:
            query: Search query string.
            wing: Optional agent_id to filter results.
            results: Maximum number of results to return.

        Returns:
            Dictionary with 'ok' (bool), 'output' (str), and 'fallback' (bool) keys.
        """
        return self._search_fallback(query, wing=wing, results=results)

    def mine_all(self, agents_dir: str) -> None:
        """Mine all agents in a directory whose memory.md has changed.

        Serializes mining: if already mining, returns immediately.
        Iterates agent subdirectories and mines each that has an updated
        memory.md file.

        Note: The ``_mining`` flag provides re-entry protection for
        single-threaded synchronous callers only. It is not safe for
        concurrent async or multi-threaded use. This is acceptable because
        mine_agent uses subprocess.run (blocking) and was designed for
        synchronous background workers.

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
