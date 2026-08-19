"""Tests for the 4-Layer Memory System (L0-L3).

Covers: L1 ring buffer eviction, L2 fact storage with dedup, L3 promotion
from L2, get_context_window combining layers, fact extraction from text
patterns, Jaccard similarity calculation, duplicate detection, promotion
criteria evaluation, and cross-agent fact promotion.
"""

import uuid
from datetime import datetime, timezone

import pytest

from nexus.memory.dedup import (
    find_duplicates,
    is_duplicate,
    jaccard_similarity,
    tokenize,
)
from nexus.memory.extract import ExtractionRule, FactExtractor
from nexus.memory.layered import (
    Fact,
    L1Summary,
    LayeredMemoryConfig,
    LayeredMemoryStore,
    MemoryLayer,
)
from nexus.memory.promotion import PromotionCriteria, PromotionEngine


# --- Fixtures ---


@pytest.fixture
def agent_id_1() -> uuid.UUID:
    """First test agent UUID."""
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def agent_id_2() -> uuid.UUID:
    """Second test agent UUID."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def agent_id_3() -> uuid.UUID:
    """Third test agent UUID."""
    return uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def task_id() -> uuid.UUID:
    """Test task UUID."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def store() -> LayeredMemoryStore:
    """Create a LayeredMemoryStore with default config."""
    return LayeredMemoryStore()


@pytest.fixture
def small_store() -> LayeredMemoryStore:
    """Create a LayeredMemoryStore with small ring buffer for eviction tests."""
    config = LayeredMemoryConfig(l1_ring_size=3, l2_max_facts=5)
    return LayeredMemoryStore(config=config)


@pytest.fixture
def extractor() -> FactExtractor:
    """Create a FactExtractor with default rules."""
    return FactExtractor()


@pytest.fixture
def promotion_engine() -> PromotionEngine:
    """Create a PromotionEngine instance."""
    return PromotionEngine()


# --- MemoryLayer Enum Tests ---


class TestMemoryLayer:
    """Tests for the MemoryLayer enum."""

    def test_enum_values(self) -> None:
        """All four layers are defined with expected values."""
        assert MemoryLayer.L0_EPHEMERAL.value == "l0_ephemeral"
        assert MemoryLayer.L1_SESSION.value == "l1_session"
        assert MemoryLayer.L2_AGENT.value == "l2_agent"
        assert MemoryLayer.L3_SHARED.value == "l3_shared"

    def test_enum_count(self) -> None:
        """Exactly four layers exist."""
        assert len(MemoryLayer) == 4


# --- LayeredMemoryConfig Tests ---


class TestLayeredMemoryConfig:
    """Tests for LayeredMemoryConfig defaults."""

    def test_defaults(self) -> None:
        """Config has expected default values."""
        config = LayeredMemoryConfig()
        assert config.l1_ring_size == 50
        assert config.l2_max_facts == 500
        assert config.l3_promotion_threshold == 3
        assert config.dedup_similarity == 0.8

    def test_custom_values(self) -> None:
        """Config accepts custom values."""
        config = LayeredMemoryConfig(
            l1_ring_size=10,
            l2_max_facts=100,
            l3_promotion_threshold=5,
            dedup_similarity=0.9,
        )
        assert config.l1_ring_size == 10
        assert config.l2_max_facts == 100
        assert config.l3_promotion_threshold == 5
        assert config.dedup_similarity == 0.9


# --- L1 Ring Buffer Tests ---


