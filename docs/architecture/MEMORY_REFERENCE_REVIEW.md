# Memory reference review

Which open-source memory and orchestration projects NEXUS may learn from, and how.
This is a design note. Nothing here is imported or vendored yet.

## Ground rules

- PostgreSQL stays the canonical store. Any projection, index or graph derived from it can be rebuilt from it.
- Tenant isolation, row-level security, `ToolPolicy` and the audit chain stay authoritative. No reference project replaces or bypasses them.
- No new runtime dependency or extra database is added for memory in v1.
- "Port" means reimplementing the idea against NEXUS models. "Adopt" means using an open format as-is. Neither means copying source.

## Decisions

| Project | Useful ideas | Existing NEXUS overlap | Direct import? | Decision | Licence/provenance |
|---|---|---|---|---|---|
| Mem0 (mem0ai/mem0) | Append-only episodes, entity linking, temporal ranking, multi-signal retrieval | `MemoryRecord`, layered memory, `RetrievalService` scoring | No | Port the ideas later. No runtime import. | Record at implementation time |
| Graphiti (getzep/graphiti) | Validity windows, provenance, supersession of facts | None for validity; `MemoryRecord` has no lifecycle columns | No | Port the model later. No extra graph database in v1. | Record at implementation time |
| LangMem (langchain-ai/langmem) | Hot-path capture versus background consolidation | Chat `_remember_response` (hot path), scheduler maintenance (background) | No | Port the split. No LangGraph dependency. | Record at implementation time |
| Cognee (topoteretes/cognee) | Company Brain shape, ontology-driven memory | Knowledge and company brain services | No | Reference only. | Record at implementation time |
| JSON Canvas (obsidianmd/jsoncanvas) | Open file format for canvases | None | Format only | Adopt the open format directly when Canvas generation is built. | Open spec; confirm licence text then |
| Dataview (blacksmithgu/obsidian-dataview) | Queryable note frontmatter | Obsidian vault projection frontmatter | No | Generate compatible frontmatter. Do not require or copy the plugin. | Record at implementation time |
| Temporal samples-python (temporalio/samples-python) | Cancellation, heartbeat, retry, resumability patterns | Temporal workers already in use | No | Port the patterns for the full-rebuild workflow. | Record at implementation time |

## Provenance record for every future port

When implementation of any row above begins, record in the PR that does it:

- upstream repository
- exact commit or release consulted
- licence
- whether code was copied or independently implemented
- local modifications, if any
- attribution or NOTICE requirements

## Deferred: hard deletes

Several memory paths still delete rows (`MemoryStore`, decay and maintenance, the memory delete route).
Hard deletion is incompatible with provenance, supersession and audit replay. The schema PR that adds
lifecycle state must, before any retrieval or projection feature ships:

- add an explicit lifecycle status to memory rows
- archive or supersede rows instead of deleting them
- exclude archived and superseded rows in SQL, in every retrieval path, not in Python after the fact

Until then, deletion behaviour is unchanged. This PR makes no schema change beyond row-level security.
