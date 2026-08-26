# Pipeline Builder — Architecture

This document is the reference map for the n8n-style visual Pipeline Builder in
NVLabsCompany. It captures how the **OpenCompany** reference implementation works
(the behavior we are matching) and how our rebuild maps onto it.

---

## 1. Reference implementation (OpenCompany)

Location analyzed: `temp_repos/OpenCompany/client/src/`.
Library: **`reactflow` v11** (imports `from 'reactflow'`, `import 'reactflow/dist/style.css'`).
NOT `@xyflow/react` (that is reactflow v12, a different package name).

### 1.1 Canvas host — `Dashboard.tsx`

- Wrapped in `<ReactFlowProvider>` so hooks like `useReactFlow`, `useNodesState`,
  `useEdgesState` work inside child components.
- Uses `useNodesState(initialNodes)` and `useEdgesState(initialEdges)`.
- `<ReactFlow>` props observed:
  - `connectionMode={ConnectionMode.Loose}` — either handle end can start a connection
  - `snapToGrid` + `snapGrid={[20, 20]}`
  - `defaultEdgeOptions={{ type: 'step' }}`
  - `connectionLineType={ConnectionLineType.Step}`
  - `selectionMode={SelectionMode.Partial}`
  - `panOnDrag`, `zoomOnScroll`
  - `proOptions={{ hideAttribution: true }}`
  - renders `<Controls />` only; the dotted grid is drawn with CSS, not `<Background>`.

### 1.2 Node type registry

```
COMPONENT_BY_KIND = {
  start:   StartNode,
  trigger: TriggerNode,
  agent:   AIAgentNode,
  chat:    AIAgentNode,
  model:   SquareNode,
  square:  SquareNode,
  tool:    SquareNode,
  generic: SquareNode,
}
```

Fallback resolution order:
1. `teamMonitor` flag → `TeamMonitorNode`
2. `uiHints.isMasterSkillEditor` → `ToolkitNode`
3. otherwise → `SquareNode`

`edgeTypes = { conditional: ConditionalEdge, smoothstep: StepEdge }`.

### 1.3 Node components

- Each is a memoized `React.FC<NodeProps>`.
- Reads its spec with `useNodeSpec(type)`.
- Renders `<Handle>` elements from `spec.handles`:
  `{ name, kind: 'input' | 'output', position, offset?, label?, role? }`.
  - handle `id === name`
  - `type='target'` for inputs, `type='source'` for outputs.
- `node.data` holds ONLY `{ label, disabled? }`. Node parameter values live in a
  DB side-table, not on the node data.

### 1.4 NodeSpec wire shape

```
{
  type, displayName, icon, group[], description?, subtitle?, version,
  inputs?: JsonSchema,   // parameters
  outputs?: JsonSchema,
  credentials?, uiHints?, color?, componentKind?,
  handles?, hideOutputHandle?, hideInputHandle?, visibility?
}
```

- `nodeSpecToDescription.ts` adapts `NodeSpec` → `INodeTypeDescription`.
- `ParameterRenderer.tsx` is a `switch(parameter.type)` covering: string, number,
  boolean, select, options, slider, file, array, collection, fixedCollection,
  json, code, dateTime.
- `shouldShowParameter` implements `displayOptions.show` conditional visibility.

### 1.5 Drag & drop

- Palette item sets `dataTransfer['application/reactflow'] = JSON.stringify({ type, data: defaults })`.
- `onDrop` computes canvas position via `reactFlowInstance.project()`, snaps to grid,
  assigns a unique id/label.

### 1.6 State & persistence

- Zustand `useAppStore`: `currentWorkflow` edit buffer + per-workflow `workflowUIStates`
  (the n8n dirty-buffer pattern).
- TanStack Query for server data.
- REST: `GET/POST/DELETE /api/database/workflows`.
- **Our project uses a different backend** — FastAPI `/api/v1/pipelines`.

### 1.7 Connection validation

- `onConnect` → `isValidConnection` → `areTypesCompatible`.
- Type matrix (`NodeConnectionType`): `main` is universal, `ai → main/ai`,
  `file ↔ binary`.

### 1.8 Extras

`useCopyPaste`, `NodeContextMenu`, `EditableNodeLabel`, `ConditionalEdge` with
`EdgeCondition` operators.

---

## 2. Our mapping (NVLabsCompany)

| OpenCompany concept        | NVLabsCompany equivalent                                            |
|----------------------------|---------------------------------------------------------------------|
| `reactflow` v11            | `reactflow` v11 (same package)                                      |
| NodeSpec registry          | `GET /api/v1/nodes` → `NodeRegistry.to_dict()` (164 nodes)          |
| `spec.inputs` (params)     | node `inputs[]`: `{name,type,required,default,description}`         |
| `spec.handles`             | derived: 1 input handle (unless trigger) + 1 output handle          |
| `componentKind`            | derived from node `category` (ai/trigger/data/... )                |
| DB workflow REST           | `GET/POST/PATCH /api/v1/companies/{id}/pipelines`                   |
| run workflow               | `POST /api/v1/pipelines/{id}/run` (Temporal-backed, BG fallback)   |
| Zustand edit buffer        | local React state in `PipelineBuilderCanvas` (single-workflow edit)|
| `ParameterRenderer`        | `NodeConfigPanel` — switch over our simpler input `type` set        |

### 2.1 Node payload from our backend

`GET /api/v1/nodes` returns:

```
{
  items: [
    {
      id, name, description, category, icon,
      inputs:  [{ name, type, required, default, description }],
      outputs: [{ name, type, description }],
      credentials: [string],
      version
    }
  ],
  total, categories
}
```

Our input `type` values: `string | number | boolean | json | file | credential`.
The config panel renders a control per type; unknown types fall back to a text field.

### 2.2 Persistence shape

A pipeline stores both the legacy `stages[]` (for the existing list/graph views) and
the visual graph in `canvas_nodes` / `canvas_edges` so the SVG-era data keeps working:

- `canvas_nodes`: `[{ id, type, label, x, y, agent?, params? }]`
- `canvas_edges`: `[{ id, from, to }]`

On save we also derive `stages[]` from the nodes for backward compatibility with the
Graph / History views on the Pipelines page.

---

## 3. Files

| File                                                          | Role                                       |
|---------------------------------------------------------------|--------------------------------------------|
| `dashboard/src/components/pipelines/builder/nodeTypes.tsx`    | custom reactflow node components + mapping |
| `dashboard/src/components/pipelines/builder/NodePalette.tsx`  | draggable palette fed by `/api/v1/nodes`   |
| `dashboard/src/components/pipelines/builder/NodeConfigPanel.tsx` | parameter renderer for a selected node  |
| `dashboard/src/components/pipelines/PipelineBuilderCanvas.tsx` | ReactFlow host, save/run wiring            |
| `dashboard/src/pages/Pipelines.tsx`                           | page shell, builder launch + persistence   |
