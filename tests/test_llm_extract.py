"""Tests for LLM-based fact extraction (LLMFactExtractor)."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from nexus.memory.llm_extract import LLMFactExtractor, DEFAULT_PROMPT_TEMPLATE
from nexus.memory.layered import Fact


AGENT_ID = uuid4()

VALID_LLM_RESPONSE = json.dumps({
    "decisions_made": ["Use PostgreSQL for persistence", "Adopt async patterns"],
    "tools_discovered": ["pytest-asyncio for async test support"],
    "patterns_learned": ["Retry with exponential backoff improves reliability"],
    "errors_encountered": ["Connection timeout on first attempt"],
})

LONG_TEXT = "A" * 300  # Longer than default min_output_length of 200
SHORT_TEXT = "Short text"  # Shorter than 200 chars


@pytest.fixture
def mock_llm() -> AsyncMock:
    """Create a mock LLM callable that returns valid JSON."""
    llm = AsyncMock(return_value=VALID_LLM_RESPONSE)
    return llm


@pytest.fixture
def extractor(mock_llm: AsyncMock) -> LLMFactExtractor:
    """Create an LLMFactExtractor with mocked LLM."""
    return LLMFactExtractor(llm_callable=mock_llm)


async def test_successful_extraction_with_all_categories(
    extractor: LLMFactExtractor, mock_llm: AsyncMock
) -> None:
    """Test successful extraction with mocked LLM returning valid JSON with all 4 categories."""
    facts = await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    # LLM should have been called
    mock_llm.assert_called_once()

    # Should have 5 facts total (2 decisions + 1 tool + 1 pattern + 1 error)
    assert len(facts) == 5

    # Verify all facts are Fact instances
    for fact in facts:
        assert isinstance(fact, Fact)
        assert fact.source_agent_id == AGENT_ID
        assert fact.access_count == 0
        assert fact.metadata is not None
        assert "fact_type" in fact.metadata
        assert fact.metadata["extraction_method"] == "llm"

    # Check fact types distribution
    fact_types = [f.metadata["fact_type"] for f in facts]
    assert fact_types.count("decision") == 2
    assert fact_types.count("tool_discovery") == 1
    assert fact_types.count("pattern") == 1
    assert fact_types.count("error") == 1


async def test_short_text_bypasses_llm(mock_llm: AsyncMock) -> None:
    """Test that short text (< 200 chars) bypasses LLM and uses regex extraction directly."""
    extractor = LLMFactExtractor(llm_callable=mock_llm)

    # Use short text with a regex-matchable pattern
    short_input = "learned that python is great"
    facts = await extractor.extract_facts(short_input, AGENT_ID)

    # LLM should NOT have been called
    mock_llm.assert_not_called()

    # Regex extractor should have extracted something
    assert len(facts) >= 1
    assert facts[0].content == "python is great"


async def test_fallback_on_invalid_json(mock_llm: AsyncMock) -> None:
    """Test fallback when LLM returns invalid JSON."""
    mock_llm.return_value = "This is not valid JSON at all {{"

    extractor = LLMFactExtractor(llm_callable=mock_llm)

    # Use text with a regex-matchable pattern for fallback verification
    text = "learned that fallback works correctly. " + "x" * 200
    facts = await extractor.extract_facts(text, AGENT_ID)

    # LLM was called but failed to parse
    mock_llm.assert_called_once()

    # Should fall back to regex extraction
    assert len(facts) >= 1
    assert any("fallback works correctly" in f.content for f in facts)


async def test_fallback_on_llm_exception(mock_llm: AsyncMock) -> None:
    """Test fallback when LLM callable raises an exception."""
    mock_llm.side_effect = RuntimeError("API connection failed")

    extractor = LLMFactExtractor(llm_callable=mock_llm)

    text = "learned that exceptions are handled. " + "x" * 200
    facts = await extractor.extract_facts(text, AGENT_ID)

    # LLM was called but raised
    mock_llm.assert_called_once()

    # Should fall back to regex extraction
    assert len(facts) >= 1
    assert any("exceptions are handled" in f.content for f in facts)


async def test_rate_limiting() -> None:
    """Test rate limiting: set max_calls_per_minute=2, call 3 times, verify 3rd uses fallback."""
    mock_llm = AsyncMock(return_value=VALID_LLM_RESPONSE)

    extractor = LLMFactExtractor(
        llm_callable=mock_llm,
        max_calls_per_minute=2,
    )

    # First call - should use LLM
    facts1 = await extractor.extract_facts(LONG_TEXT, AGENT_ID)
    assert mock_llm.call_count == 1

    # Second call - should use LLM
    facts2 = await extractor.extract_facts(LONG_TEXT, AGENT_ID)
    assert mock_llm.call_count == 2

    # Third call - should be rate limited, uses fallback (no additional LLM call)
    text_with_pattern = "learned that rate limiting works. " + "x" * 200
    facts3 = await extractor.extract_facts(text_with_pattern, AGENT_ID)
    # LLM should NOT have been called a 3rd time
    assert mock_llm.call_count == 2

    # The fallback should have extracted from regex
    assert any("rate limiting works" in f.content for f in facts3)


async def test_extracted_facts_correct_format(
    extractor: LLMFactExtractor, mock_llm: AsyncMock
) -> None:
    """Test extracted facts have correct format (content, source_agent_id, metadata with fact_type)."""
    facts = await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    for fact in facts:
        # Content should be a non-empty string
        assert isinstance(fact.content, str)
        assert len(fact.content) > 0

        # source_agent_id should match
        assert fact.source_agent_id == AGENT_ID

        # created_at should be a datetime
        assert fact.created_at is not None

        # access_count should be 0
        assert fact.access_count == 0

        # metadata should have fact_type
        assert fact.metadata is not None
        assert "fact_type" in fact.metadata
        assert fact.metadata["fact_type"] in (
            "decision", "tool_discovery", "pattern", "error"
        )


async def test_configurable_min_output_length() -> None:
    """Test configurable min_output_length threshold."""
    mock_llm = AsyncMock(return_value=VALID_LLM_RESPONSE)

    # Set a very low threshold so even short text triggers LLM
    extractor = LLMFactExtractor(
        llm_callable=mock_llm,
        min_output_length=5,
    )

    # Text is longer than 5 chars but shorter than default 200
    text = "This is a medium-length text for testing"
    facts = await extractor.extract_facts(text, AGENT_ID)

    # LLM should have been called because text length > 5
    mock_llm.assert_called_once()
    assert len(facts) == 5  # All items from VALID_LLM_RESPONSE


async def test_custom_prompt_template() -> None:
    """Test that custom prompt template is used when provided."""
    mock_llm = AsyncMock(return_value=VALID_LLM_RESPONSE)
    custom_template = "Custom extraction prompt for: {text}"

    extractor = LLMFactExtractor(
        llm_callable=mock_llm,
        prompt_template=custom_template,
    )

    await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    # Verify the custom template was used in the LLM call
    called_prompt = mock_llm.call_args[0][0]
    assert called_prompt == f"Custom extraction prompt for: {LONG_TEXT}"


async def test_empty_categories_in_response() -> None:
    """Test that empty categories in LLM response still work."""
    empty_response = json.dumps({
        "decisions_made": [],
        "tools_discovered": [],
        "patterns_learned": [],
        "errors_encountered": [],
    })
    mock_llm = AsyncMock(return_value=empty_response)

    extractor = LLMFactExtractor(llm_callable=mock_llm)
    facts = await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    # LLM was called
    mock_llm.assert_called_once()

    # No facts extracted (all categories empty)
    assert len(facts) == 0


async def test_deduplication_across_categories() -> None:
    """Test that same content from different categories is not duplicated."""
    duplicate_response = json.dumps({
        "decisions_made": ["Use retry logic"],
        "tools_discovered": ["Use retry logic"],  # Same content as above
        "patterns_learned": ["Different pattern"],
        "errors_encountered": [],
    })
    mock_llm = AsyncMock(return_value=duplicate_response)

    extractor = LLMFactExtractor(llm_callable=mock_llm)
    facts = await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    # Should have 2 facts, not 3 (duplicate removed)
    assert len(facts) == 2

    contents = [f.content for f in facts]
    assert "Use retry logic" in contents
    assert "Different pattern" in contents


async def test_partial_categories_in_response() -> None:
    """Test that response with only some categories still works."""
    partial_response = json.dumps({
        "decisions_made": ["Only decisions here"],
    })
    mock_llm = AsyncMock(return_value=partial_response)

    extractor = LLMFactExtractor(llm_callable=mock_llm)
    facts = await extractor.extract_facts(LONG_TEXT, AGENT_ID)

    # Should extract the one fact from the available category
    assert len(facts) == 1
    assert facts[0].content == "Only decisions here"
    assert facts[0].metadata["fact_type"] == "decision"


async def test_non_dict_response_triggers_fallback() -> None:
    """Test that a JSON response that is not a dict triggers fallback."""
    mock_llm = AsyncMock(return_value=json.dumps(["not", "a", "dict"]))

    extractor = LLMFactExtractor(llm_callable=mock_llm)
    text = "learned that non-dict is handled. " + "x" * 200
    facts = await extractor.extract_facts(text, AGENT_ID)

    # Should fall back to regex extraction
    assert any("non-dict is handled" in f.content for f in facts)
