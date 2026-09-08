"""Tests for wikilink extraction and the derived graph (ADR 0002 §14, Phase 1D).

Two guarantees are the point of this file. First, a link is read only when a
human meant it as a relationship: a link shown inside a code fence is
documentation, not an edge. Second, edges stay derive-on-read — the graph route
resolves them from the registry at request time, and no edge table exists for
them to drift against.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes.memory_graph import (
    MAX_DANGLING_NODES,
    get_memory_graph,
)
from nexus.knowledge.embeddings import NullEmbeddingProvider
from nexus.knowledge.parsers import MarkdownParser
from nexus.knowledge.rag import RAGPipeline
from nexus.models.obsidian import ObsidianDocument
from nexus.obsidian import VaultIndexer, VaultScanner
from nexus.obsidian.wikilinks import (
    MAX_LINKS_PER_NOTE,
    extract_wikilinks,
    frontmatter_links,
    normalize_target,
    note_links,
)

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ---------------------------------------------------------------------------
# Parsing: which brackets are a relationship
# ---------------------------------------------------------------------------


def test_plain_wikilink_is_extracted() -> None:
    assert extract_wikilinks("See [[Security Architecture]] for context.") == [
        "Security Architecture"
    ]


def test_alias_and_heading_are_display_only() -> None:
    """Two notes are related whether or not the link renders under a label."""
    body = "[[Cipher|the agent]] and [[Runtime#Startup]] and [[Notes^block-id]]"
    assert extract_wikilinks(body) == ["Cipher", "Runtime", "Notes"]


def test_embed_syntax_counts_as_a_link() -> None:
    assert extract_wikilinks("![[Diagram]]") == ["Diagram"]


def test_md_extension_is_stripped() -> None:
    assert extract_wikilinks("[[Knowledge/SSRF.md]]") == ["Knowledge/SSRF"]


def test_duplicates_collapse_case_insensitively_keeping_first_form() -> None:
    assert extract_wikilinks("[[Cipher]] [[cipher]] [[CIPHER]]") == ["Cipher"]


def test_link_in_a_fenced_block_is_not_a_relationship() -> None:
    """A note documenting the syntax does not thereby relate to "Target"."""
    body = "Use it like this:\n\n```markdown\n[[Target]]\n```\n\nSee [[Real]].\n"
    assert extract_wikilinks(body) == ["Real"]


def test_link_in_a_tilde_fence_is_also_ignored() -> None:
    body = "~~~\n[[Fenced]]\n~~~\n[[Real]]"
    assert extract_wikilinks(body) == ["Real"]


def test_link_in_an_inline_code_span_is_ignored() -> None:
    assert extract_wikilinks("write `[[Target]]` to link; see [[Real]]") == ["Real"]


def test_empty_and_whitespace_targets_are_dropped() -> None:
    assert extract_wikilinks("[[]] [[   ]] [[#heading-only]]") == []


def test_unclosed_brackets_are_not_a_link() -> None:
    assert extract_wikilinks("[[Unclosed and [[Nested]]") == ["Nested"]


def test_body_without_brackets_short_circuits() -> None:
    assert extract_wikilinks("No links at all here.") == []


def test_link_count_is_capped() -> None:
    """A generated index note must not swamp the derived graph."""
    body = " ".join(f"[[Note {i}]]" for i in range(MAX_LINKS_PER_NOTE + 25))
    assert len(extract_wikilinks(body)) == MAX_LINKS_PER_NOTE


def test_overlong_target_is_truncated_not_dropped() -> None:
    target = normalize_target("x" * 900)
    assert 0 < len(target) <= 512


# ---------------------------------------------------------------------------
# Frontmatter `related`, per ADR 0002 §14
# ---------------------------------------------------------------------------


def test_frontmatter_related_accepts_bare_titles_and_wikilinks() -> None:
    assert frontmatter_links({"related": ["Cipher", "[[SSRF Protection]]"]}) == [
        "Cipher",
        "SSRF Protection",
    ]


def test_frontmatter_related_accepts_a_single_scalar() -> None:
    assert frontmatter_links({"related": "Cipher"}) == ["Cipher"]


def test_malformed_related_entry_is_skipped_not_fatal() -> None:
    """One bad note must not fail the scan (same contract as parse_note)."""
    assert frontmatter_links({"related": [{"nested": "map"}, "Cipher"]}) == ["Cipher"]


def test_note_without_related_has_no_frontmatter_links() -> None:
    assert frontmatter_links({}) == []


def test_note_links_merges_body_and_frontmatter_without_duplicates() -> None:
    links = note_links({"related": ["Cipher", "Extra"]}, "Body links to [[Cipher]].")
    assert links == ["Cipher", "Extra"]


# ---------------------------------------------------------------------------
# Storage: parsed during indexing, onto the document row
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wiki.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vaults"
    (root / str(COMPANY_A) / "Knowledge").mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        yield root


def write_note(root: Path, rel: str, body: str) -> None:
    path = root / str(COMPANY_A) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


async def scan_and_index(factory) -> None:
    """Register the vault and index it, as the operator endpoints do."""
    async with factory() as db:
        await VaultScanner(db, COMPANY_A).scan()
        await db.commit()
    async with factory() as db:
        pipeline = RAGPipeline(
            db=db, embedding_provider=NullEmbeddingProvider(), parser=MarkdownParser()
        )
        await VaultIndexer(db, COMPANY_A, pipeline=pipeline).index_stale()
        await db.commit()


async def documents(factory) -> list[ObsidianDocument]:
    async with factory() as db:
        statement = (
            select(ObsidianDocument)
            .where(ObsidianDocument.company_id == COMPANY_A)
            .order_by(ObsidianDocument.vault_path)
        )
        return list((await db.execute(statement)).scalars().all())


async def test_indexing_records_the_notes_link_targets(vault, session_factory) -> None:
    write_note(
        vault,
        "Knowledge/SSRF.md",
        "---\ntype: knowledge\nrelated:\n  - Incident INC-042\n---\n"
        "# SSRF\n\nValidate hosts. See [[Security Architecture]].\n",
    )
    await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.wikilink_targets == ["Security Architecture", "Incident INC-042"]


async def test_a_note_with_no_links_stores_none_not_an_empty_list(
    vault, session_factory
) -> None:
    write_note(vault, "Knowledge/Plain.md", "# Plain\n\nNo links.\n")
    await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.wikilink_targets is None


async def test_links_are_recorded_even_when_the_note_has_no_indexable_prose(
    vault, session_factory
) -> None:
    """A hub note that is only links still relates to its neighbours."""
    write_note(vault, "Knowledge/Hub.md", "---\nrelated: [Cipher]\n---\n")
    await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.wikilink_targets == ["Cipher"]


async def test_edited_links_replace_the_previous_set(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nLinks [[Old]].\n")
    await scan_and_index(session_factory)

    write_note(vault, "Knowledge/A.md", "# A\n\nLinks [[New]] now.\n")
    await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.wikilink_targets == ["New"]


# ---------------------------------------------------------------------------
# Derived graph: resolved on read, with no edge table
# ---------------------------------------------------------------------------


async def graph(session_factory) -> dict:
    async with session_factory() as db:
        return await get_memory_graph(COMPANY_A, db)


async def test_no_persisted_edge_table_backs_the_graph() -> None:
    """ADR 0002 §14 forbids a second graph source of truth."""
    tables = set(SQLModel.metadata.tables)
    assert not [
        name
        for name in tables
        if "wikilink" in name or name.endswith(("_edges", "_links", "_relations"))
    ]


async def test_wikilink_becomes_an_edge_between_two_vault_notes(
    vault, session_factory
) -> None:
    write_note(vault, "Knowledge/SSRF.md", "# SSRF\n\nPart of [[Security Architecture]].\n")
    write_note(vault, "Knowledge/Security Architecture.md", "# Security Architecture\n\nTop level.\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    wikilinks = [link for link in result["links"] if link["type"] == "wikilink"]
    assert len(wikilinks) == 1

    labels = {node["id"]: node["label"] for node in result["nodes"]}
    edge = wikilinks[0]
    assert labels[edge["source"]] == "SSRF"
    assert labels[edge["target"]] == "Security Architecture"


async def test_a_link_resolves_by_vault_path_as_well_as_title(
    vault, session_factory
) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Knowledge/Target]].\n")
    write_note(vault, "Knowledge/Target.md", "---\ntitle: Wholly Different\n---\n# T\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    wikilinks = [link for link in result["links"] if link["type"] == "wikilink"]
    assert len(wikilinks) == 1
    assert not any(node["index_status"] == "missing" for node in result["nodes"])


async def test_link_matching_is_case_insensitive(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[cipher]].\n")
    write_note(vault, "Knowledge/Cipher.md", "# Cipher\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    assert len([l for l in result["links"] if l["type"] == "wikilink"]) == 1
    assert not any(node["index_status"] == "missing" for node in result["nodes"])


async def test_dangling_link_becomes_a_missing_node(vault, session_factory) -> None:
    """A relationship stated before the other note exists is information."""
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Not Written Yet]].\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    missing = [node for node in result["nodes"] if node["index_status"] == "missing"]
    assert [node["label"] for node in missing] == ["Not Written Yet"]
    assert len([l for l in result["links"] if l["type"] == "wikilink"]) == 1


async def test_two_notes_linking_the_same_missing_target_share_one_node(
    vault, session_factory
) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\n[[Ghost]]\n")
    write_note(vault, "Knowledge/B.md", "# B\n\n[[ghost]]\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    missing = [node for node in result["nodes"] if node["index_status"] == "missing"]
    assert len(missing) == 1
    assert len([l for l in result["links"] if l["type"] == "wikilink"]) == 2


async def test_dangling_nodes_are_capped(vault, session_factory) -> None:
    links = "\n".join(f"[[Ghost {i}]]" for i in range(MAX_DANGLING_NODES + 20))
    write_note(vault, "Knowledge/Index.md", f"# Index\n\n{links}\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    missing = [node for node in result["nodes"] if node["index_status"] == "missing"]
    assert len(missing) == MAX_DANGLING_NODES


async def test_self_link_produces_no_edge(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[A]].\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    assert [l for l in result["links"] if l["type"] == "wikilink"] == []


async def test_vault_nodes_are_namespaced_apart_from_memory_nodes(
    vault, session_factory
) -> None:
    """A note and a memory about the same subject are two nodes, not one."""
    write_note(vault, "Knowledge/A.md", "# A\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    vault_nodes = [node for node in result["nodes"] if node["community"] == "vault"]
    assert vault_nodes
    assert all(node["id"].startswith("obsidian:") for node in vault_nodes)


async def test_metrics_and_clusters_include_the_vault(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\n[[B]]\n")
    write_note(vault, "Knowledge/B.md", "# B\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    assert result["metrics"]["total_nodes"] == len(result["nodes"])
    assert result["metrics"]["total_links"] == len(result["links"])
    assert any(cluster["id"] == "vault" for cluster in result["clusters"])


async def test_company_without_a_vault_gets_the_memory_graph_unchanged(
    session_factory,
) -> None:
    result = await graph(session_factory)
    assert result["nodes"] == []
    assert not any(cluster["id"] == "vault" for cluster in result["clusters"])


async def test_another_tenants_notes_never_appear(vault, session_factory) -> None:
    other = uuid.UUID("22222222-2222-2222-2222-222222222222")
    write_note(vault, "Knowledge/Mine.md", "# Mine\n")
    await scan_and_index(session_factory)

    async with session_factory() as db:
        result = await get_memory_graph(other, db)
    assert result["nodes"] == []


# ---------------------------------------------------------------------------
# Resolution: folders, duplicate basenames, and what a link cannot reach
# ---------------------------------------------------------------------------


def test_folder_qualified_target_keeps_its_folder() -> None:
    """``[[Folder/Note]]`` names a path, so the folder is part of the target."""
    assert extract_wikilinks("See [[Knowledge/SSRF]].") == ["Knowledge/SSRF"]


def test_heading_only_link_is_not_a_relationship() -> None:
    """``[[#Heading]]`` points inside the same note, so there is no second note."""
    assert extract_wikilinks("Jump to [[#Overview]].") == []
    assert normalize_target("#Overview") == ""


async def test_a_link_resolves_through_a_folder_path(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Knowledge/Nested/Deep]].\n")
    write_note(vault, "Knowledge/Nested/Deep.md", "# Deep\n\nBottom.\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    wikilinks = [link for link in result["links"] if link["type"] == "wikilink"]
    assert len(wikilinks) == 1, "a folder-qualified link did not resolve"
    assert not [node for node in result["nodes"] if "missing" in node.get("tags", [])]


async def test_duplicate_basenames_resolve_to_one_note_deterministically(
    vault, session_factory
) -> None:
    """Two notes can share a filename, and a bare title cannot name both.

    Obsidian disambiguates with the folder path; a bare title is ambiguous. One
    note wins, chosen by vault path order rather than by row order, so the same
    vault always produces the same graph — an unstable choice would make the
    edge move between requests with nothing having changed.
    """
    write_note(vault, "Knowledge/Alpha/Shared.md", "# Shared\n\nFirst.\n")
    write_note(vault, "Knowledge/Beta/Shared.md", "# Shared\n\nSecond.\n")
    write_note(vault, "Knowledge/Link.md", "# Link\n\nSee [[Shared]].\n")
    await scan_and_index(session_factory)

    first = await graph(session_factory)
    second = await graph(session_factory)
    edges = [link for link in first["links"] if link["type"] == "wikilink"]
    assert len(edges) == 1, "a bare ambiguous title produced more than one edge"
    assert edges == [link for link in second["links"] if link["type"] == "wikilink"], (
        "the winning note changed between two identical requests"
    )

    # Both notes are still reachable by their folder-qualified paths.
    qualified = {node.get("vault_path") for node in first["nodes"]}
    assert {"Knowledge/Alpha/Shared.md", "Knowledge/Beta/Shared.md"} <= qualified


@pytest.mark.parametrize(
    "target",
    [
        "../../../etc/passwd",
        "../../Secrets",
        "/etc/passwd",
        "C:/Windows/System32/config/SAM",
        "C:\\Windows\\System32\\config\\SAM",
        "//host/share/Secret",
        "\\\\host\\share\\Secret",
    ],
)
async def test_a_path_shaped_target_reaches_nothing(
    vault, session_factory, target
) -> None:
    """Resolution is a registry lookup, so a path-shaped target cannot escape.

    Traversal, absolute, drive-relative and UNC forms are all just text here:
    nothing is opened, and a target that matches no registered note becomes a
    dangling node like any other. The security boundary is not re-implemented —
    a link never becomes a filesystem read in the first place.
    """
    write_note(vault, "Knowledge/A.md", f"# A\n\nSee [[{target}]].\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    real = [node for node in result["nodes"] if node.get("vault_path")]
    assert [node["vault_path"] for node in real] == ["Knowledge/A.md"]
    for node in result["nodes"]:
        assert str(vault) not in node.get("raw_content", "")
        assert str(vault) not in node["summary"]


async def test_a_link_cannot_reach_another_companys_note(
    vault, session_factory
) -> None:
    """Two companies with the same note title stay separate graphs."""
    other = uuid.UUID("22222222-2222-2222-2222-222222222222")
    (vault / str(other)).mkdir(parents=True, exist_ok=True)
    (vault / str(other) / "Shared.md").write_text("# Shared\n\nTheirs.\n", encoding="utf-8")
    write_note(vault, "Knowledge/Mine.md", "# Mine\n\nSee [[Shared]].\n")

    async with session_factory() as db:
        await VaultScanner(db, COMPANY_A).scan()
        await VaultScanner(db, other).scan()
        await db.commit()
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    # The link found nothing of ours, so it dangles rather than crossing tenants.
    dangling = [node for node in result["nodes"] if "missing" in node.get("tags", [])]
    assert len(dangling) == 1
    assert [link for link in result["links"] if link["type"] == "wikilink"]
    assert all(
        node.get("vault_path") in (None, "Knowledge/Mine.md") for node in result["nodes"]
    )


# ---------------------------------------------------------------------------
# Graph mutation: no stale edge survives an edit or a deletion
# ---------------------------------------------------------------------------


def _edge_pairs(result: dict) -> set[tuple[str, str]]:
    """Wikilink edges as (source label, target label) pairs."""
    labels = {node["id"]: node["label"] for node in result["nodes"]}
    return {
        (labels[link["source"]], labels[link["target"]])
        for link in result["links"]
        if link["type"] == "wikilink"
    }


async def test_retargeting_a_link_leaves_no_stale_edge(vault, session_factory) -> None:
    """A -> B, then A is edited to point at C: the A -> B edge must be gone."""
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "Knowledge/B.md", "# B\n")
    write_note(vault, "Knowledge/C.md", "# C\n")
    await scan_and_index(session_factory)
    assert _edge_pairs(await graph(session_factory)) == {("A", "B")}

    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[C]] instead.\n")
    await scan_and_index(session_factory)

    assert _edge_pairs(await graph(session_factory)) == {("A", "C")}


async def test_adding_a_second_link_keeps_the_first(vault, session_factory) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "Knowledge/B.md", "# B\n")
    write_note(vault, "Knowledge/C.md", "# C\n")
    await scan_and_index(session_factory)

    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[B]] and [[C]].\n")
    await scan_and_index(session_factory)

    assert _edge_pairs(await graph(session_factory)) == {("A", "B"), ("A", "C")}


