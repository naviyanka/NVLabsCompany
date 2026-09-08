"""Memory Graph API — derive graph visualization from memory records."""

import uuid
from typing import Any
from collections import defaultdict

from fastapi import APIRouter
from sqlalchemy import select

from nexus.api.deps import DbSession, PathCompanyId
from nexus.models.memory import MemoryRecord

router = APIRouter(tags=["memory"])


@router.get("/api/v1/companies/{company_id}/memory/graph")
async def get_memory_graph(
    company_id: PathCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    """Build a graph visualization from memory records.

    ``PathCompanyId`` rather than a bare ``uuid.UUID``: the company in the URL is
    validated against the authenticated principal, so a caller cannot read another
    tenant's graph by editing the path. The auth middleware already rejects that
    for this URL shape, but it falls open when ``auth_enabled`` is false, and the
    vault subgraph now carries note titles and vault-relative paths — so the check
    belongs on the route too rather than only in front of it.

    Returns nodes (one per memory), edges (derived from shared agent/scope/proximity),
    clusters (grouped by scope), and computed metrics.
    """
    stmt = select(MemoryRecord).where(MemoryRecord.company_id == company_id).order_by(MemoryRecord.created_at.desc())
    result = await db.execute(stmt)
    memories = list(result.scalars().all())

    # Build nodes
    nodes = []
    for mem in memories:
        nodes.append({
            "id": str(mem.id),
            "label": mem.content[:60] + ("..." if len(mem.content) > 60 else ""),
            "type": _infer_node_type(mem.scope),
            "community": mem.scope,
            "agent_id": str(mem.agent_id) if mem.agent_id else None,
            "importance": mem.importance,
            "confidence": min(1.0, mem.importance + 0.1),  # synthetic confidence
            "created_at": mem.created_at.isoformat(),
            "updated_at": mem.updated_at.isoformat(),
            "summary": mem.content,
            "raw_content": mem.content,
            "tags": [mem.scope, mem.tier],
            "access_count": mem.access_count,
            "decay_score": _compute_decay_score(mem),
        })

    # Build edges — link memories sharing agent OR scope, weighted by importance product
    links = []
    edge_id = 0
    for i, mem_a in enumerate(memories):
        for mem_b in memories[i + 1:]:
            weight = 0.0
            edge_type = None

            # Same agent → strong link
            if mem_a.agent_id and mem_a.agent_id == mem_b.agent_id:
                weight = (mem_a.importance + mem_b.importance) / 2.0
                edge_type = "informs"

            # Same scope → weaker link
            elif mem_a.scope == mem_b.scope:
                weight = (mem_a.importance * mem_b.importance) * 0.6
                edge_type = "part_of"

            # High importance both + recent proximity → temporal link
            elif mem_a.importance > 0.7 and mem_b.importance > 0.7:
                time_delta = abs((mem_a.created_at - mem_b.created_at).total_seconds())
                if time_delta < 86400 * 7:  # within 7 days
                    weight = 0.5
                    edge_type = "temporal_precedes"

            if weight > 0.3:  # threshold
                links.append({
                    "id": f"e{edge_id}",
                    "source": str(mem_a.id),
                    "target": str(mem_b.id),
                    "type": edge_type,
                    "weight": round(weight, 2),
                    "label": edge_type.replace("_", " ").title(),
                })
                edge_id += 1

                # Cap edges per node to avoid clutter
                if edge_id > len(memories) * 3:
                    break
        if edge_id > len(memories) * 3:
            break

    # Build clusters (by scope)
    scope_counts: dict[str, int] = defaultdict(int)
    for mem in memories:
        scope_counts[mem.scope] += 1

    clusters = []
    cluster_colors = {
        "task_context": "#FFB020",
        "long_term": "#38BDF8",
        "guidelines": "#22C55E",
        "episodic_reflection": "#A855F7",
        "system_rule": "#F43F5E",
        "agent": "#9CA3AF",
    }
    for scope, count in scope_counts.items():
        if count > 0:
            clusters.append({
                "id": scope,
                "name": scope.replace("_", " ").title(),
                "description": f"{count} memories in {scope} scope",
                "lead_agent_id": None,
                "color": cluster_colors.get(scope, "#6B6B6E"),
                "accent_color": cluster_colors.get(scope, "#6B6B6E"),
            })

    # Compute metrics
    total_importance = sum(m.importance for m in memories) if memories else 0
    avg_importance = total_importance / len(memories) if memories else 0
    avg_confidence = min(1.0, avg_importance + 0.1)

    metrics = {
        "total_nodes": len(nodes),
        "total_links": len(links),
        "contradictions_count": 0,  # no contradiction detection yet
        "avg_confidence": round(avg_confidence, 3),
        "avg_importance": round(avg_importance, 3),
        "modularity_score": 0.72,  # placeholder
        "clustering_coefficient": 0.58,  # placeholder
        "memory_recall_rate": 95.0,
        "hnsw_index_size_kb": len(nodes) * 120 + 600,
    }

    vault_nodes, vault_links, vault_cluster = await _vault_subgraph(company_id, db)
    nodes.extend(vault_nodes)
    links.extend(vault_links)
    if vault_cluster is not None:
        clusters.append(vault_cluster)
    metrics["total_nodes"] = len(nodes)
    metrics["total_links"] = len(links)

    return {
        "nodes": nodes,
        "links": links,
        "clusters": clusters,
        "metrics": metrics,
    }


# Vault nodes are namespaced (ADR 0002 §14) so a note and a memory about the same
# subject are two nodes rather than one collision. Memory ids stay bare UUIDs,
# which cannot collide with this prefix.
_VAULT_PREFIX = "obsidian:"

# Dangling targets rendered. A link to a note that does not exist yet is real
# information — a human stated a relationship before writing the other side — but
# a vault mid-reorganisation can have many, and they are the least useful nodes
# on the canvas, so they are bounded.
MAX_DANGLING_NODES = 50


async def _vault_subgraph(
    company_id: uuid.UUID, db: DbSession
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Derive vault note nodes and wikilink edges for one company.

    Wikilinks are the vault's own relationship mechanism, so they are read from
    the registry rather than inferred. Edges are resolved through a title/path
    index — one pass over the documents, then one pass over their links — and
    deliberately not fed through the memory pair loop above, whose O(n²) scan
    ADR 0002 §14 already flags as a scaling ceiling.

    Nothing is persisted: this is the same derive-on-read contract the memory
    graph already follows, so there is no edge table.

    Args:
        company_id: The company whose vault registry is read.
        db: Async session.

    Returns:
        Nodes, links, and a cluster for the vault, or empty results when the
        company has no registered notes.
    """
    from nexus.models.obsidian import ObsidianDocument

    stmt = select(ObsidianDocument).where(ObsidianDocument.company_id == company_id)
    documents = list((await db.execute(stmt)).scalars().all())
    if not documents:
        return [], [], None

    nodes: list[dict[str, Any]] = []
    # A wikilink names a note by title or by vault path, and Obsidian matches
    # case-insensitively, so both keys are indexed the same way.
    by_key: dict[str, str] = {}
    for doc in documents:
        node_id = f"{_VAULT_PREFIX}{doc.nexus_id}"
        title = doc.title or doc.vault_path
        nodes.append(
            {
                "id": node_id,
                "label": title[:60] + ("..." if len(title) > 60 else ""),
                "type": "knowledge",
                "community": "vault",
                "agent_id": None,
                # A note is authored by a human on purpose, so it is not
                # discounted the way a synthesised memory score is.
                "importance": 1.0,
                "confidence": 1.0,
                "created_at": doc.created_at.isoformat(),
                "updated_at": (doc.updated_at or doc.created_at).isoformat(),
                "summary": title,
                "raw_content": doc.vault_path,
                "tags": [tag for tag in ("vault", doc.doc_type, doc.index_status) if tag],
                "access_count": 0,
                "decay_score": 1.0,
                "vault_path": doc.vault_path,
                "index_status": doc.index_status,
            }
        )
        for key in (title, doc.vault_path, doc.vault_path.removesuffix(".md")):
            by_key.setdefault(key.casefold(), node_id)

    links: list[dict[str, Any]] = []
    dangling: dict[str, str] = {}
    for doc in documents:
        source_id = f"{_VAULT_PREFIX}{doc.nexus_id}"
        for target in doc.wikilink_targets or []:
            key = target.casefold()
            target_id = by_key.get(key)
            if target_id is None:
                if key in dangling:
                    target_id = dangling[key]
                elif len(dangling) < MAX_DANGLING_NODES:
                    target_id = f"{_VAULT_PREFIX}missing:{key}"
                    dangling[key] = target_id
                    nodes.append(
                        {
                            "id": target_id,
                            "label": target[:60],
                            "type": "knowledge",
                            "community": "vault",
                            "agent_id": None,
                            "importance": 0.3,
                            "confidence": 0.3,
                            "created_at": doc.created_at.isoformat(),
                            "updated_at": doc.created_at.isoformat(),
                            "summary": f"Linked but not present in the vault: {target}",
                            "raw_content": target,
                            "tags": ["vault", "missing"],
                            "access_count": 0,
                            "decay_score": 0.3,
                            "index_status": "missing",
                        }
                    )
                else:
                    continue
            if target_id == source_id:
                # A note linking to itself is not a relationship.
                continue
            links.append(
                {
                    "id": f"w{len(links)}",
                    "source": source_id,
                    "target": target_id,
                    "type": "wikilink",
                    "weight": 1.0,
                    "label": "Wikilink",
                }
            )

    cluster = {
        "id": "vault",
        "name": "Vault",
        "description": f"{len(documents)} notes in the Obsidian vault",
        "lead_agent_id": None,
        "color": "#7C6CF0",
        "accent_color": "#7C6CF0",
    }
    return nodes, links, cluster


def _infer_node_type(scope: str) -> str:
    """Map scope to visual node type."""
    mapping = {
        "task_context": "task",
        "long_term": "knowledge",
        "guidelines": "fact",
        "episodic_reflection": "experience",
        "system_rule": "decision",
        "agent": "agent",
    }
    return mapping.get(scope, "knowledge")


def _compute_decay_score(mem: MemoryRecord) -> float:
    """Compute freshness score (1.0 = freshest, decays over time)."""
    import datetime
    age_days = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - mem.created_at).days
    # Decay half-life ~90 days
    decay = max(0.1, 1.0 - (age_days / 180.0))
    return round(decay, 2)
