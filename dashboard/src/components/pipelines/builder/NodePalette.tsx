/**
 * NodePalette — draggable node palette fed by GET /api/v1/nodes.
 *
 * Mirrors OpenCompany's palette: each item is draggable and sets
 * dataTransfer['application/reactflow'] to a JSON payload the canvas onDrop
 * reads. Also supports click-to-add via onAdd for touch / no-drag flows.
 */

import { apiClient } from '@/api/client';
import type { ApiNode } from '@/types/pipeline';
import { useEffect, useMemo, useState } from 'react';
import { categoryColor } from './categories';
import { NodeIcon } from './NodeIcon';

/** Built-in pipeline control nodes that are not in the backend registry. */
const BUILTIN_NODES: ApiNode[] = [
  {
    id: 'builtin.trigger',
    name: 'Trigger',
    description: 'Webhook, Cron, Git Push, or Manual dispatch',
    category: 'trigger',
    icon: '⚡',
    inputs: [
      { name: 'event', type: 'string', required: false, default: 'manual', description: 'Trigger event type' },
    ],
    outputs: [{ name: 'out', type: 'main' }],
    credentials: [],
  },
];

export interface PaletteDragPayload {
  nodeId: string;
  name: string;
  category: string;
  icon?: string;
  inputs: ApiNode['inputs'];
}

function toPayload(node: ApiNode): PaletteDragPayload {
  return {
    nodeId: node.id,
    name: node.name,
    category: node.category,
    icon: node.icon,
    inputs: node.inputs,
  };
}

export function NodePalette({ onAdd }: { onAdd: (payload: PaletteDragPayload) => void }) {
  const [nodes, setNodes] = useState<ApiNode[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<{ items: ApiNode[] }>('/api/v1/nodes')
      .then((res) => {
        if (cancelled) return;
        setNodes(res.items || []);
      })
      .catch(() => { /* keep builtins only */ })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  const categories = useMemo(() => {
    const cats = new Set(nodes.map((n) => n.category));
    return Array.from(cats).sort();
  }, [nodes]);

  const filtered = useMemo(() => {
    let result = nodes;
    if (category !== 'all') result = result.filter((n) => n.category === category);
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (n) =>
          (n.name ?? '').toLowerCase().includes(q) ||
          (n.description ?? '').toLowerCase().includes(q),
      );
    }
    return result;
  }, [nodes, category, search]);

  const onDragStart = (e: React.DragEvent, node: ApiNode) => {
    e.dataTransfer.setData('application/reactflow', JSON.stringify(toPayload(node)));
    e.dataTransfer.effectAllowed = 'move';
  };

  const renderRow = (node: ApiNode, compact = false) => {
    const color = categoryColor(node.category);
    return (
      <div
        key={node.id}
        draggable
        onDragStart={(e) => onDragStart(e, node)}
        onClick={() => onAdd(toPayload(node))}
        title={node.description}
        className="w-full text-left p-2 rounded-[6px] border border-white/[0.06] bg-[#141416] hover:border-white/[0.2] hover:bg-[#1A1A1E] transition-all cursor-grab active:cursor-grabbing group"
      >
        <div className="flex items-center gap-2">
          <span
            className="flex items-center justify-center rounded shrink-0"
            style={{
              width: compact ? 22 : 26,
              height: compact ? 22 : 26,
              background: color + '18',
              border: `1px solid ${color}60`,
            }}
          >
            <NodeIcon icon={node.icon} category={node.category} size={compact ? 12 : 14} color={color} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-medium text-[#E0E0E0] group-hover:text-[#FFB020] truncate">
              {node.name}
            </div>
            {!compact && (
              <div className="text-[9px] text-[#6B6B6E] truncate">{node.category}</div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="p-3 space-y-2">
      <div className="text-[10px] font-mono text-[#FFB020] uppercase font-bold tracking-wider mb-1">
        Node Library — Drag onto canvas
      </div>

      <input
        type="text"
        placeholder="Search nodes..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
      />

      <select
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        className="w-full px-2 py-1 bg-[#141416] border border-white/[0.08] rounded text-[10px] text-white focus:outline-none focus:border-[#FFB020]"
      >
        <option value="all">All Categories ({nodes.length})</option>
        {categories.map((cat) => (
          <option key={cat} value={cat}>
            {cat} ({nodes.filter((n) => n.category === cat).length})
          </option>
        ))}
      </select>

      {/* Built-in pipeline controls */}
      <div className="text-[9px] font-mono text-[#6B6B6E] uppercase mt-2 mb-1">Pipeline Controls</div>
      {BUILTIN_NODES.map((n) => renderRow(n))}

      {/* Registry nodes */}
      <div className="text-[9px] font-mono text-[#6B6B6E] uppercase mt-3 mb-1">
        Workflow Nodes ({filtered.length})
      </div>
      {loading && <div className="text-[10px] text-[#6B6B6E] py-2">Loading nodes…</div>}
      <div className="space-y-1 max-h-[52vh] overflow-y-auto pr-1">
        {filtered.slice(0, 60).map((n) => renderRow(n, true))}
        {filtered.length > 60 && (
          <div className="text-[9px] text-[#6B6B6E] text-center py-1">
            +{filtered.length - 60} more — narrow with search
          </div>
        )}
      </div>
    </div>
  );
}