async def test_deleting_the_source_note_removes_its_edges(
    vault, session_factory
) -> None:
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "Knowledge/B.md", "# B\n")
    await scan_and_index(session_factory)

    (vault / str(COMPANY_A) / "Knowledge" / "A.md").unlink()
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    assert _edge_pairs(result) == set()
    assert [node["label"] for node in result["nodes"]] == ["B"]


async def test_deleting_the_target_note_turns_the_edge_dangling(
    vault, session_factory
) -> None:
    """The relationship survives the note: a human still said A relates to B."""
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "Knowledge/B.md", "# B\n")
    await scan_and_index(session_factory)

    (vault / str(COMPANY_A) / "Knowledge" / "B.md").unlink()
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    assert _edge_pairs(result) == {("A", "B")}
    missing = [node for node in result["nodes"] if "missing" in node.get("tags", [])]
    assert len(missing) == 1, "the deleted target did not become a dangling node"
    assert missing[0]["index_status"] == "missing"
    assert "vault_path" not in missing[0], (
        "a dangling node claimed a vault path it does not have"
    )


async def test_a_dangling_link_is_not_a_registered_document(
    vault, session_factory
) -> None:
    """A missing target is derived at read time, never a row in the registry."""
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Nowhere]].\n")
    await scan_and_index(session_factory)

    rows = await documents(session_factory)
    assert [row.vault_path for row in rows] == ["Knowledge/A.md"]


