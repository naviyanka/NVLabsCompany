import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Save,
  Trash2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  MousePointer2,
  X,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import type {
  CanvasNode,
  CanvasEdge,
  CanvasNodeType,
  NodeTypeDefinition,
  PipelineItem,
} from '@/types/pipeline';
import { NODE_TYPE_CATALOG } from '@/types/pipeline';

/* ─────── constants ─────── */
const NODE_W = 200;
const NODE_H = 72;
const PORT_R = 7;
const GRID_SIZE = 20;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2.5;

const snap = (v: number) => Math.round(v / GRID_SIZE) * GRID_SIZE;

/* ─────── helpers ─────── */
function nodeColor(type: CanvasNodeType): string {
  return NODE_TYPE_CATALOG.find((n) => n.type === type)?.color ?? '#FFB020';
}
function nodeIcon(type: CanvasNodeType): string {
  return NODE_TYPE_CATALOG.find((n) => n.type === type)?.icon ?? '⬡';
}

/* ─────── component ─────── */
interface PipelineBuilderCanvasProps {
  pipeline?: PipelineItem | null;
  onSave: (nodes: CanvasNode[], edges: CanvasEdge[], name: string) => void;
  onClose: () => void;
}

export function PipelineBuilderCanvas({
  pipeline,
  onSave,
  onClose,
}: PipelineBuilderCanvasProps) {
  /* ── state ── */
  const [nodes, setNodes] = useState<CanvasNode[]>(() => {
    if (pipeline?.canvas_nodes?.length) return pipeline.canvas_nodes;
    // Seed from existing stages
    if (pipeline?.stages?.length) {
      return pipeline.stages.map((s, i) => ({
        id: s.id,
        type: (i === 0 ? 'trigger' : 'agent_task') as CanvasNodeType,
        label: s.name,
        x: 80 + i * 280,
        y: 200,
        agent: s.assignedAgent,
      }));
    }
    return [
      { id: 'start-1', type: 'trigger' as CanvasNodeType, label: 'Git Push Trigger', x: 80, y: 220, agent: 'System' },
    ];
  });

  const [edges, setEdges] = useState<CanvasEdge[]>(() => {
    if (pipeline?.canvas_edges?.length) return pipeline.canvas_edges;
    // Auto-connect sequential stages
    if (pipeline?.stages && pipeline.stages.length > 1) {
      const stgs = pipeline.stages;
      return stgs.slice(0, -1).map((s, i) => ({
        id: `e-${s.id}-${stgs[i + 1]!.id}`,
        from: s.id,
        to: stgs[i + 1]!.id,
      }));
    }
    return [];
  });

  const [pipelineName, setPipelineName] = useState(pipeline?.name || 'Untitled Pipeline');

  // Camera
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);

  // Interaction state
  const [dragging, setDragging] = useState<{ nodeId: string; offsetX: number; offsetY: number } | null>(null);
  const [panning, setPanning] = useState<{ startX: number; startY: number; panX: number; panY: number } | null>(null);
  const [wiring, setWiring] = useState<{ fromId: string; mouseX: number; mouseY: number } | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [editingNode, setEditingNode] = useState<CanvasNode | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);

  /* ── screen ↔ canvas coords ── */
  const screenToCanvas = useCallback(
    (sx: number, sy: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return { x: sx, y: sy };
      return {
        x: (sx - rect.left - pan.x) / zoom,
        y: (sy - rect.top - pan.y) / zoom,
      };
    },
    [pan, zoom],
  );

  /* ── zoom ── */
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * factor)));
    },
    [],
  );

  const zoomIn = () => setZoom((z) => Math.min(MAX_ZOOM, z * 1.2));
  const zoomOut = () => setZoom((z) => Math.max(MIN_ZOOM, z / 1.2));
  const fitView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  /* ── pointer events (unified for drag, pan, wire) ── */
  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      // Only left button
      if (e.button !== 0) return;
      const target = e.target as SVGElement;

      // Port click → start/finish wiring
      const portNodeId = target.getAttribute('data-port-node') || target.closest('[data-port-node]')?.getAttribute('data-port-node');

      if (wiring) {
        // If already wiring and clicked anywhere, check for target node
        const targetNodeId = findTargetNodeAt(e.clientX, e.clientY, wiring.fromId);
        if (targetNodeId && targetNodeId !== wiring.fromId) {
          const exists = edges.some((ed) => ed.from === wiring.fromId && ed.to === targetNodeId);
          if (!exists) {
            setEdges((prev) => [
              ...prev,
              { id: `e-${Date.now()}`, from: wiring.fromId, to: targetNodeId },
            ]);
          }
        }
        setWiring(null);
        return;
      }

      if (portNodeId) {
        const pt = screenToCanvas(e.clientX, e.clientY);
        setWiring({ fromId: portNodeId, mouseX: pt.x, mouseY: pt.y });
        e.stopPropagation();
        return;
      }

      // Node body click → start drag
      const nodeId = target.closest('[data-node-id]')?.getAttribute('data-node-id');
      if (nodeId) {
        const node = nodes.find((n) => n.id === nodeId);
        if (!node) return;
        const pt = screenToCanvas(e.clientX, e.clientY);
        setDragging({ nodeId, offsetX: pt.x - node.x, offsetY: pt.y - node.y });
        setSelectedNodeId(nodeId);
        (e.target as Element).setPointerCapture?.(e.pointerId);
        return;
      }

      // Canvas background → start panning
      setPanning({ startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y });
      (e.target as Element).setPointerCapture?.(e.pointerId);
    },
    [nodes, pan, screenToCanvas, wiring, edges],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (dragging) {
        const pt = screenToCanvas(e.clientX, e.clientY);
        setNodes((prev) =>
          prev.map((n) =>
            n.id === dragging.nodeId
              ? { ...n, x: snap(pt.x - dragging.offsetX), y: snap(pt.y - dragging.offsetY) }
              : n,
          ),
        );
        return;
      }
      if (panning) {
        setPan({
          x: panning.panX + (e.clientX - panning.startX),
          y: panning.panY + (e.clientY - panning.startY),
        });
        return;
      }
      if (wiring) {
        const pt = screenToCanvas(e.clientX, e.clientY);
        setWiring((w) => (w ? { ...w, mouseX: pt.x, mouseY: pt.y } : null));
      }
    },
    [dragging, panning, wiring, screenToCanvas],
  );

  // Find target node under cursor using DOM + Bounding Box + Proximity
  const findTargetNodeAt = useCallback(
    (clientX: number, clientY: number, sourceNodeId: string): string | null => {
      // 1. DOM hit check
      const els = document.elementsFromPoint(clientX, clientY);
      for (const el of els) {
        const pn = el.getAttribute('data-port-node');
        if (pn && pn !== sourceNodeId) return pn;
        const nid = el.closest('[data-node-id]')?.getAttribute('data-node-id');
        if (nid && nid !== sourceNodeId) return nid;
      }

      // 2. Bounding Box & Proximity check in canvas coordinates
      const canvasPt = screenToCanvas(clientX, clientY);
      for (const node of nodes) {
        if (node.id === sourceNodeId) continue;
        
        // Node rectangle bounds (with generous 15px padding)
        if (
          canvasPt.x >= node.x - 15 &&
          canvasPt.x <= node.x + NODE_W + 15 &&
          canvasPt.y >= node.y - 15 &&
          canvasPt.y <= node.y + NODE_H + 15
        ) {
          return node.id;
        }

        // Port proximity check (radius 40px)
        const portX = node.x;
        const portY = node.y + NODE_H / 2;
        const dx = canvasPt.x - portX;
        const dy = canvasPt.y - portY;
        if (Math.sqrt(dx * dx + dy * dy) <= 40) {
          return node.id;
        }
      }
      return null;
    },
    [nodes, screenToCanvas],
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      if (wiring) {
        const targetNodeId = findTargetNodeAt(e.clientX, e.clientY, wiring.fromId);
        if (targetNodeId && targetNodeId !== wiring.fromId) {
          const exists = edges.some((ed) => ed.from === wiring.fromId && ed.to === targetNodeId);
          if (!exists) {
            setEdges((prev) => [
              ...prev,
              { id: `e-${Date.now()}`, from: wiring.fromId, to: targetNodeId },
            ]);
          }
        }
        setWiring(null);
        return;
      }
      setDragging(null);
      setPanning(null);
    },
    [wiring, edges, findTargetNodeAt],
  );

  /* ── palette drop (add node) ── */
  const addNodeFromPalette = useCallback(
    (typeDef: NodeTypeDefinition) => {
      const id = `node-${Date.now().toString(36)}`;
      // Place near center of viewport
      const cx = (-pan.x + 400) / zoom;
      const cy = (-pan.y + 300) / zoom;
      const newNode: CanvasNode = {
        id,
        type: typeDef.type,
        label: typeDef.label,
        x: snap(cx + Math.random() * 40),
        y: snap(cy + Math.random() * 40),
        agent: typeDef.defaultAgent,
      };
      setNodes((prev) => [...prev, newNode]);
      setSelectedNodeId(id);
    },
    [pan, zoom],
  );

  /* ── delete selected ── */
  const deleteSelected = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes((prev) => prev.filter((n) => n.id !== selectedNodeId));
    setEdges((prev) => prev.filter((e) => e.from !== selectedNodeId && e.to !== selectedNodeId));
    setSelectedNodeId(null);
  }, [selectedNodeId]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        // Only delete if we're not in an input
        if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;
        deleteSelected();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [deleteSelected]);

  /* ── save ── */
  const handleSave = () => {
    onSave(nodes, edges, pipelineName);
  };

  /* ── edge path helpers ── */
  const getPortPos = (node: CanvasNode, dir: 'in' | 'out') => {
    if (dir === 'in') return { x: node.x, y: node.y + NODE_H / 2 };
    return { x: node.x + NODE_W, y: node.y + NODE_H / 2 };
  };

  const edgePath = (from: CanvasNode, to: CanvasNode) => {
    const s = getPortPos(from, 'out');
    const e = getPortPos(to, 'in');
    const dx = Math.abs(e.x - s.x) * 0.5;
    return `M ${s.x} ${s.y} C ${s.x + dx} ${s.y}, ${e.x - dx} ${e.y}, ${e.x} ${e.y}`;
  };

  /* ── render ── */
  return (
    <div className="fixed inset-0 z-50 bg-[#08080A] flex flex-col">
      {/* ── Top toolbar ── */}
      <div className="h-12 bg-[#0C0C0E] border-b border-white/[0.08] flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] cursor-pointer">
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
          {/* Zoom controls */}
          <div className="flex items-center gap-1 bg-[#141416] border border-white/[0.08] rounded-[6px] px-1 py-0.5">
            <button onClick={zoomOut} className="p-1 text-gray-400 hover:text-white cursor-pointer"><ZoomOut size={14} /></button>
            <span className="text-[10px] font-mono text-gray-400 w-10 text-center">{Math.round(zoom * 100)}%</span>
            <button onClick={zoomIn} className="p-1 text-gray-400 hover:text-white cursor-pointer"><ZoomIn size={14} /></button>
            <button onClick={fitView} className="p-1 text-gray-400 hover:text-white cursor-pointer"><Maximize2 size={14} /></button>
          </div>

          <div className="w-px h-5 bg-white/[0.1]" />

          {selectedNodeId && (
            <Button variant="secondary" size="xs" icon={<Trash2 size={13} className="text-rose-400" />} onClick={deleteSelected}>
              Delete
            </Button>
          )}

          <Button variant="primary" size="sm" icon={<Save size={14} />} onClick={handleSave}>
            Save Pipeline
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left: Node Type Palette ── */}
        <div className={`${paletteOpen ? 'w-56' : 'w-0'} shrink-0 bg-[#0C0C0E] border-r border-white/[0.08] overflow-y-auto transition-all`}>
          {paletteOpen && (
            <div className="p-3 space-y-2">
              <div className="text-[10px] font-mono text-[#FFB020] uppercase font-bold tracking-wider mb-2">
                Node Types — Drag to Add
              </div>
              {NODE_TYPE_CATALOG.map((def) => (
                <button
                  key={def.type}
                  onClick={() => addNodeFromPalette(def)}
                  className="w-full text-left p-2.5 rounded-[8px] border border-white/[0.06] bg-[#141416] hover:border-white/[0.2] hover:bg-[#1A1A1E] transition-all cursor-pointer group"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="w-7 h-7 rounded-[6px] flex items-center justify-center text-sm border"
                      style={{ borderColor: def.color + '60', background: def.color + '18' }}
                    >
                      {def.icon}
                    </span>
                    <div>
                      <div className="text-xs font-medium text-white group-hover:text-[#FFB020] transition-colors">
                        {def.label}
                      </div>
                      <div className="text-[10px] text-gray-500 leading-tight">{def.description}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Toggle palette ── */}
        <button
          onClick={() => setPaletteOpen(!paletteOpen)}
          className="absolute left-0 bottom-4 z-10 ml-1 p-1.5 bg-[#1A1A1E] border border-white/[0.1] rounded-r-lg text-gray-400 hover:text-white cursor-pointer"
          style={{ left: paletteOpen ? '14rem' : 0 }}
        >
          {paletteOpen ? '◀' : '▶'}
        </button>

        {/* ── Canvas ── */}
        <div className="flex-1 relative overflow-hidden">
          {/* Minimap hint */}
          <div className="absolute top-3 left-3 z-10 text-[10px] font-mono text-gray-500 bg-[#0C0C0E]/80 px-2 py-1 rounded border border-white/[0.06] pointer-events-none select-none">
            <MousePointer2 size={10} className="inline mr-1" />
            Drag nodes · Connect ports · Scroll to zoom · Drag canvas to pan
          </div>

          <svg
            ref={svgRef}
            className="w-full h-full"
            style={{ cursor: panning ? 'grabbing' : dragging ? 'move' : 'default' }}
            onWheel={handleWheel}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          >
            {/* Grid pattern */}
            <defs>
              <pattern id="grid-small" width={GRID_SIZE * zoom} height={GRID_SIZE * zoom} patternUnits="userSpaceOnUse" x={pan.x % (GRID_SIZE * zoom)} y={pan.y % (GRID_SIZE * zoom)}>
                <circle cx={GRID_SIZE * zoom / 2} cy={GRID_SIZE * zoom / 2} r={0.6} fill="rgba(255,255,255,0.05)" />
              </pattern>
              <pattern id="grid-large" width={GRID_SIZE * 5 * zoom} height={GRID_SIZE * 5 * zoom} patternUnits="userSpaceOnUse" x={pan.x % (GRID_SIZE * 5 * zoom)} y={pan.y % (GRID_SIZE * 5 * zoom)}>
                <circle cx={GRID_SIZE * 5 * zoom / 2} cy={GRID_SIZE * 5 * zoom / 2} r={1} fill="rgba(255,255,255,0.08)" />
              </pattern>
              {/* Edge arrow markers */}
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse" fill="#FFB020">
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            </defs>

            <rect width="100%" height="100%" fill="url(#grid-small)" />
            <rect width="100%" height="100%" fill="url(#grid-large)" />

            {/* Transform group */}
            <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
              {/* ── Edges ── */}
              {edges.map((edge) => {
                const fromNode = nodes.find((n) => n.id === edge.from);
                const toNode = nodes.find((n) => n.id === edge.to);
                if (!fromNode || !toNode) return null;
                return (
                  <g key={edge.id}>
                    <path
                      d={edgePath(fromNode, toNode)}
                      fill="none"
                      stroke="#FFB020"
                      strokeWidth={2}
                      strokeOpacity={0.6}
                      markerEnd="url(#arrow)"
                    />
                    {/* clickable hit area to delete edge */}
                    <path
                      d={edgePath(fromNode, toNode)}
                      fill="none"
                      stroke="transparent"
                      strokeWidth={12}
                      style={{ cursor: 'pointer' }}
                      onDoubleClick={() => setEdges((prev) => prev.filter((e) => e.id !== edge.id))}
                    />
                  </g>
                );
              })}

              {/* ── Wiring preview ── */}
              {wiring && (() => {
                const fromNode = nodes.find((n) => n.id === wiring.fromId);
                if (!fromNode) return null;
                const s = getPortPos(fromNode, 'out');
                const dx = Math.abs(wiring.mouseX - s.x) * 0.5;
                return (
                  <path
                    d={`M ${s.x} ${s.y} C ${s.x + dx} ${s.y}, ${wiring.mouseX - dx} ${wiring.mouseY}, ${wiring.mouseX} ${wiring.mouseY}`}
                    fill="none"
                    stroke="#FFB020"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    strokeOpacity={0.8}
                    pointerEvents="none"
                  />
                );
              })()}

              {/* ── Nodes ── */}
              {nodes.map((node) => {
                const color = nodeColor(node.type);
                const icon = nodeIcon(node.type);
                const isSelected = selectedNodeId === node.id;

                return (
                  <g
                    key={node.id}
                    data-node-id={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    style={{ cursor: 'move' }}
                    onDoubleClick={() => setEditingNode(node)}
                  >
                    {/* Shadow */}
                    <rect
                      x={2} y={2}
                      width={NODE_W} height={NODE_H}
                      rx={10}
                      fill="rgba(0,0,0,0.4)"
                    />
                    {/* Body */}
                    <rect
                      width={NODE_W} height={NODE_H}
                      rx={10}
                      fill="#141416"
                      stroke={isSelected ? '#FFB020' : color + '80'}
                      strokeWidth={isSelected ? 2 : 1.2}
                    />
                    {/* Color accent bar */}
                    <rect x={0} y={0} width={4} height={NODE_H} rx={2} fill={color} />

                    {/* Icon */}
                    <text x={18} y={NODE_H / 2 + 1} fontSize={18} dominantBaseline="central" fill={color}>
                      {icon}
                    </text>

                    {/* Label */}
                    <text x={42} y={24} fontSize={11} fill="white" fontWeight="600" fontFamily="system-ui">
                      {node.label.length > 20 ? node.label.slice(0, 20) + '…' : node.label}
                    </text>

                    {/* Agent */}
                    <text x={42} y={48} fontSize={9} fill="#6B6B6E" fontFamily="monospace">
                      {node.agent || node.type}
                    </text>

                    {/* Input port (left) */}
                    {node.type !== 'trigger' && (
                      <g className="cursor-crosshair">
                        <circle
                          cx={0} cy={NODE_H / 2}
                          r={16}
                          fill="transparent"
                          data-port-node={node.id}
                          data-port-dir="in"
                        />
                        <circle
                          cx={0} cy={NODE_H / 2}
                          r={PORT_R}
                          fill="#0C0C0E"
                          stroke={color}
                          strokeWidth={2}
                          className="pointer-events-none"
                        />
                      </g>
                    )}

                    {/* Output port (right) */}
                    <g className="cursor-crosshair">
                      <circle
                        cx={NODE_W} cy={NODE_H / 2}
                        r={16}
                        fill="transparent"
                        data-port-node={node.id}
                        data-port-dir="out"
                      />
                      <circle
                        cx={NODE_W} cy={NODE_H / 2}
                        r={PORT_R}
                        fill="#0C0C0E"
                        stroke={color}
                        strokeWidth={2}
                        className="pointer-events-none"
                      />
                    </g>
                  </g>
                );
              })}
            </g>
          </svg>

          {/* ── Node count footer ── */}
          <div className="absolute bottom-3 right-3 text-[10px] font-mono text-gray-500 bg-[#0C0C0E]/80 px-2 py-1 rounded border border-white/[0.06] select-none">
            {nodes.length} nodes · {edges.length} edges
          </div>
        </div>
      </div>

      {/* ── Node editor overlay ── */}
      {editingNode && (
        <div className="absolute inset-0 z-60 bg-black/50 flex items-center justify-center" onClick={() => setEditingNode(null)}>
          <div className="bg-[#141416] border border-white/[0.12] rounded-[12px] p-5 w-96 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-white">Edit Node</h3>
              <button onClick={() => setEditingNode(null)} className="p-1 text-gray-400 hover:text-white cursor-pointer"><X size={16} /></button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-[11px] font-mono text-gray-400 uppercase mb-1">Label</label>
                <input
                  type="text"
                  value={editingNode.label}
                  onChange={(e) => {
                    const val = e.target.value;
                    setEditingNode((prev) => prev ? { ...prev, label: val } : prev);
                    setNodes((prev) => prev.map((n) => n.id === editingNode.id ? { ...n, label: val } : n));
                  }}
                  className="w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-gray-400 uppercase mb-1">Assigned Agent</label>
                <input
                  type="text"
                  value={editingNode.agent || ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    setEditingNode((prev) => prev ? { ...prev, agent: val } : prev);
                    setNodes((prev) => prev.map((n) => n.id === editingNode.id ? { ...n, agent: val } : n));
                  }}
                  className="w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-gray-400 uppercase mb-1">Node Type</label>
                <select
                  value={editingNode.type}
                  onChange={(e) => {
                    const val = e.target.value as CanvasNodeType;
                    setEditingNode((prev) => prev ? { ...prev, type: val } : prev);
                    setNodes((prev) => prev.map((n) => n.id === editingNode.id ? { ...n, type: val } : n));
                  }}
                  className="w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white focus:outline-none focus:border-[#FFB020]"
                >
                  {NODE_TYPE_CATALOG.map((c) => (
                    <option key={c.type} value={c.type}>{c.icon} {c.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-white/[0.08]">
              <Button variant="secondary" size="xs" onClick={() => setEditingNode(null)}>Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
