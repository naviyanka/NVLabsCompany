# Pipeline Builder — Remaining Tasks

Live checklist. Completed items move to the "Done" section with a note.

## In progress / pending

### Parity with reference (follow-up)
- [ ] Connection type matrix (main/ai/file/binary compatibility) enforced in
      `isValidConnection`.
- [ ] Conditional edges (`ConditionalEdge` + operators) for branch/if nodes.
- [ ] Copy / paste of selected nodes (`useCopyPaste` equivalent).
- [ ] Node context menu (right-click: duplicate, disable).
- [ ] Editable node label inline (double-click title).
- [ ] `displayOptions.show` style conditional parameter visibility in config panel.
- [ ] Per-node run status overlay while a pipeline is executing (live from run polling).
- [ ] Fix pre-existing React "unique key prop" warning in `Pipelines` render (unrelated
      to the builder; likely duplicate/missing pipeline `id` from the backend list).

### Backend follow-up
- [ ] Persist per-node `params` through pipeline run so the executor receives them
      (verify `run_pipeline` consumes `canvas_nodes[].params`).
- [ ] Validate that all 164 nodes surface a usable `inputs[]` schema; fill gaps for
      nodes with empty inputs.
- [ ] Executor coverage: many nodes are "defined but no executor" (503). Track which
      nodes are executable vs. definition-only.

## Done

- [x] 164 nodes registered and served via `/api/v1/nodes` (backend).
- [x] Node execution endpoint with audit logging.
- [x] Pipeline CRUD + Temporal-backed run endpoint.
- [x] Node Library merged into Pipelines page as the "Nodes" tab.
- [x] Documentation folder created (`docs/pipeline-builder/`).
- [x] `reactflow` v11 installed (11.11.4).
- [x] `builder/nodeTypes.tsx` — Trigger / Agent / Action node components + `nodeTypes` map.
- [x] `builder/categories.ts` — category → color/icon/kind mapping.
- [x] `builder/NodePalette.tsx` — draggable palette from `/api/v1/nodes` (search + category,
      164 nodes across 26 categories verified in-browser).
- [x] `builder/NodeConfigPanel.tsx` — parameter renderer from node `inputs[]` schema
      (verified: ai-chat shows prompt/model/temperature controls).
- [x] Rebuilt `PipelineBuilderCanvas.tsx` on `<ReactFlowProvider>`: Background dots,
      Controls, MiniMap, snap grid [20,20], ConnectionMode.Loose, drag-drop + click-to-add,
      connection validation (no self-loop / no duplicate edge).
- [x] Save → `POST/PATCH /api/v1/companies/{id}/pipelines` (canvas_nodes/edges + derived
      stages) via the unchanged `onSave` contract in `Pipelines.tsx`.
- [x] Run → `POST /api/v1/pipelines/{id}/run` with run-status polling (existing wiring).
- [x] `tsc --noEmit` clean; in-browser smoke test passed (palette loads, add node, config
      panel renders schema).
- [x] Real per-node lucide icons (`builder/NodeIcon.tsx`) resolved from the backend `icon`
      field (kebab→PascalCase lookup in lucide-react `icons`, category fallback), matching
      the reference repo's backend-driven icon approach. Verified: brain/eye/mic/tag/file-text.
- [x] Node deletion: per-node hover/selected trash button, toolbar Delete button, and
      Delete/Backspace keys (verified in-browser: 2→1 nodes).
