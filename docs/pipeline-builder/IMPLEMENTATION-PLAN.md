# Pipeline Builder — Implementation Plan (reactflow rebuild)

Goal: replace the hand-rolled SVG canvas with a `reactflow` v11 builder that behaves
like the OpenCompany reference, driven by our 164-node backend registry.

## Steps

### 1. Install
- `npm install reactflow` in `dashboard/` (v11.x).
- Import styles once: `import 'reactflow/dist/style.css'`.

### 2. Node type components — `builder/nodeTypes.tsx`
- One memoized component per visual kind: `TriggerNode`, `AgentNode`, `ActionNode`
  (generic square), driven by node `category`.
- `nodeTypes` map passed to `<ReactFlow>`.
- Each node renders:
  - a colored accent + category icon + label + subtitle (category / agent),
  - a target `<Handle>` on the left (hidden for triggers),
  - a source `<Handle>` on the right.
- `node.data` carries `{ label, category, icon, color, nodeId, params }`.
- `CATEGORY_COLORS` / `CATEGORY_ICONS` map the 29 categories to colors/glyphs
  (reuse the maps already in the SVG builder).

### 3. Palette — `builder/NodePalette.tsx`
- Fetch `GET /api/v1/nodes` once; cache items.
- Search box + category `<select>` (counts per category).
- Each row is `draggable`; `onDragStart` sets
  `dataTransfer['application/reactflow'] = JSON.stringify(node)`.
- Also expose a small set of built-in pipeline controls (trigger/start) at the top.

### 4. Config panel — `builder/NodeConfigPanel.tsx`
- Opens when a node is selected (or double-clicked).
- Renders the node's `inputs[]` as form controls (switch on `type`):
  - `string` → text input; `number` → number input; `boolean` → checkbox;
    `json` → textarea (parsed on blur); `file` → file path text; `credential` →
    credential picker (text for now); default → text.
- Also edits the node label.
- Writes values into `node.data.params` via `setNodes`.

### 5. Canvas host — `PipelineBuilderCanvas.tsx`
- `<ReactFlowProvider>` wrapper.
- `useNodesState` / `useEdgesState`.
- `<ReactFlow>` configured to mirror the reference: `connectionMode=Loose`,
  `snapToGrid`, `snapGrid=[20,20]`, `defaultEdgeOptions={type:'smoothstep'}`,
  `proOptions={hideAttribution:true}`, `<Background>` dots, `<Controls>`, `<MiniMap>`.
- `onConnect` with `isValidConnection` (no self-loops, no duplicate edges).
- `onDrop` / `onDragOver` for palette drops using `reactFlowInstance.project()`.
- Toolbar: pipeline name, save, run, delete-selected, fit view.
- Seed from `pipeline.canvas_nodes/edges` if present, else from `stages`, else a
  single trigger node.

### 6. Persistence — `Pipelines.tsx`
- On save, convert reactflow nodes/edges → `canvas_nodes`/`canvas_edges` and derive
  `stages[]`; POST (new) or PATCH (existing) to
  `/api/v1/companies/{id}/pipelines`.
- Run via `POST /api/v1/pipelines/{id}/run`, poll run status.

### 7. Verify & ship
- `cd dashboard; npx tsc --noEmit` must pass.
- Restart backend (8000) + frontend (3000, `PROXY_API=true`).
- Manually verify: palette loads 164 nodes, drag-drop adds a node, connect two nodes,
  edit params, save, reload, run.
- Commit and push each increment.

## Interaction parity checklist (vs OpenCompany)

- [ ] Drag from palette → drop on canvas creates a node at cursor
- [ ] Snap to 20px grid
- [ ] Connect output→input handles; invalid connections rejected
- [ ] Move / multi-select / delete nodes
- [ ] Per-node parameter editing from schema
- [ ] Save + reload round-trips the graph
- [ ] Run triggers backend execution