# ---------------------------------------------------------------------------
# Identity: what a rename does to the edges pointing at a note
# ---------------------------------------------------------------------------


async def test_rename_with_a_nexus_id_keeps_the_note_and_its_inbound_edge(
    vault, session_factory
) -> None:
    """A note carrying a nexus_id is the same node after a move.

    The link text still names the old title, so the *edge* re-resolves against the
    new title rather than following the move — but the node's identity, and
    therefore everything else attached to it, is preserved.
    """
    note_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    write_note(
        vault, "Knowledge/Target.md", f"---\nnexus_id: {note_id}\n---\n# Target\n\nBody.\n"
    )
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Target]].\n")
    await scan_and_index(session_factory)
    assert _edge_pairs(await graph(session_factory)) == {("A", "Target")}

    (vault / str(COMPANY_A) / "Knowledge" / "Target.md").unlink()
    write_note(
        vault,
        "Knowledge/Moved/Target.md",
        f"---\nnexus_id: {note_id}\n---\n# Target\n\nBody.\n",
    )
    await scan_and_index(session_factory)

    rows = await documents(session_factory)
    moved = [row for row in rows if row.vault_path == "Knowledge/Moved/Target.md"]
    assert len(moved) == 1
    assert moved[0].nexus_id == note_id, "the move created a new identity"
    assert len(rows) == 2, "the moved note was registered twice"
    assert _edge_pairs(await graph(session_factory)) == {("A", "Target")}