class TestL1RingBuffer:
    """Tests for L1 session summary ring buffer."""

    def test_add_summary(self, store: LayeredMemoryStore, task_id: uuid.UUID) -> None:
        """Session summary is added to L1."""
        store.add_session_summary(task_id, "Completed task X")
        assert len(store.l1_summaries) == 1
        assert store.l1_summaries[0].summary == "Completed task X"
        assert store.l1_summaries[0].task_id == task_id

    def test_ring_buffer_eviction(
        self, small_store: LayeredMemoryStore, task_id: uuid.UUID
    ) -> None:
        """Oldest summary is evicted when ring buffer is full."""
        # Ring size is 3
        small_store.add_session_summary(task_id, "Summary 1")
        small_store.add_session_summary(task_id, "Summary 2")
        small_store.add_session_summary(task_id, "Summary 3")
        assert len(small_store.l1_summaries) == 3

        # Adding a 4th should evict the first
        small_store.add_session_summary(task_id, "Summary 4")
        assert len(small_store.l1_summaries) == 3
        summaries = [s.summary for s in small_store.l1_summaries]
        assert "Summary 1" not in summaries
        assert "Summary 4" in summaries

    def test_ring_buffer_order(
        self, small_store: LayeredMemoryStore, task_id: uuid.UUID
    ) -> None:
        """Summaries are maintained in insertion order."""
        small_store.add_session_summary(task_id, "First")
        small_store.add_session_summary(task_id, "Second")
        small_store.add_session_summary(task_id, "Third")
        summaries = [s.summary for s in small_store.l1_summaries]
        assert summaries == ["First", "Second", "Third"]

    def test_summary_has_timestamp(
        self, store: LayeredMemoryStore, task_id: uuid.UUID
    ) -> None:
        """Session summaries have a created_at timestamp."""
        store.add_session_summary(task_id, "Test summary")
        assert store.l1_summaries[0].created_at is not None
        assert isinstance(store.l1_summaries[0].created_at, datetime)


# --- L2 Fact Storage Tests ---


