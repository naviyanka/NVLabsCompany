"""Tests for the skills catalog module."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nexus.tools.skills_catalog import (
    CATALOG_TTL_SECONDS,
    CatalogSkill,
    load_catalog,
    parse_catalog_markdown,
)


class TestParseCatalogMarkdown:
    """Tests for parse_catalog_markdown function."""

    def test_parse_table_rows_with_categories(self) -> None:
        """Parse table rows grouped under category headings."""
        md = (
            "## Development Tools\n"
            "\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **CodeHelper** | Helps with code | "
            "[Repo](https://github.com/alice/code-helper) |\n"
            "| **Linter** | Lints code | "
            "[Repo](https://github.com/bob/linter) |\n"
            "\n"
            "## Productivity\n"
            "\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **TaskManager** | Manages tasks | "
            "[Repo](https://github.com/carol/task-mgr) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert len(skills) == 3
        assert skills[0].name == "CodeHelper"
        assert skills[0].category == "Development Tools"
        assert skills[0].owner == "alice"
        assert skills[1].name == "Linter"
        assert skills[1].owner == "bob"
        assert skills[2].name == "TaskManager"
        assert skills[2].category == "Productivity"
        assert skills[2].owner == "carol"

    def test_handles_malformed_rows(self) -> None:
        """Skip malformed table rows with insufficient cells."""
        md = (
            "## Tools\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| OnlyOne |\n"
            "| **Valid** | Good desc | "
            "[Link](https://github.com/owner/repo) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert len(skills) == 1
        assert skills[0].name == "Valid"

    def test_extracts_github_owner(self) -> None:
        """Extract GitHub owner from repository URL."""
        md = (
            "## Cat\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Tool** | Desc | "
            "[Link](https://github.com/myorg/my-repo) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert len(skills) == 1
        assert skills[0].owner == "myorg"

    def test_deduplicates_by_name_url(self) -> None:
        """Skip duplicate entries with the same name and URL."""
        md = (
            "## Cat\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Dup** | First | "
            "[Link](https://github.com/owner/dup) |\n"
            "| **Dup** | Second | "
            "[Link](https://github.com/owner/dup) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert len(skills) == 1
        assert skills[0].description == "First"

    def test_strips_emoji_from_heading(self) -> None:
        """Strip leading emoji/pictographs from category headings."""
        md = (
            "## \U0001f527 Utilities\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Util** | A utility | "
            "[Link](https://github.com/owner/util) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert skills[0].category == "Utilities"

    def test_skips_header_rows(self) -> None:
        """Skip table header rows (Name, Skill, Tool)."""
        md = (
            "## Cat\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Real** | Desc | "
            "[Link](https://github.com/owner/real) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert len(skills) == 1
        assert skills[0].name == "Real"

    def test_h3_heading_as_category(self) -> None:
        """Use ### headings as categories."""
        md = (
            "### Sub Category\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Item** | Desc | "
            "[Link](https://github.com/x/y) |\n"
        )
        skills = parse_catalog_markdown(md)
        assert skills[0].category == "Sub Category"

    def test_empty_markdown(self) -> None:
        """Return empty list for empty markdown."""
        skills = parse_catalog_markdown("")
        assert skills == []


class TestLoadCatalog:
    """Tests for load_catalog async function."""

    @pytest.mark.asyncio
    async def test_cache_hit_fresh(self, tmp_path) -> None:
        """Return cached data when cache is fresh."""
        cache_path = str(tmp_path / "cache.json")
        cache_data = {
            "skills": [
                {
                    "name": "Cached",
                    "description": "From cache",
                    "url": "https://github.com/x/y",
                    "category": "Cat",
                    "owner": "x",
                }
            ],
            "fetched_at": time.time(),  # Fresh
        }
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        result = await load_catalog(cache_path)
        assert result["stale"] is False
        assert result["error"] is None
        assert len(result["skills"]) == 1
        assert result["skills"][0].name == "Cached"

    @pytest.mark.asyncio
    async def test_cache_miss_fetch(self, tmp_path) -> None:
        """Fetch from remote when no cache exists."""
        cache_path = str(tmp_path / "cache.json")
        mock_md = (
            "## Tools\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Fresh** | From net | "
            "[Link](https://github.com/net/fresh) |\n"
        )
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = mock_md
        mock_response.raise_for_status = lambda: None

        with patch("nexus.tools.skills_catalog.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await load_catalog(cache_path)

        assert result["stale"] is False
        assert result["error"] is None
        assert len(result["skills"]) == 1
        assert result["skills"][0].name == "Fresh"
        # Cache file should be written
        assert os.path.isfile(cache_path)

    @pytest.mark.asyncio
    async def test_stale_on_failure(self, tmp_path) -> None:
        """Return stale cache when fetch fails."""
        cache_path = str(tmp_path / "cache.json")
        # Write old cache (expired)
        cache_data = {
            "skills": [
                {
                    "name": "Old",
                    "description": "Stale",
                    "url": "https://github.com/a/b",
                    "category": "Cat",
                    "owner": "a",
                }
            ],
            "fetched_at": time.time() - CATALOG_TTL_SECONDS - 100,
        }
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        with patch("nexus.tools.skills_catalog.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPError("Connection failed")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await load_catalog(cache_path)

        assert result["stale"] is True
        assert result["error"] is not None
        assert len(result["skills"]) == 1
        assert result["skills"][0].name == "Old"

    @pytest.mark.asyncio
    async def test_no_cache_fetch_failure(self, tmp_path) -> None:
        """Return empty with error when no cache and fetch fails."""
        cache_path = str(tmp_path / "no_cache.json")

        with patch("nexus.tools.skills_catalog.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.HTTPError("Timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await load_catalog(cache_path)

        assert result["skills"] == []
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_force_bypasses_fresh_cache(self, tmp_path) -> None:
        """Force flag ignores cache freshness and re-fetches."""
        cache_path = str(tmp_path / "cache.json")
        cache_data = {
            "skills": [
                {
                    "name": "Cached",
                    "description": "Old",
                    "url": "https://github.com/a/b",
                    "category": "Cat",
                    "owner": "a",
                }
            ],
            "fetched_at": time.time(),  # Fresh
        }
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        mock_md = (
            "## Tools\n"
            "| Name | Description | Link |\n"
            "| --- | --- | --- |\n"
            "| **Refreshed** | New | "
            "[Link](https://github.com/new/repo) |\n"
        )
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = mock_md
        mock_response.raise_for_status = lambda: None

        with patch("nexus.tools.skills_catalog.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await load_catalog(cache_path, force=True)

        assert result["skills"][0].name == "Refreshed"
        assert result["stale"] is False
