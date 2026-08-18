"""Knowledge System module for NEXUS.

Provides organizational knowledge management, RAG-based retrieval,
and experience tracking capabilities for AI agents.

Components:
    - KnowledgePlaza: Collaborative knowledge base with versioned pages
    - RAGPipeline: Retrieval-Augmented Generation with chunking and hybrid search
    - ExperienceManager: Agent experience recording and pattern extraction
"""

from nexus.knowledge.experience import ExperienceManager
from nexus.knowledge.plaza import KnowledgePlaza
from nexus.knowledge.rag import RAGPipeline

__all__ = ["KnowledgePlaza", "RAGPipeline", "ExperienceManager"]