class TestL2FactStorage:
    """Tests for L2 per-agent fact storage with deduplication."""

    def test_store_fact(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Facts are stored in L2 for the correct agent."""
        result = store.store_fact(agent_id_1, "Python uses GIL for thread safety")
        assert result is True
        facts = store.get_agent_facts(agent_id_1)
        assert len(facts) == 1
        assert facts[0].content == "Python uses GIL for thread safety"

    def test_store_fact_with_metadata(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Facts can include metadata."""
        meta = {"source": "documentation", "confidence": 0.95}
        store.store_fact(agent_id_1, "FastAPI uses Starlette", metadata=meta)
        facts = store.get_agent_facts(agent_id_1)
        assert facts[0].metadata == meta

    def test_dedup_blocks_similar_facts(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Duplicate facts are rejected based on Jaccard similarity."""
        store.store_fact(agent_id_1, "database connection pool size maximum")
        # Near-duplicate: subset + one extra token -> similarity 0.83
        result = store.store_fact(
            agent_id_1, "database connection pool size maximum configuration"
        )
        assert result is False
        assert len(store.get_agent_facts(agent_id_1)) == 1

    def test_different_facts_stored(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Distinct facts are stored independently."""
        store.store_fact(agent_id_1, "Python is dynamically typed")
        store.store_fact(agent_id_1, "Rust has zero-cost abstractions")
        assert len(store.get_agent_facts(agent_id_1)) == 2

    def test_facts_per_agent_isolation(
        self,
        store: LayeredMemoryStore,
        agent_id_1: uuid.UUID,
        agent_id_2: uuid.UUID,
    ) -> None:
        """Each agent's facts are isolated."""
        store.store_fact(agent_id_1, "Agent 1 knows this")
        store.store_fact(agent_id_2, "Agent 2 knows that")
        assert len(store.get_agent_facts(agent_id_1)) == 1
        assert len(store.get_agent_facts(agent_id_2)) == 1
        assert store.get_agent_facts(agent_id_1)[0].content == "Agent 1 knows this"

    def test_l2_max_facts_eviction(
        self, small_store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Oldest fact is evicted when L2 max is reached."""
        # Max is 5 for small_store, use very distinct facts to avoid dedup
        distinct_facts = [
            "Python programming language features overview",
            "Kubernetes container orchestration platform details",
            "PostgreSQL relational database system internals",
            "React frontend framework component lifecycle",
            "Terraform infrastructure code deployment tools",
            "GraphQL query language specification details",
        ]
        for fact in distinct_facts:
            small_store.store_fact(agent_id_1, fact)
        facts = small_store.get_agent_facts(agent_id_1, limit=10)
        assert len(facts) == 5
        # Oldest (first) should be evicted
        contents = [f.content for f in facts]
        assert distinct_facts[0] not in contents
        assert distinct_facts[5] in contents

    def test_get_agent_facts_respects_limit(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """get_agent_facts respects the limit parameter."""
        distinct_facts = [
            "Python dynamic typing features",
            "Kubernetes pod scheduling algorithms",
            "PostgreSQL query optimization techniques",
            "React component lifecycle methods",
            "Terraform state management practices",
            "GraphQL schema design principles",
            "Docker container networking modes",
            "Redis caching eviction policies",
            "MongoDB document indexing strategies",
            "Nginx reverse proxy configuration",
        ]
        for fact in distinct_facts:
            store.store_fact(agent_id_1, fact)
        facts = store.get_agent_facts(agent_id_1, limit=3)
        assert len(facts) == 3

    def test_get_agent_facts_increments_access_count(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Accessing facts increments their access_count."""
        store.store_fact(agent_id_1, "Important knowledge to track")
        store.get_agent_facts(agent_id_1)
        store.get_agent_facts(agent_id_1)
        # Access the underlying store directly to check count
        raw_facts = store.l2_facts[agent_id_1]
        assert raw_facts[0].access_count == 2


# --- L3 Promotion Tests ---


class TestL3Promotion:
    """Tests for promoting facts from L2 to L3."""

    def test_promote_existing_fact(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """A fact in L2 can be promoted to L3."""
        store.store_fact(agent_id_1, "Shared knowledge for everyone")
        result = store.promote_to_shared(agent_id_1, "Shared knowledge for everyone")
        assert result is True
        shared = store.get_shared_knowledge()
        assert len(shared) == 1
        assert shared[0].content == "Shared knowledge for everyone"

    def test_promote_nonexistent_fact_fails(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Promoting a fact that doesn't exist returns False."""
        result = store.promote_to_shared(agent_id_1, "This fact does not exist")
        assert result is False

    def test_promote_preserves_l2(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Promoted fact remains in L2 (copied, not moved)."""
        store.store_fact(agent_id_1, "Keep in both layers")
        store.promote_to_shared(agent_id_1, "Keep in both layers")
        # Should be in both L2 and L3
        assert len(store.get_agent_facts(agent_id_1)) == 1
        assert len(store.get_shared_knowledge()) == 1

    def test_get_shared_knowledge_limit(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """get_shared_knowledge respects the limit parameter."""
        distinct_facts = [
            "Company policy requires code reviews",
            "Production deployments happen on Tuesdays",
            "Database backups run every midnight",
            "API versioning uses semantic format",
            "Incident response follows PagerDuty protocol",
        ]
        for fact in distinct_facts:
            store.store_fact(agent_id_1, fact)
            store.promote_to_shared(agent_id_1, fact)
        shared = store.get_shared_knowledge(limit=2)
        assert len(shared) == 2


# --- Context Window Tests ---


class TestContextWindow:
    """Tests for get_context_window combining L1 + L2 + L3."""

    def test_combines_all_layers(
        self,
        store: LayeredMemoryStore,
        agent_id_1: uuid.UUID,
        task_id: uuid.UUID,
    ) -> None:
        """Context window includes items from L1, L2, and L3."""
        store.add_session_summary(task_id, "Did task A")
        store.store_fact(agent_id_1, "Agent specific knowledge about systems")
        store.store_fact(agent_id_1, "Shared org knowledge about policies")
        store.promote_to_shared(agent_id_1, "Shared org knowledge about policies")

        context = store.get_context_window(agent_id_1, limit=20)
        assert any("[session]" in c for c in context)
        assert any("[agent]" in c for c in context)
        assert any("[shared]" in c for c in context)

    def test_context_window_respects_limit(
        self,
        store: LayeredMemoryStore,
        agent_id_1: uuid.UUID,
        task_id: uuid.UUID,
    ) -> None:
        """Context window does not exceed the specified limit."""
        for i in range(10):
            store.add_session_summary(task_id, f"Session summary {i}")
            store.store_fact(agent_id_1, f"Agent fact {i} with unique content {i * 7}")

        context = store.get_context_window(agent_id_1, limit=5)
        assert len(context) <= 5

    def test_context_window_empty_store(
        self, store: LayeredMemoryStore, agent_id_1: uuid.UUID
    ) -> None:
        """Context window returns empty list for empty store."""
        context = store.get_context_window(agent_id_1)
        assert context == []

    def test_context_window_prefixes(
        self,
        store: LayeredMemoryStore,
        agent_id_1: uuid.UUID,
        task_id: uuid.UUID,
    ) -> None:
        """Context items are prefixed with their layer source."""
        store.add_session_summary(task_id, "Session info")
        store.store_fact(agent_id_1, "Agent fact about deployment processes")
        store.store_fact(agent_id_1, "Organizational shared policy knowledge")
        store.promote_to_shared(agent_id_1, "Organizational shared policy knowledge")

        context = store.get_context_window(agent_id_1, limit=20)
        session_items = [c for c in context if c.startswith("[session]")]
        agent_items = [c for c in context if c.startswith("[agent]")]
        shared_items = [c for c in context if c.startswith("[shared]")]
        assert len(session_items) >= 1
        assert len(agent_items) >= 1
        assert len(shared_items) >= 1


# --- Jaccard Similarity Tests ---


class TestJaccardSimilarity:
    """Tests for Jaccard similarity calculation."""

    def test_identical_sets(self) -> None:
        """Identical sets have similarity 1.0."""
        s = {"hello", "world"}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets(self) -> None:
        """Completely different sets have similarity 0.0."""
        a = {"hello", "world"}
        b = {"foo", "bar"}
        assert jaccard_similarity(a, b) == 0.0

    def test_partial_overlap(self) -> None:
        """Partial overlap gives expected similarity."""
        a = {"hello", "world", "foo"}
        b = {"hello", "world", "bar"}
        # Intersection: {hello, world} = 2
        # Union: {hello, world, foo, bar} = 4
        assert jaccard_similarity(a, b) == pytest.approx(0.5)

    def test_empty_sets(self) -> None:
        """Two empty sets return 0.0."""
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty_set(self) -> None:
        """One empty set returns 0.0."""
        assert jaccard_similarity({"hello"}, set()) == 0.0


# --- Tokenization Tests ---


class TestTokenize:
    """Tests for text tokenization."""

    def test_basic_tokenization(self) -> None:
        """Text is split into lowercase tokens."""
        tokens = tokenize("Hello World Programming")
        assert "hello" in tokens
        assert "world" in tokens
        assert "programming" in tokens

    def test_stopwords_removed(self) -> None:
        """Common stopwords are filtered out."""
        tokens = tokenize("the cat is on the mat")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "on" not in tokens
        assert "cat" in tokens
        assert "mat" in tokens

    def test_punctuation_splitting(self) -> None:
        """Punctuation is used as a split point."""
        tokens = tokenize("hello-world, foo.bar!")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo" in tokens
        assert "bar" in tokens

    def test_returns_set(self) -> None:
        """Tokenize returns a set (no duplicates)."""
        tokens = tokenize("hello hello hello world")
        assert isinstance(tokens, set)
        assert "hello" in tokens

    def test_empty_string(self) -> None:
        """Empty string returns empty set."""
        assert tokenize("") == set()


# --- Duplicate Detection Tests ---


class TestDuplicateDetection:
    """Tests for is_duplicate and find_duplicates."""

    def test_exact_duplicate_detected(self) -> None:
        """Exact duplicate content is detected."""
        existing = [
            Fact(
                content="The server runs on port 8080",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            )
        ]
        assert is_duplicate(existing, "The server runs on port 8080") is True

    def test_near_duplicate_detected(self) -> None:
        """Near-duplicate with minor wording change is detected."""
        existing = [
            Fact(
                content="database connection pool size maximum",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            )
        ]
        # Adding one extra word to a 5-token phrase: 5/6 = 0.83 similarity
        assert (
            is_duplicate(
                existing, "database connection pool size maximum configuration"
            )
            is True
        )

    def test_different_content_not_duplicate(self) -> None:
        """Clearly different content is not a duplicate."""
        existing = [
            Fact(
                content="Python is a programming language",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            )
        ]
        assert (
            is_duplicate(existing, "Rust has zero-cost abstractions") is False
        )

    def test_empty_existing_no_duplicate(self) -> None:
        """Empty existing list means nothing is a duplicate."""
        assert is_duplicate([], "Any content here") is False

    def test_find_duplicates_identifies_pairs(self) -> None:
        """find_duplicates returns index pairs of similar facts."""
        facts = [
            Fact(
                content="Server configuration uses port 8080",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            ),
            Fact(
                content="Completely different topic about cooking recipes",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            ),
            Fact(
                content="Server configuration uses port 8080 setting",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        duplicates = find_duplicates(facts, threshold=0.7)
        assert (0, 2) in duplicates
        assert (0, 1) not in duplicates

    def test_find_duplicates_no_duplicates(self) -> None:
        """find_duplicates returns empty list when no duplicates exist."""
        facts = [
            Fact(
                content="Python programming language features",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            ),
            Fact(
                content="Kubernetes container orchestration platform",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        assert find_duplicates(facts) == []

    def test_custom_threshold(self) -> None:
        """Custom threshold affects duplicate detection sensitivity."""
        existing = [
            Fact(
                content="The API endpoint returns JSON data",
                source_agent_id=None,
                created_at=datetime.now(timezone.utc),
            )
        ]
        # With very low threshold, more things are duplicates
        assert (
            is_duplicate(existing, "The API endpoint returns XML data", threshold=0.5)
            is True
        )
        # With very high threshold, fewer things are duplicates
        assert (
            is_duplicate(existing, "The API endpoint returns XML data", threshold=0.95)
            is False
        )


# --- Fact Extraction Tests ---


class TestFactExtraction:
    """Tests for rule-based fact extraction."""

    def test_learned_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts facts from 'learned that ...' pattern."""
        text = "I learned that the API rate limit is 100 requests per minute."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("API rate limit" in c for c in contents)

    def test_important_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts facts from 'important: ...' pattern."""
        text = "Important: the deployment requires manual approval."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("deployment requires manual approval" in c for c in contents)

    def test_note_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts facts from 'note: ...' pattern."""
        text = "Note: the database migration takes 5 minutes."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("database migration" in c for c in contents)

    def test_always_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts behavioral rules from 'always ...' pattern."""
        text = "We should always validate user input before processing."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("always" in c.lower() for c in contents)

    def test_never_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts behavioral rules from 'never ...' pattern."""
        text = "We must never expose internal API keys to clients."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("never" in c.lower() for c in contents)

    def test_error_pattern(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracts defensive rules from error patterns."""
        text = "Error: connection timeout after 30 seconds."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 1
        contents = [f.content for f in facts]
        assert any("connection timeout" in c for c in contents)

    def test_no_patterns_matched(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Returns empty list when no patterns match."""
        text = "Just a regular sentence with nothing special."
        facts = extractor.extract_facts(text, agent_id_1)
        assert facts == []

    def test_multiple_patterns_in_text(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Multiple patterns in the same text produce multiple facts."""
        text = (
            "I learned that caching improves performance. "
            "Important: always invalidate cache on write."
        )
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) >= 2

    def test_extracted_facts_have_metadata(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracted facts include metadata about the extraction rule."""
        text = "Important: backup databases daily."
        facts = extractor.extract_facts(text, agent_id_1)
        assert facts[0].metadata is not None
        assert "fact_type" in facts[0].metadata
        assert facts[0].metadata["fact_type"] == "important"

    def test_extracted_facts_have_agent_id(
        self, extractor: FactExtractor, agent_id_1: uuid.UUID
    ) -> None:
        """Extracted facts reference the source agent."""
        text = "Note: the service runs on port 3000."
        facts = extractor.extract_facts(text, agent_id_1)
        assert facts[0].source_agent_id == agent_id_1

    def test_custom_rules(self, agent_id_1: uuid.UUID) -> None:
        """FactExtractor works with custom rules."""
        custom_rules = [
            ExtractionRule(
                pattern=r"TODO:\s*(.+?)(?:\.|$)",
                fact_type="todo",
                description="TODO items",
            )
        ]
        extractor = FactExtractor(rules=custom_rules)
        text = "TODO: implement error handling."
        facts = extractor.extract_facts(text, agent_id_1)
        assert len(facts) == 1
        assert "implement error handling" in facts[0].content

    def test_default_rules_method(self) -> None:
        """default_rules returns a non-empty list of ExtractionRule."""
        rules = FactExtractor.default_rules()
        assert len(rules) > 0
        assert all(isinstance(r, ExtractionRule) for r in rules)


# --- Promotion Engine Tests ---


class TestPromotionEngine:
    """Tests for L2 -> L3 promotion logic."""

    def test_high_access_count_promotes(
        self, promotion_engine: PromotionEngine, agent_id_1: uuid.UUID
    ) -> None:
        """Facts with high access count are promoted."""
        fact = Fact(
            content="Important organizational knowledge",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=5,
        )
        criteria = PromotionCriteria(min_access_count=3)
        all_facts: dict[uuid.UUID, list[Fact]] = {agent_id_1: [fact]}
        assert promotion_engine.should_promote(fact, criteria, all_facts) is True

    def test_low_access_count_no_promote(
        self, promotion_engine: PromotionEngine, agent_id_1: uuid.UUID
    ) -> None:
        """Facts with low access count are not promoted (without cross-agent)."""
        fact = Fact(
            content="Rarely accessed knowledge unique to agent",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=1,
        )
        criteria = PromotionCriteria(min_access_count=3, min_agents_referenced=3)
        all_facts: dict[uuid.UUID, list[Fact]] = {agent_id_1: [fact]}
        assert promotion_engine.should_promote(fact, criteria, all_facts) is False

    def test_cross_agent_validation_promotes(
        self,
        promotion_engine: PromotionEngine,
        agent_id_1: uuid.UUID,
        agent_id_2: uuid.UUID,
        agent_id_3: uuid.UUID,
    ) -> None:
        """Facts found across multiple agents are promoted."""
        fact_content = "The API gateway handles authentication"
        fact1 = Fact(
            content=fact_content,
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=1,
        )
        fact2 = Fact(
            content="The API gateway handles authentication requests",
            source_agent_id=agent_id_2,
            created_at=datetime.now(timezone.utc),
            access_count=1,
        )
        fact3 = Fact(
            content="API gateway handles auth and authentication",
            source_agent_id=agent_id_3,
            created_at=datetime.now(timezone.utc),
            access_count=0,
        )
        criteria = PromotionCriteria(min_access_count=10, min_agents_referenced=2)
        all_facts: dict[uuid.UUID, list[Fact]] = {
            agent_id_1: [fact1],
            agent_id_2: [fact2],
            agent_id_3: [fact3],
        }
        assert promotion_engine.should_promote(fact1, criteria, all_facts) is True

    def test_single_agent_no_cross_promote(
        self, promotion_engine: PromotionEngine, agent_id_1: uuid.UUID
    ) -> None:
        """Facts only in one agent's store are not cross-promoted."""
        fact = Fact(
            content="Unique knowledge only this agent has",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=0,
        )
        criteria = PromotionCriteria(min_access_count=10, min_agents_referenced=2)
        all_facts: dict[uuid.UUID, list[Fact]] = {agent_id_1: [fact]}
        assert promotion_engine.should_promote(fact, criteria, all_facts) is False

    def test_promote_eligible_returns_qualified_facts(
        self,
        promotion_engine: PromotionEngine,
        agent_id_1: uuid.UUID,
        agent_id_2: uuid.UUID,
    ) -> None:
        """promote_eligible returns all facts meeting criteria."""
        high_access_fact = Fact(
            content="Well-known deployment procedure",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=5,
        )
        low_access_fact = Fact(
            content="Obscure internal detail only seen once",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=0,
        )
        criteria = PromotionCriteria(min_access_count=3, min_agents_referenced=5)
        all_facts: dict[uuid.UUID, list[Fact]] = {
            agent_id_1: [high_access_fact, low_access_fact],
            agent_id_2: [],
        }
        eligible = promotion_engine.promote_eligible(all_facts, criteria)
        assert len(eligible) == 1
        assert eligible[0].content == "Well-known deployment procedure"

    def test_promote_eligible_deduplicates(
        self,
        promotion_engine: PromotionEngine,
        agent_id_1: uuid.UUID,
        agent_id_2: uuid.UUID,
    ) -> None:
        """promote_eligible does not return the same fact content twice."""
        fact1 = Fact(
            content="Common knowledge about the system",
            source_agent_id=agent_id_1,
            created_at=datetime.now(timezone.utc),
            access_count=5,
        )
        fact2 = Fact(
            content="Common knowledge about the system",
            source_agent_id=agent_id_2,
            created_at=datetime.now(timezone.utc),
            access_count=5,
        )
        criteria = PromotionCriteria(min_access_count=3)
        all_facts: dict[uuid.UUID, list[Fact]] = {
            agent_id_1: [fact1],
            agent_id_2: [fact2],
        }
        eligible = promotion_engine.promote_eligible(all_facts, criteria)
        # Should only return one even though both agents have the same content
        assert len(eligible) == 1

    def test_promotion_criteria_defaults(self) -> None:
        """PromotionCriteria has expected defaults."""
        criteria = PromotionCriteria()
        assert criteria.min_access_count == 3
        assert criteria.min_agents_referenced == 2
        assert criteria.min_age_hours == 24
