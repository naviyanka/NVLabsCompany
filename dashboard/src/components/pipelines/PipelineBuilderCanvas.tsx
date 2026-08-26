/**
 * PipelineBuilderCanvas — n8n-style visual pipeline builder built on reactflow v11.
 *
 * Mirrors the OpenCompany reference behavior: ReactFlowProvider host, custom node
 * components, drag-and-drop palette fed by the backend node registry, per-node
 * parameter editing from the node input schema, connection validation, snap grid,
 * Background/Controls/MiniMap. Persists via the same onSave(nodes, edges, name)
 * contract used by the previous SVG builder, so Pipelines.tsx is unchanged.
 */

import { Button } from '@/components/common/Button';
import type { CanvasEdge, CanvasNode, CanvasNodeType, PipelineItem } from '@/types/pipeline';
import { Save, Trash2, X } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node
} from 'reactflow';
import 'reactflow/dist/style.css';
import { categoryColor, categoryIcon, kindForCategory } from './builder/categories';
import { NodeConfigPanel, type SelectedNode } from './builder/NodeConfigPanel';
import { NodePalette, type PaletteDragPayload } from './builder/NodePalette';
import { nodeTypes, type BuilderNodeData } from './builder/nodeTypes';

const GRID = 20;
const DND_MIME = 'application/reactflow';

type RFNode = Node<BuilderNodeData>;

let idCounter = 0;
function nextId(): string {
  idCounter += 1;
  return `node-${Date.now().toString(36)}-${idCounter}`;
}

/* ── seed reactflow graph from a pipeline ── */
function seedGraph(pipeline?: PipelineItem | null): { nodes: RFNode[]; edges: Edge[] } {
  // 1. Existing canvas graph
  if (pipeline?.canvas_nodes?.length) {
    const nodes: RFNode[] = pipeline.canvas_nodes.map((n) => ({
      id: n.id,
      type: kindForCategory(n.category),
      position: { x: n.x, y: n.y },
      data: {
        label: n.label,
        category: n.category,
        icon: categoryIcon(n.category),
        color: categoryColor(n.category),
        nodeId: n.nodeId,
        agent: n.agent,
        params: n.params ?? {},
      },
    }));
    const edges: Edge[] = (pipeline.canvas_edges ?? []).map((e) => ({
      id: e.id,
      source: e.from,
      target: e.to,
      type: 'smoothstep',
    }));
    return { nodes, edges };
  }

  // 2. Legacy stages → sequential nodes
  if (pipeline?.stages?.length) {
    const nodes: RFNode[] = pipeline.stages.map((s, i) => ({
      id: s.id,
      type: i === 0 ? 'trigger' : 'action',
      position: { x: 80 + i * 280, y: 200 },
      data: {
        label: s.name,
        category: i === 0 ? 'trigger' : 'utility',
        icon: categoryIcon(i === 0 ? 'trigger' : 'utility'),
        color: categoryColor(i === 0 ? 'trigger' : 'utility'),
        agent: s.assignedAgent,
        params: {},
      },
    }));
    const edges: Edge[] = pipeline.stages.slice(0, -1).map((s, i) => ({
      id: `e-${s.id}-${pipeline.stages[i + 1]!.id}`,
      source: s.id,
      target: pipeline.stages[i + 1]!.id,
      type: 'smoothstep',
    }));
    return { nodes, edges };
  }

  // 3. Empty → single trigger
  return {
    nodes: [
      {
        id: 'trigger-1',
        type: 'trigger',
        position: { x: 120, y: 200 },
        data: {
          label: 'Trigger',
          category: 'trigger',
          icon: categoryIcon('trigger'),
          color: categoryColor('trigger'),
          params: { event: 'manual' },
        },
      },
    ],
    edges: [],
  };
}

interface PipelineBuilderCanvasProps {
  pipeline?: PipelineItem | null;
  onSave: (nodes: CanvasNode[], edges: CanvasEdge[], name: string) => void;
  onClose: () => void;
}

