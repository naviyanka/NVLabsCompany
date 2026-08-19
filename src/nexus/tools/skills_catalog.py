"""Remote skills catalog: fetch and cache community skill listings.

Parses a GitHub README.md table format to discover community-published
skills. Implements disk-based caching with a 24-hour TTL and stale-on-failure
fallback for resilience.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass

import httpx


@dataclass(frozen=True)
class CatalogSkill:
    """A skill entry from the remote community catalog.

    Attributes:
        name: Skill name (from table row).
        description: Skill description (from table row).
        url: URL to the skill repository or page.
        category: Category heading under which the skill was listed.
        owner: GitHub repository owner extracted from the URL.
    """

    name: str
    description: str
    url: str
    category: str
    owner: str


CATALOG_URL: str = (
    "https://raw.githubusercontent.com/"
    "abubakarsiddik31/claude-skills-collection/main/README.md"
)

CATALOG_TTL_SECONDS: int = 86400  # 24 hours


def parse_catalog_markdown(md: str) -> list[CatalogSkill]:
    """Parse a GitHub README table into catalog skill entries.

    Tracks the current category from ## or ### headings. Parses table rows
    by splitting on |, requiring at least 3 cells. Skips separator rows.
    Extracts the GitHub owner from URL patterns.

    Args:
        md: Raw markdown content of the catalog README.

    Returns:
        Deduplicated list of CatalogSkill entries.
    """
    lines = md.split("\n")
    skills: list[CatalogSkill] = []
    current_category = ""
    seen: set[tuple[str, str]] = set()

    for line in lines:
        stripped = line.strip()

        # Track category from headings
        heading_match = re.match(r"^#{2,3}\s+(.*)", stripped)
        if heading_match:
            raw_heading = heading_match.group(1).strip()
            # Strip markdown formatting and leading emoji/pictographs
            clean = re.sub(r"[*`_~]", "", raw_heading)
            # Remove leading emoji (Unicode pictographs, symbols, etc.)
            clean = re.sub(
                r"^[\U0001F300-\U0001FAFF\U00002702-\U000027B0"
                r"\U0000FE00-\U0000FE0F\U0000200D\U00002600-\U000026FF"
                r"\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F]+\s*",
                "",
                clean,
            )
            current_category = clean.strip()
            continue

        # Parse table rows
        if "|" not in stripped:
            continue

        # Skip separator rows (contain ---)
        if re.match(r"^\|?\s*[-:]+\s*\|", stripped):
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # Remove empty first/last from leading/trailing |
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        if len(cells) < 3:
            continue

        # Extract name (strip bold/code formatting)
        raw_name = cells[0]
        name = re.sub(r"[*`]", "", raw_name).strip()
        if not name or name.lower() in ("name", "skill"):
            continue

        # Extract description
        description = cells[1].strip()

        # Extract URL from the third cell (or any cell with a link)
        url = ""
        for cell in cells:
            link_match = re.search(r"\[.*?\]\((https?://[^)]+)\)", cell)
            if link_match:
                url = link_match.group(1)
                break
        # Also check for bare URLs
        if not url:
            for cell in cells:
                bare_match = re.search(r"(https?://\S+)", cell)
                if bare_match:
                    url = bare_match.group(1)
                    break

        if not url:
            continue

        # Extract GitHub owner from URL
        owner = ""
        owner_match = re.search(r"github\.com/([^/]+)", url)
        if owner_match:
            owner = owner_match.group(1)

        # Deduplicate by (name, url)
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)

        skills.append(
            CatalogSkill(
                name=name,
                description=description,
                url=url,
                category=current_category,
                owner=owner,
            )
        )

    return skills


async def load_catalog(
    cache_path: str,
    force: bool = False,
) -> dict:
    """Load the skills catalog with disk caching and stale-on-failure.

    Checks the disk cache first. If fresh (< 24h TTL) and not forced,
    returns cached data. Otherwise fetches from the remote URL, parses,
    and updates the cache. On fetch failure, returns stale cache if
    available.

    Args:
        cache_path: Path to the JSON cache file on disk.
        force: If True, bypass cache freshness check and re-fetch.

    Returns:
        Dictionary with keys: skills (list of CatalogSkill dicts),
        fetched_at (float timestamp), stale (bool), error (str or None).
    """
    cached_data: dict | None = None

    # Try reading existing cache
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        cached_data = None

    # Check if cache is fresh
    if cached_data and not force:
        fetched_at = cached_data.get("fetched_at", 0)
        if time.time() - fetched_at < CATALOG_TTL_SECONDS:
            return {
                "skills": [
                    CatalogSkill(**s) for s in cached_data.get("skills", [])
                ],
                "fetched_at": fetched_at,
                "stale": False,
                "error": None,
            }

    # Fetch from remote
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(CATALOG_URL)
            response.raise_for_status()
            md = response.text
    except (httpx.HTTPError, OSError) as exc:
        # Return stale cache on failure
        if cached_data:
            return {
                "skills": [
                    CatalogSkill(**s) for s in cached_data.get("skills", [])
                ],
                "fetched_at": cached_data.get("fetched_at", 0),
                "stale": True,
                "error": str(exc),
            }
        return {
            "skills": [],
            "fetched_at": 0,
            "stale": False,
            "error": str(exc),
        }

    # Parse
    skills = parse_catalog_markdown(md)

    # If parse returned empty and we have cache, return stale
    if not skills and cached_data:
        return {
            "skills": [
                CatalogSkill(**s) for s in cached_data.get("skills", [])
            ],
            "fetched_at": cached_data.get("fetched_at", 0),
            "stale": True,
            "error": None,
        }

    # Write cache
    now = time.time()
    cache_content = {
        "skills": [asdict(s) for s in skills],
        "fetched_at": now,
    }
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_content, f)
    except OSError:
        pass  # Cache write failure is non-fatal

    return {
        "skills": skills,
        "fetched_at": now,
        "stale": False,
        "error": None,
    }


__all__ = [
    "CatalogSkill",
    "CATALOG_URL",
    "CATALOG_TTL_SECONDS",
    "parse_catalog_markdown",
    "load_catalog",
]
