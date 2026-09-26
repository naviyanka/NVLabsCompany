/**
 * The one React Flow surface every Canvas mode renders into.
 *
 * Nodes and edges come from the mode's projection of server state. Locally
 * the surface keeps only presentation: node positions, measured sizes and the
 * selection. A connect, remove or toggle is sent to the API; nothing is added
 * to or taken from the graph until the refetch that follows brings back what
 * the server now holds, success or failure.
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import ReactFlow, {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { ApiClientError } from '@/api/client';
import { isTopologyQuery } from '@/api/canvas';
import { describeError } from '@/components/workspace/describeError';
import { canvasNodeTypes, EDGE_STYLES } from './registry';
import type { CanvasEdge, CanvasNode, ModeGraph } from './types';

/** Mutation refusals quote the server: it is the one that decided. */
function mutationMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.status !== 404 && error.status !== 401 && error.detail) {
    return error.detail;
  }
  return describeError(error);
}

/** Keep what the user arranged; take everything else from the server. */
function reconcile<T extends CanvasNode | CanvasEdge>(server: T[], local: T[], keep: (prev: T, next: T) => T): T[] {
  const byId = new Map(local.map((item) => [item.id, item]));
  return server.map((item) => {
    const prev = byId.get(item.id);
    return prev ? keep(prev, item) : item;
  });
}

interface CanvasSurfaceProps {
  graph: ModeGraph;
  /** Opens an agent or session in the workspace (a URL change, nothing more). */
  onOpen?: (node: CanvasNode) => void;
}

export function CanvasSurface({ graph, onOpen }: CanvasSurfaceProps) {
  const queryClient = useQueryClient();
  const [nodes, setNodes] = useState<CanvasNode[]>(graph.nodes);
  const [edges, setEdges] = useState<CanvasEdge[]>(graph.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setNodes((local) =>
      reconcile(graph.nodes, local, (prev, next) => ({
        ...next,
        position: prev.position,
        width: prev.width,
        height: prev.height,
      }))
    );
  }, [graph.nodes]);
  useEffect(() => {
    setEdges((local) => reconcile(graph.edges, local, (prev, next) => ({ ...next, selected: prev.selected })));
  }, [graph.edges]);

  const mutation = useMutation({
    mutationFn: (op: () => Promise<unknown>) => op(),
    onMutate: () => setNotice(null),
    onSettled: () => queryClient.invalidateQueries({ predicate: ({ queryKey }) => isTopologyQuery(queryKey) }),
  });

  const connect = (c: Connection) => {
    if (!graph.connect) return;
    const refusal = graph.canConnect?.(c) ?? null;
    if (refusal) {
      setNotice(refusal);
      return;
    }
    mutation.mutate(() => graph.connect!(c));
  };

  const onNodesChange = (changes: NodeChange[]) => {
    // Nodes are domain rows: the canvas never deletes one.
    setNodes((nds) => applyNodeChanges(changes.filter((c) => c.type !== 'remove'), nds));
    for (const c of changes) if (c.type === 'select' && c.selected) setSelectedId(c.id);
  };

  const onEdgesChange = (changes: EdgeChange[]) => {
    const removed = changes.filter((c) => c.type === 'remove').map((c) => c.id);
    const target = edges.find((e) => removed.includes(e.id) && e.deletable);
    if (target && graph.removeEdge) mutation.mutate(() => graph.removeEdge!(target));
    setEdges((eds) => applyEdgeChanges(changes.filter((c) => c.type !== 'remove'), eds));
  };

  const selected = nodes.find((n) => n.id === selectedId) ?? null;
  const viewNodes = useMemo(
    () => nodes.map((n) => ({ ...n, selected: n.id === selectedId, deletable: false })),
    [nodes, selectedId]
  );

  const error = notice ?? (mutation.error ? mutationMessage(mutation.error) : null);
  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 relative min-w-0">
        {error && (
          <p role="alert" className="absolute top-2 left-2 right-2 z-10 px-3 py-1.5 text-[11px] rounded bg-red-500/10 text-red-400 border border-red-500/30">
            {error}
          </p>
        )}
        <ReactFlow
          nodes={viewNodes}
          edges={edges}
          nodeTypes={canvasNodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={connect}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onNodeDoubleClick={(_, n) => onOpen?.(n as CanvasNode)}
          onPaneClick={() => setSelectedId(null)}
          nodesConnectable={!!graph.connect}
          deleteKeyCode={graph.removeEdge ? ['Backspace', 'Delete'] : null}
          proOptions={{ hideAttribution: true }}
          fitView
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#2A2A2E" />
          <Controls className="!bg-[#141416] !border-white/[0.1]" />
          <MiniMap className="!bg-[#0C0C0E] !border !border-white/[0.1]" maskColor="rgba(0,0,0,0.6)" />
        </ReactFlow>
      </div>
      <Inspector
        graph={graph}
        nodes={nodes}
        edges={edges}
        selected={selected}
        onSelect={setSelectedId}
        onConnect={connect}
        onRun={(op) => mutation.mutate(op)}
        pending={mutation.isPending}
        onOpen={onOpen}
      />
    </div>
  );
}

