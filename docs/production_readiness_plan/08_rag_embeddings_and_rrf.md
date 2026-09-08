# Micro-Phase 6: Full-Scale Knowledge & RAG Modernization

## 1. Problem Statement
Vector similarity requires flexible embedding options (Voyage AI, OpenAI, FastEmbed) and robust hybrid retrieval combining lexical BM25 with dense semantic search without score calibration skew.

## 2. Technical Invariants
1. Pluggable embedding providers conforming to `EmbeddingProvider` protocol with dimension checks.
2. Reciprocal Rank Fusion (`RRFRanker`) algorithm fusing sparse BM25 and dense vector results:
   $$\text{RRF}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
3. Zero regressions to standard keyword retrieval.

## 3. Implementation Status
- `VoyageEmbeddingProvider` added in `src/nexus/knowledge/embeddings.py` (commit `d23b6cc`).
- `RRFRanker` added in `src/nexus/knowledge/rankers.py` and exported in `src/nexus/knowledge/__init__.py` (commit `dcc4ce9`).
- Unit test suite verified in `tests/test_rag_pipeline_enhanced.py`.