async def test_rename_without_a_nexus_id_is_a_new_note_and_the_edge_dangles(
    vault, session_factory
) -> None:
    """Phase 1 does not write ids into frontmatter, so path is the identity.

    An untagged note that moves is a delete plus a create. This is a real
    limitation, not something the graph papers over: an inbound link that named
    the old title is left dangling, which is visible rather than silent.
    """
    write_note(vault, "Knowledge/Target.md", "# Target\n\nBody.\n")
    write_note(vault, "Knowledge/A.md", "# A\n\nSee [[Target]].\n")
    await scan_and_index(session_factory)
    before = {row.vault_path: row.nexus_id for row in await documents(session_factory)}

    (vault / str(COMPANY_A) / "Knowledge" / "Target.md").unlink()
    write_note(vault, "Knowledge/Renamed.md", "# Target\n\nBody.\n")
    await scan_and_index(session_factory)

    after = {row.vault_path: row.nexus_id for row in await documents(session_factory)}
    assert "Knowledge/Target.md" not in after, "the old path stayed registered"
    assert after["Knowledge/Renamed.md"] != before["Knowledge/Target.md"], (
        "an untagged rename was treated as identity-preserving"
    )

    # The link still resolves, because the note kept its H1 title — the identity
    # changed underneath it, which is the part that is not preserved.
    result = await graph(session_factory)
    assert _edge_pairs(result) == {("A", "Target")}


