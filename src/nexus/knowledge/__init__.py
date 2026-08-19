"""Knowledge System module for NEXUS.

Provides organizational knowledge management, RAG-based retrieval,
and experience tracking capabilities for AI agents.

Components:
    - KnowledgePlaza: Collaborative knowledge base with versioned pages
    - RAGPipeline: Retrieval-Augmented Generation with chunking and hybrid search
    - ExperienceManager: Agent experience recording and pattern extraction
    - Rankers: BM25Ranker, CrossEncoderRanker, RerankerPipeline
    - Retrievers: DenseRetriever, SparseRetriever, HybridRetriever
    - Parsers: TextParser, MarkdownParser, CodeParser, ParsedChunk
    - Protocols: Ranker, Retriever, DocumentParser
"""

from nexus.knowledge.experience import ExperienceManager
from nexus.knowledge.parsers import (
    CodeParser,
    DocumentParser,
    MarkdownParser,
    ParsedChunk,
    TextParser,
)
from nexus.knowledge.plaza import KnowledgePlaza
from nexus.knowledge.rag import RAGPipeline
from nexus.knowledge.rankers import (
    BM25Ranker,
    CrossEncoderRanker,
    Ranker,
    RerankerPipeline,
)
from nexus.knowledge.retrievers import (
    DenseRetriever,
    HybridRetriever,
    Retriever,
    SparseRetriever,
)

__all__ = [
    "KnowledgePlaza",
    "RAGPipeline",
    "ExperienceManager",
    "BM25Ranker",
    "CrossEncoderRanker",
    "RerankerPipeline",
    "Ranker",
    "DenseRetriever",
    "SparseRetriever",
    "HybridRetriever",
    "Retriever",
    "TextParser",
    "MarkdownParser",
    "CodeParser",
    "ParsedChunk",
    "DocumentParser",
]
