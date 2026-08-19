"""LLM-based fact extraction from agent output text.

Uses cheap LLM calls (e.g., GPT-4o-mini) for structured fact extraction
with cost guards, rate limiting, and fallback to existing regex-based
extraction via FactExtractor.

Cost estimate: ~$0.001 per extraction call with GPT-4o-mini.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Awaitable
from datetime import datetime, timezone
from uuid import UUID

from nexus.memory.extract import FactExtractor
from nexus.memory.layered import Fact


# Mapping from JSON category keys to fact_type metadata values
_CATEGORY_TO_FACT_TYPE: dict[str, str] = {
    "decisions_made": "decision",
    "tools_discovered": "tool_discovery",
    "patterns_learned": "pattern",
    "errors_encountered": "error",
}

DEFAULT_PROMPT_TEMPLATE = """Extract structured facts from the following agent output text.
Return a JSON object with exactly these keys (each containing a list of strings):

{{
  "decisions_made": ["..."],
  "tools_discovered": ["..."],
  "patterns_learned": ["..."],
  "errors_encountered": ["..."]
}}

If a category has no items, use an empty list.
Only return the JSON object, no other text.

Agent output:
{text}"""


class LLMFactExtractor:
    """Extracts structured facts from agent output using LLM calls.

    Uses an async LLM callable to perform structured extraction of facts
    into four categories: decisions, tool discoveries, patterns, and errors.
    Falls back to regex-based FactExtractor on any failure.

    Cost estimate: ~$0.001 per extraction call with GPT-4o-mini.

    Example usage:
        async def my_llm(prompt: str) -> str:
            return await openai_client.complete(prompt)

        extractor = LLMFactExtractor(llm_callable=my_llm)
        facts = await extractor.extract_facts(agent_output, agent_id)
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        min_output_length: int = 200,
        max_calls_per_minute: int = 10,
        prompt_template: str | None = None,
    ) -> None:
        """Initialize the LLM-based fact extractor.

        Args:
            llm_callable: Async function that takes a prompt string and returns
                a response string. Signature: async def(str) -> str.
            min_output_length: Minimum text length to trigger LLM extraction.
                Texts shorter than this are handled by regex FactExtractor.
            max_calls_per_minute: Maximum LLM calls allowed per rolling 60-second
                window. Exceeding this triggers fallback to regex extraction.
            prompt_template: Optional custom prompt template. Must contain {text}
                placeholder. If None, uses the default structured extraction prompt.
        """
        self._llm_callable = llm_callable
        self._min_output_length = min_output_length
        self._max_calls_per_minute = max_calls_per_minute
        self._prompt_template = prompt_template or DEFAULT_PROMPT_TEMPLATE
        self._call_timestamps: list[float] = []
        self._fallback_extractor = FactExtractor()

    async def extract_facts(self, text: str, agent_id: UUID) -> list[Fact]:
        """Extract facts from text using LLM-based structured extraction.

        For short texts (below min_output_length), delegates directly to the
        regex-based FactExtractor without making an LLM call.

        For longer texts, calls the LLM with a structured prompt and parses
        the JSON response into Fact objects. Falls back to regex extraction
        if the LLM call fails or the response cannot be parsed.

        Rate limiting is enforced: if the rolling 60-second call count
        exceeds max_calls_per_minute, falls back to regex extraction.

        Args:
            text: The agent output text to extract facts from.
            agent_id: The UUID of the agent that produced this text.

        Returns:
            List of extracted Fact instances (may be empty).
        """
        # Short text bypass: use regex extraction directly
        if len(text) <= self._min_output_length:
            return self._fallback_extractor.extract_facts(text, agent_id)

        # Rate limit check
        if self._is_rate_limited():
            return self._fallback_extractor.extract_facts(text, agent_id)

        # Attempt LLM extraction
        try:
            prompt = self._prompt_template.format(text=text)
            response = await self._llm_callable(prompt)
            facts = self._parse_response(response, agent_id)
            # Record successful call timestamp for rate limiting
            self._call_timestamps.append(time.time())
            return facts
        except Exception:
            # Any failure falls back to regex extraction
            return self._fallback_extractor.extract_facts(text, agent_id)

    def _is_rate_limited(self) -> bool:
        """Check if the rate limit has been exceeded.

        Counts LLM call timestamps within the last 60 seconds.

        Returns:
            True if the rate limit is exceeded, False otherwise.
        """
        now = time.time()
        cutoff = now - 60.0
        # Prune old timestamps
        self._call_timestamps = [
            ts for ts in self._call_timestamps if ts > cutoff
        ]
        return len(self._call_timestamps) >= self._max_calls_per_minute

    def _parse_response(self, response: str, agent_id: UUID) -> list[Fact]:
        """Parse the LLM JSON response into Fact objects.

        Expects a JSON object with keys: decisions_made, tools_discovered,
        patterns_learned, errors_encountered. Each key maps to a list of strings.

        Args:
            response: The raw LLM response string (expected to be JSON).
            agent_id: The UUID of the source agent.

        Returns:
            List of Fact instances created from the parsed response.

        Raises:
            ValueError: If the response cannot be parsed as valid JSON.
            KeyError: If expected keys are missing (handled gracefully).
        """
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("LLM response is not a JSON object")

        facts: list[Fact] = []
        seen_contents: set[str] = set()
        now = datetime.now(timezone.utc)

        for category, fact_type in _CATEGORY_TO_FACT_TYPE.items():
            items = data.get(category, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, str) or not item.strip():
                    continue
                content = item.strip()
                # Deduplication: skip if same content already seen
                if content in seen_contents:
                    continue
                seen_contents.add(content)
                facts.append(
                    Fact(
                        content=content,
                        source_agent_id=agent_id,
                        created_at=now,
                        access_count=0,
                        metadata={
                            "fact_type": fact_type,
                            "extraction_method": "llm",
                        },
                    )
                )

        return facts
