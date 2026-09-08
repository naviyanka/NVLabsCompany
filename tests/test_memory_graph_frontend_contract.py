"""The memory graph payload against the dashboard's TypeScript contract.

The dashboard renders this endpoint's response directly, and its types are the
only thing standing between a payload change and a blank canvas. There is no
JavaScript test runner in ``dashboard/`` — ``npm run lint`` is ``tsc --noEmit``,
which checks the types against each other but never against a real response. So
the contract is pinned from this side: these tests read the actual ``.ts`` files
and assert that what the API emits is what the frontend declares it can render.

That means a field renamed here, or a new node or edge kind added, fails a test
rather than silently reaching a consumer that drops it.

Realism matters for the same reason: the graph under test is built by writing
real Markdown into a temporary vault and running the real scan, index and
derivation path. No node or edge is hand-inserted, and the development vault is
never touched.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes.memory_graph import get_memory_graph
from nexus.knowledge.embeddings import NullEmbeddingProvider
from nexus.knowledge.parsers import MarkdownParser
from nexus.knowledge.rag import RAGPipeline
from nexus.obsidian import VaultIndexer, VaultScanner

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard" / "src"
TYPES_FILE = DASHBOARD / "types" / "memoryGraph.ts"
ADAPTER_FILE = DASHBOARD / "lib" / "memoryGraphAdapter.ts"
PAGE_FILE = DASHBOARD / "pages" / "MemoryGraph.tsx"
API_FILE = DASHBOARD / "api" / "memoryGraph.ts"

# Fields the frontend types declare as required (no `?`). A response missing one
# reaches the renderer as undefined.
REQUIRED_NODE_FIELDS = {
    "id",
    "label",
    "type",
    "community",
    "importance",
    "confidence",
    "created_at",
    "updated_at",
    "summary",
    "tags",
}
REQUIRED_LINK_FIELDS = {"id", "source", "target", "type", "weight"}
REQUIRED_CLUSTER_FIELDS = {"id", "name", "description", "lead_agent_id", "color", "accent_color"}
REQUIRED_METRIC_FIELDS = {
    "total_nodes",
    "total_links",
    "contradictions_count",
    "avg_confidence",
    "avg_importance",
    "modularity_score",
    "clustering_coefficient",
    "memory_recall_rate",
    "hnsw_index_size_kb",
}


def _ts_union(source: str, name: str) -> set[str]:
    """The string members of an exported TS union type."""
    match = re.search(rf"export type {name} =(.+?);", source, re.S)
    assert match, f"{name} is no longer declared in the dashboard types"
    return set(re.findall(r"'([^']+)'", match.group(1)))


@pytest.fixture(scope="module")
def ts_sources() -> dict[str, str]:
    for path in (TYPES_FILE, ADAPTER_FILE, PAGE_FILE, API_FILE):
        assert path.is_file(), f"the dashboard file this contract pins is gone: {path}"
    return {
        "types": TYPES_FILE.read_text(encoding="utf-8"),
        "adapter": ADAPTER_FILE.read_text(encoding="utf-8"),
        "page": PAGE_FILE.read_text(encoding="utf-8"),
        "api": API_FILE.read_text(encoding="utf-8"),
    }


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'graph.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def vault(tmp_path):
    """A temporary vault root. The development vault is never written to."""
    root = tmp_path / "vaults"
    (root / str(COMPANY_A)).mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        yield root


def write_note(root: Path, rel: str, body: str) -> None:
    path = root / str(COMPANY_A) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


async def scan_and_index(factory) -> None:
    """The real operator path: register the vault, then index it."""
    async with factory() as db:
        await VaultScanner(db, COMPANY_A).scan()
        await db.commit()
    async with factory() as db:
        pipeline = RAGPipeline(
            db=db, embedding_provider=NullEmbeddingProvider(), parser=MarkdownParser()
        )
        await VaultIndexer(db, COMPANY_A, pipeline=pipeline).index_stale()
        await db.commit()


async def graph(factory, company: uuid.UUID = COMPANY_A) -> dict:
    async with factory() as db:
        return await get_memory_graph(company, db)


async def linked_vault_graph(vault, session_factory) -> dict:
    """A -> B by wikilink, plus a dangling target, through the real pipeline."""
    write_note(vault, "A.md", "# A\n\nRelates to [[B]] and [[Nowhere]].\n")
    write_note(vault, "B.md", "# B\n\nOrdinary prose.\n")
    await scan_and_index(session_factory)
    return await graph(session_factory)


# ---------------------------------------------------------------------------
# Response shape against the declared types
# ---------------------------------------------------------------------------


async def test_response_has_the_four_top_level_keys(vault, session_factory) -> None:
    """``MemoryGraphData`` declares exactly these, and the page reads all four."""
    result = await linked_vault_graph(vault, session_factory)
    assert set(result) == {"nodes", "links", "clusters", "metrics"}


async def test_every_node_carries_the_required_fields(vault, session_factory) -> None:
    result = await linked_vault_graph(vault, session_factory)
    assert result["nodes"], "nothing was derived, so the test proves nothing"
    for node in result["nodes"]:
        missing = REQUIRED_NODE_FIELDS - set(node)
        assert not missing, f"node {node.get('id')} is missing {sorted(missing)}"


async def test_every_link_carries_the_required_fields(vault, session_factory) -> None:
    result = await linked_vault_graph(vault, session_factory)
    assert result["links"], "no edges were derived, so the test proves nothing"
    for link in result["links"]:
        missing = REQUIRED_LINK_FIELDS - set(link)
        assert not missing, f"link {link.get('id')} is missing {sorted(missing)}"


async def test_clusters_and_metrics_match_the_declared_shape(
    vault, session_factory
) -> None:
    result = await linked_vault_graph(vault, session_factory)
    for cluster in result["clusters"]:
        assert REQUIRED_CLUSTER_FIELDS <= set(cluster)
    assert REQUIRED_METRIC_FIELDS == set(result["metrics"])


async def test_node_types_are_all_in_the_frontend_union(
    vault, session_factory, ts_sources
) -> None:
    """A node type the union does not list renders through an untested fallback."""
    declared = _ts_union(ts_sources["types"], "MemoryNodeType")
    result = await linked_vault_graph(vault, session_factory)
    emitted = {node["type"] for node in result["nodes"]}
    assert emitted <= declared, f"undeclared node types: {sorted(emitted - declared)}"


async def test_edge_types_are_all_in_the_frontend_union(
    vault, session_factory, ts_sources
) -> None:
    declared = _ts_union(ts_sources["types"], "MemoryEdgeType")
    result = await linked_vault_graph(vault, session_factory)
    emitted = {link["type"] for link in result["links"]}
    assert emitted <= declared, f"undeclared edge types: {sorted(emitted - declared)}"
    assert "wikilink" in emitted, "the vault produced no wikilink edge to check"


def test_every_edge_type_has_a_colour(ts_sources) -> None:
    """``EDGE_TYPE_COLORS`` is keyed by the union, so a gap is a compile error.

    Asserted here as well because ``tsc`` is the only frontend gate and it is not
    run by this suite: a missing entry would fall back to grey at runtime.
    """
    declared = _ts_union(ts_sources["types"], "MemoryEdgeType")
    coloured = set(
        re.findall(r"^\s{2}(\w+): \{ stroke:", ts_sources["adapter"], re.M)
    )
    assert declared <= coloured, f"edge types with no colour: {sorted(declared - coloured)}"


# ---------------------------------------------------------------------------
# Obsidian nodes and wikilink edges, end to end
# ---------------------------------------------------------------------------


async def test_a_wikilink_between_two_notes_reaches_the_payload(
    vault, session_factory
) -> None:
    """The headline: real files, real scan and index, one A -> B edge."""
    write_note(vault, "A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "B.md", "# B\n\nProse.\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    labels = {node["id"]: node["label"] for node in result["nodes"]}
    edges = {
        (labels[link["source"]], labels[link["target"]])
        for link in result["links"]
        if link["type"] == "wikilink"
    }
    assert edges == {("A", "B")}


async def test_two_wikilinks_from_one_note_both_reach_the_payload(
    vault, session_factory
) -> None:
    write_note(vault, "A.md", "# A\n\nSee [[B]] and [[C]].\n")
    write_note(vault, "B.md", "# B\n")
    write_note(vault, "C.md", "# C\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    labels = {node["id"]: node["label"] for node in result["nodes"]}
    edges = {
        (labels[link["source"]], labels[link["target"]])
        for link in result["links"]
        if link["type"] == "wikilink"
    }
    assert edges == {("A", "B"), ("A", "C")}


async def test_an_edited_note_changes_the_payload_on_the_next_fetch(
    vault, session_factory
) -> None:
    """Derive-on-read is what makes the refresh button meaningful."""
    write_note(vault, "A.md", "# A\n\nSee [[B]].\n")
    write_note(vault, "B.md", "# B\n")
    write_note(vault, "C.md", "# C\n")
    await scan_and_index(session_factory)

    write_note(vault, "A.md", "# A\n\nSee [[C]] now.\n")
    await scan_and_index(session_factory)

    result = await graph(session_factory)
    labels = {node["id"]: node["label"] for node in result["nodes"]}
    edges = {
        (labels[link["source"]], labels[link["target"]])
        for link in result["links"]
        if link["type"] == "wikilink"
    }
    assert edges == {("A", "C")}, "a stale edge survived into the payload"


async def test_vault_nodes_are_distinguishable_from_memory_nodes(
    vault, session_factory
) -> None:
    """The frontend needs to tell a note apart from a memory without guessing.

    Three signals travel with a vault node: the ``obsidian:`` id prefix, the
    ``vault`` community, and a ``vault`` tag. The node ``type`` is the existing
    generic ``knowledge`` — deliberately, because the renderer already draws that
    and inventing a type would need a colour, a glyph and a legend entry for no
    behavioural gain.
    """
    result = await linked_vault_graph(vault, session_factory)
    vault_nodes = [node for node in result["nodes"] if node["id"].startswith("obsidian:")]
    assert vault_nodes
    for node in vault_nodes:
        assert node["community"] == "vault"
        assert "vault" in node["tags"]
        assert node["type"] == "knowledge"


async def test_a_dangling_target_is_marked_and_carries_no_path(
    vault, session_factory
) -> None:
    """A missing note is a derived node, not a registered document."""
    result = await linked_vault_graph(vault, session_factory)
    missing = [node for node in result["nodes"] if "missing" in node["tags"]]
    assert len(missing) == 1
    assert missing[0]["id"].startswith("obsidian:missing:")
    assert missing[0]["index_status"] == "missing"
    assert "vault_path" not in missing[0], "a node with no file claimed a path"


async def test_memory_knowledge_and_vault_nodes_coexist(
    vault, session_factory
) -> None:
    """A company with both memories and notes gets one graph, not two."""
    from nexus.models.memory import MemoryRecord

    async with session_factory() as db:
        db.add(
            MemoryRecord(
                company_id=COMPANY_A,
                agent_id=uuid.uuid4(),
                scope="long_term",
                content="An ordinary memory record.",
                importance=0.9,
            )
        )
        await db.commit()

    result = await linked_vault_graph(vault, session_factory)
    ids = [node["id"] for node in result["nodes"]]
    assert any(node_id.startswith("obsidian:") for node_id in ids)
    assert any(not node_id.startswith("obsidian:") for node_id in ids), (
        "the memory node was lost when the vault subgraph was merged in"
    )
    assert len(set(ids)) == len(ids), "a vault node collided with a memory node"


# ---------------------------------------------------------------------------
# What the payload must never contain
# ---------------------------------------------------------------------------


async def test_no_host_path_reaches_the_payload(vault, session_factory) -> None:
    """Vault paths are vault-relative; the root is host layout and stays here."""
    import json

    result = await linked_vault_graph(vault, session_factory)
    serialized = json.dumps(result)
    assert str(vault) not in serialized
    assert str(vault.parent) not in serialized
    assert "C:\\" not in serialized
    for node in result["nodes"]:
        if "vault_path" in node:
            assert not node["vault_path"].startswith("/")
            assert ":" not in node["vault_path"]


async def test_another_companys_graph_is_not_reachable(vault, session_factory) -> None:
    result = await linked_vault_graph(vault, session_factory)
    assert result["nodes"]

    other = uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert (await graph(session_factory, other))["nodes"] == []


# ---------------------------------------------------------------------------
# The dashboard's own wiring, asserted against its source
# ---------------------------------------------------------------------------


def test_the_page_fetches_the_real_endpoint(ts_sources) -> None:
    """The route the page calls has to be the one this suite exercises."""
    assert "/memory/graph" in ts_sources["api"]
    assert "getActiveCompanyId()" in ts_sources["api"], (
        "the company is hardcoded rather than taken from the session"
    )
    assert "fetchMemoryGraph" in ts_sources["page"]


def test_the_page_does_not_render_the_built_in_fixtures(ts_sources) -> None:
    """The mock graph must not be the production source any more.

    The fixtures still exist for demos, reachable through ``loadDemoData()``, but
    the page never calls it — a canvas of invented notes is worse than an empty
    one, because it reads as a working graph.
    """
    assert "loadDemoData" not in ts_sources["page"]
    assert "INITIAL_NODES" not in ts_sources["page"]
    assert "calculateInitialData" in ts_sources["adapter"], (
        "the fixtures were deleted; existing demo flows depended on them"
    )
    # The store starts from an empty graph, not from the fixtures.
    assert "this.data = emptyGraphData();" in ts_sources["adapter"]


def test_a_failed_fetch_does_not_fall_back_to_fixtures(ts_sources) -> None:
    """The error path reports the failure; it never substitutes fake data."""
    page = ts_sources["page"]
    assert "setLoadError" in page
    error_block = page.split("const loadGraph", 1)[1].split("useEffect", 1)[0]
    assert "loadDemoData" not in error_block
    assert "memoryGraphStore.replaceData" in error_block


def test_the_page_exposes_a_refresh(ts_sources) -> None:
    """Derive-on-read means a re-fetch is the whole staleness story."""
    assert "onClick={loadGraph}" in ts_sources["page"]


def test_clusters_come_from_the_payload(ts_sources) -> None:
    """The server derives its own clusters, including ``vault``.

    A consumer reading the hardcoded ``MEMORY_CLUSTERS`` instead would give a real
    cluster no name, no colour and no filter pill.
    """
    assert "export function graphClusters()" in ts_sources["adapter"]
    for name in (
        "GraphFilterBar",
        "GraphNodeInspector",
        "MemoryNodeSidebarPanel",
        "MemoryGraphCanvas",
        "AddMemoryNodeModal",
    ):
        source = (DASHBOARD / "components" / "graph" / f"{name}.tsx").read_text(
            encoding="utf-8"
        )
        assert "MEMORY_CLUSTERS" not in source, (
            f"{name} still reads the hardcoded cluster list"
        )


def test_the_frontend_declares_the_vault_node_fields(ts_sources) -> None:
    """``vault_path`` and ``index_status`` are optional, because dangling nodes lack them."""
    types = ts_sources["types"]
    assert "vault_path?: string;" in types
    assert "index_status?: string;" in types