interface InspectorProps {
  graph: ModeGraph;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  selected: CanvasNode | null;
  onSelect: (id: string | null) => void;
  onConnect: (c: Connection) => void;
  onRun: (op: () => Promise<unknown>) => void;
  pending: boolean;
  onOpen?: (node: CanvasNode) => void;
}

/**
 * Everything the canvas can do by drag, as ordinary controls: pick a node,
 * connect it, remove or toggle its relationships. Same mutations, same path.
 */
function Inspector({ graph, nodes, edges, selected, onSelect, onConnect, onRun, pending, onOpen }: InspectorProps) {
  const [target, setTarget] = useState('');
  const label = (id: string) => nodes.find((n) => n.id === id)?.data.label ?? id;
  const candidates = selected
    ? nodes.filter(
        (n) =>
          n.id !== selected.id &&
          graph.canConnect?.({ source: selected.id, target: n.id, sourceHandle: null, targetHandle: null }) === null
      )
    : [];
  const related = selected ? edges.filter((e) => e.source === selected.id || e.target === selected.id) : [];
  const openable = selected && onOpen && (selected.data.kind === 'agent' || selected.data.kind === 'session');

  return (
    <aside aria-label="Inspector" className="w-64 shrink-0 border-l border-white/[0.08] p-3 space-y-3 overflow-y-auto text-xs">
      <label className="block">
        <span className="text-[10px] uppercase text-[#6B6B6E]">Selected</span>
        <select
          aria-label="Selected item"
          value={selected?.id ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
          className="mt-1 w-full bg-[#141416] border border-white/[0.08] rounded px-2 py-1 text-[#F2F1EE]"
        >
          <option value="">Nothing selected</option>
          {nodes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.data.kind}: {n.data.label}
            </option>
          ))}
        </select>
      </label>
      {pending && <p role="status" className="text-[#9C9C9F]">Saving…</p>}
      {selected && (
        <>
          <div>
            <p className="text-[#F2F1EE]">{selected.data.label}</p>
            {selected.data.subtitle && <p className="font-mono text-[10px] text-[#6B6B6E]">{selected.data.subtitle}</p>}
            {openable && (
              <button type="button" onClick={() => onOpen!(selected)} className="mt-1 text-[#38BDF8]">
                Open in workspace
              </button>
            )}
          </div>
          {graph.connectLabel && candidates.length > 0 && (
            <form
              className="space-y-1"
              onSubmit={(e) => {
                e.preventDefault();
                if (target) onConnect({ source: selected.id, target, sourceHandle: null, targetHandle: null });
              }}
            >
              <select
                aria-label={graph.connectLabel}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="w-full bg-[#141416] border border-white/[0.08] rounded px-2 py-1 text-[#F2F1EE]"
              >
                <option value="">Choose…</option>
                {candidates.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.data.label}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={!target || pending}
                className="px-2 py-1 rounded bg-[#FFB020] text-black disabled:opacity-40"
              >
                {graph.connectLabel}
              </button>
            </form>
          )}
          <ul aria-label="Relationships" className="space-y-1">
            {related.map((e) => {
              const kind = e.data!.kind;
              const other = e.source === selected.id ? e.target : e.source;
              const toggles = graph.toggleEdge && (kind === 'binding' || kind === 'binding_disabled');
              const name = `${EDGE_STYLES[kind].label}: ${label(other)}`;
              return (
                <li key={e.id} className="flex items-center gap-1">
                  <span className="flex-1 truncate text-[#9C9C9F]">
                    {name}
                  </span>
                  {toggles && (
                    <button type="button" disabled={pending} onClick={() => onRun(() => graph.toggleEdge!(e))} aria-label={`${kind === 'binding' ? 'Disable' : 'Enable'} ${name}`} className="text-[#38BDF8] disabled:opacity-40">
                      {kind === 'binding' ? 'Disable' : 'Enable'}
                    </button>
                  )}
                  {e.deletable && graph.removeEdge && (
                    <button type="button" disabled={pending} onClick={() => onRun(() => graph.removeEdge!(e))} aria-label={`Remove ${name}`} className="text-red-400 disabled:opacity-40">
                      Remove
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </aside>
  );
}