function BuilderInner({ pipeline, onSave, onClose }: PipelineBuilderCanvasProps) {
  const seed = useMemo(() => seedGraph(pipeline), [pipeline]);
  const [nodes, setNodes, onNodesChange] = useNodesState(seed.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(seed.edges);
  const [pipelineName, setPipelineName] = useState(pipeline?.name || 'Untitled Pipeline');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const { project, deleteElements } = useReactFlow();

  const deleteSelected = useCallback(() => {
    const selNodes = nodes.filter((n) => n.selected || n.id === selectedId).map((n) => ({ id: n.id }));
    const selEdges = edges.filter((e) => e.selected).map((e) => ({ id: e.id }));
    if (selNodes.length || selEdges.length) {
      void deleteElements({ nodes: selNodes, edges: selEdges });
      setSelectedId(null);
    }
  }, [nodes, edges, deleteElements, selectedId]);

  /* ── connection handling ── */
  const isValidConnection = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return false;
      if (c.source === c.target) return false; // no self-loop
      const dup = edges.some((e) => e.source === c.source && e.target === c.target);
      return !dup;
    },
    [edges],
  );

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, type: 'smoothstep' }, eds)),
    [setEdges],
  );

  /* ── drag & drop from palette ── */
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const spawnNode = useCallback(
    (payload: PaletteDragPayload, position: { x: number; y: number }) => {
      const id = nextId();
      const defaults: Record<string, unknown> = {};
      for (const inp of payload.inputs ?? []) {
        if (inp.default !== undefined && inp.default !== null) defaults[inp.name] = inp.default;
      }
      const node: RFNode = {
        id,
        type: kindForCategory(payload.category),
        position,
        data: {
          label: payload.name,
          category: payload.category,
          icon: payload.icon || categoryIcon(payload.category),
          color: categoryColor(payload.category),
          nodeId: payload.nodeId.startsWith('builtin.') ? undefined : payload.nodeId,
          params: defaults,
        },
      };
      // stash the input schema on the node so the config panel can render it
      inputSchemaRef.current[id] = payload.inputs ?? [];
      setNodes((nds) => nds.concat(node));
      setSelectedId(id);
    },
    [setNodes],
  );

  // input schema per node id (not persisted; re-derived from palette payload)
  const inputSchemaRef = useRef<Record<string, PaletteDragPayload['inputs']>>({});

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData(DND_MIME);
      if (!raw) return;
      let payload: PaletteDragPayload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      const bounds = wrapperRef.current?.getBoundingClientRect();
      const position = project({
        x: e.clientX - (bounds?.left ?? 0),
        y: e.clientY - (bounds?.top ?? 0),
      });
      spawnNode(payload, position);
    },
    [project, spawnNode],
  );

  const onPaletteAdd = useCallback(
    (payload: PaletteDragPayload) => {
      // Click-to-add drops near the viewport center.
      const bounds = wrapperRef.current?.getBoundingClientRect();
      const position = project({
        x: (bounds?.width ?? 800) / 2 + (Math.random() * 60 - 30),
        y: (bounds?.height ?? 600) / 2 + (Math.random() * 60 - 30),
      });
      spawnNode(payload, position);
    },
    [project, spawnNode],
  );

  /* ── selection & config panel ── */
  const selectedNode: SelectedNode | null = useMemo(() => {
    if (!selectedId) return null;
    const n = nodes.find((x) => x.id === selectedId);
    if (!n) return null;
    return { id: n.id, data: n.data, inputs: inputSchemaRef.current[n.id] };
  }, [selectedId, nodes]);

  const onLabelChange = useCallback(
    (id: string, label: string) =>
      setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, label } } : n))),
    [setNodes],
  );

  const onParamChange = useCallback(
    (id: string, name: string, value: unknown) =>
      setNodes((nds) =>
        nds.map((n) =>
          n.id === id
            ? { ...n, data: { ...n.data, params: { ...(n.data.params ?? {}), [name]: value } } }
            : n,
        ),
      ),
    [setNodes],
  );

  /* ── save: convert reactflow graph → CanvasNode/CanvasEdge ── */
  const handleSave = useCallback(() => {
    const canvasNodes: CanvasNode[] = nodes.map((n) => ({
      id: n.id,
      type: (n.data.category as CanvasNodeType) ?? 'agent_task',
      label: n.data.label,
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
      agent: n.data.agent,
      nodeId: n.data.nodeId,
      category: n.data.category,
      params: n.data.params,
    }));
    const canvasEdges: CanvasEdge[] = edges.map((e) => ({
      id: e.id,
      from: e.source,
      to: e.target,
    }));
    onSave(canvasNodes, canvasEdges, pipelineName);
  }, [nodes, edges, pipelineName, onSave]);

  return (
    <div className="fixed inset-0 z-50 bg-[#08080A] flex flex-col">
      {/* toolbar */}
      <div className="h-12 bg-[#0C0C0E] border-b border-white/[0.08] flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] cursor-pointer"
          >
            <X size={18} />
          </button>
          <div className="w-px h-5 bg-white/[0.1]" />
          <input
            type="text"
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            className="bg-transparent text-sm font-medium text-white border-none outline-none w-72 placeholder-gray-500"
            placeholder="Pipeline name..."
          />
        </div>
        <div className="flex items-center gap-2">
          {selectedId && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Trash2 size={14} className="text-rose-400" />}
              onClick={deleteSelected}
            >
              Delete
            </Button>
          )}
          <Button variant="primary" size="sm" icon={<Save size={14} />} onClick={handleSave}>
            Save Pipeline
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* palette */}
        <div className="w-64 shrink-0 bg-[#0C0C0E] border-r border-white/[0.08] overflow-y-auto">
          <NodePalette onAdd={onPaletteAdd} />
        </div>

        {/* canvas */}
        <div className="flex-1 relative" ref={wrapperRef}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            nodeTypes={nodeTypes}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            snapToGrid
            snapGrid={[GRID, GRID]}
            defaultEdgeOptions={{ type: 'smoothstep' }}
            connectionMode={ConnectionMode.Loose}
            proOptions={{ hideAttribution: true }}
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background variant={BackgroundVariant.Dots} gap={GRID} size={1} color="#2A2A2E" />
            <Controls className="!bg-[#141416] !border-white/[0.1]" />
            <MiniMap
              className="!bg-[#0C0C0E] !border !border-white/[0.1]"
              nodeColor={(n) => (n.data as BuilderNodeData)?.color || '#FFB020'}
              maskColor="rgba(0,0,0,0.6)"
            />
          </ReactFlow>

          <div className="absolute bottom-3 right-3 text-[10px] font-mono text-gray-500 bg-[#0C0C0E]/80 px-2 py-1 rounded border border-white/[0.06] select-none pointer-events-none">
            {nodes.length} nodes · {edges.length} edges
          </div>
        </div>

        {/* config panel */}
        <NodeConfigPanel
          node={selectedNode}
          onClose={() => setSelectedId(null)}
          onLabelChange={onLabelChange}
          onParamChange={onParamChange}
        />
      </div>
    </div>
  );
}

export function PipelineBuilderCanvas(props: PipelineBuilderCanvasProps) {
  return (
    <ReactFlowProvider>
      <BuilderInner {...props} />
    </ReactFlowProvider>
  );
}
