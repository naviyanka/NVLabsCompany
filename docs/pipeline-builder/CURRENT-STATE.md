# Pipeline Builder — Current State (before reactflow rebuild)

Snapshot of what exists in the repo at the start of the reactflow rebuild.

## What we have

### Backend (production-ready)
- **164 workflow nodes** registered in `src/nexus/nodes/registry.py`, served via
  `GET /api/v1/nodes` (`src/nexus/api/routes/nodes.py`). Supports `?category=` and
  `?q=` filters, plus `GET /api/v1/nodes/categories` and
  `GET /api/v1/nodes/{id}`.
- **Node execution** endpoint `POST /api/v1/nodes/{id}/execute` — runs a node with
  params through `nexus.nodes.executor`, returns `{node_id, success, outputs, error}`,
  and writes an audit log. Returns 503 for nodes defined without an executor.
- **Pipeline CRUD**: `GET/POST/PATCH /api/v1/companies/{id}/pipelines`.
- **Pipeline run**: `POST /api/v1/pipelines/{id}/run` — Temporal-backed when
  `USE_TEMPORAL` is set, falls back to FastAPI BackgroundTasks otherwise.
- **Run status**: `GET /api/v1/companies/{id}/pipelines/{id}/runs/{runId}`.

### Frontend
- `pages/Pipelines.tsx` — page shell with views: Graph (split), Builder, Nodes,
  History, Security. "Visual Builder" and "Edit Visual" buttons launch the builder.
- `components/pipelines/PipelineBuilderCanvas.tsx` — a **hand-rolled SVG canvas**
  (drag, pan, zoom, wire, palette). Fetches real nodes from `/api/v1/nodes` for its
  palette. **This is what the rebuild replaces.**
- `components/pipelines/AddPipelineModal.tsx`, `PipelineDetailDrawer.tsx` — form-based
  create + inspect (kept).
- `pages/NodeLibrary.tsx` — the node catalog, embedded as the "Nodes" tab.
- `types/pipeline.ts` — `PipelineItem`, `PipelineStage`, `CanvasNode`, `CanvasEdge`,
  `NodeTypeDefinition`, `NODE_TYPE_CATALOG`.

## Limitations of the current SVG builder

- Custom pointer-event math for drag/pan/wire is brittle (proximity-based hit testing).
- No real connection validation (any port to any port).
- No per-node parameter editing beyond label / agent / type — the 164 nodes' rich
  `inputs` schema is not surfaced.
- No copy/paste, context menu, or multi-select.
- Not the same interaction model as the reference (n8n / OpenCompany).

## Decisions already made

- Rebuild on `reactflow` v11 (same library as OpenCompany) rather than copy-porting
  OpenCompany's builder (500KB, tightly coupled to their WebSocket protocol, node spec,
  and Zustand store — would not run in our app).
- Keep the legacy `stages[]` persistence alongside `canvas_nodes`/`canvas_edges` so the
  Graph and History views keep working.
- Node Library stays merged into the Pipelines page as the "Nodes" tab.
