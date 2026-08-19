"""Memory systems: 3-temperature store and 4-layer intelligent memory.

- 3-temperature: hot (in-memory), warm (PostgreSQL), cold (JSON archive).
- 4-layer: L0 (ephemeral), L1 (session), L2 (agent), L3 (shared).
"""

from nexus.memory.store import MemoryStore
from nexus.memory.retriever import tokenize, bm25_score, search
from nexus.memory.scoping import MemoryScopeManager
from nexus.memory.layered import (
    Fact,
    L1Summary,
    LayeredMemoryConfig,
    LayeredMemoryStore,
    MemoryLayer,
)
from nexus.memory.extract import ExtractionRule, FactExtractor
from nexus.memory.dedup import (
    jaccard_similarity,
    is_duplicate,
    find_duplicates,
)
from nexus.memory.promotion import PromotionCriteria, PromotionEngine
from nexus.memory.semantic import EmbeddingModel, SemanticMemoryManager

__all__ = [
    "MemoryStore",
    "tokenize",
    "bm25_score",
    "search",
    "MemoryScopeManager",
    "Fact",
    "L1Summary",
    "LayeredMemoryConfig",
    "LayeredMemoryStore",
    "MemoryLayer",
    "ExtractionRule",
    "FactExtractor",
    "jaccard_similarity",
    "is_duplicate",
    "find_duplicates",
    "PromotionCriteria",
    "PromotionEngine",
    "EmbeddingModel",
    "SemanticMemoryManager",
]