# ---------------------------------------------------------------------------
# A bad link must never break indexing, and the graph route stays tenant-scoped
# ---------------------------------------------------------------------------


async def test_a_malformed_link_does_not_fail_indexing(vault, session_factory) -> None:
    """Extraction is best-effort: RAG indexing outranks link discovery."""
    from nexus.models.obsidian import INDEX_STATUS_INDEXED

    write_note(
        vault,
        "Knowledge/Ugly.md",
        "---\nrelated:\n  nested: {bad: shape}\n---\n"
        "# Ugly\n\nProse worth indexing. [[unclosed and [[]] and [[   ]]\n",
    )
    await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED
    assert doc.wikilink_targets is None


async def test_an_extraction_failure_does_not_fail_indexing(
    vault, session_factory
) -> None:
    """Even an outright bug in the parser must not cost the note its index."""
    from nexus.models.obsidian import INDEX_STATUS_INDEXED

    write_note(vault, "Knowledge/A.md", "# A\n\nProse worth indexing. [[B]]\n")
    with patch(
        "nexus.obsidian.indexer.note_links", side_effect=RuntimeError("parser bug")
    ):
        await scan_and_index(session_factory)

    (doc,) = await documents(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED, (
        "a link-extraction failure cost the note its RAG index"
    )
    assert doc.wikilink_targets is None


def test_the_graph_route_validates_the_company_in_the_url() -> None:
    """A client must not be able to read another tenant's graph by editing the path.

    The auth middleware also rejects this URL shape on a mismatch, but it falls
    open when auth is disabled, and the vault subgraph carries note titles and
    vault-relative paths — so the dependency is declared on the route as well.
    """
    import inspect

    from nexus.api.deps import PathCompanyId

    annotation = inspect.signature(get_memory_graph).parameters["company_id"].annotation
    assert annotation is PathCompanyId
