/**
 * Shared node and edge registry for every Canvas mode.
 *
 * Every mode draws domain entities with `EntityNode`, which has no edit
 * affordances: the Canvas changes relationships, never the nodes themselves.
 * Edge looks are keyed by relationship kind so the same relationship reads the
 * same in every mode.
 */

import { memo } from 'react';
import { Handle, Position, type NodeProps, type XYPosition } from 'reactflow';

import type { CanvasEdge, EdgeData, EdgeKind, EntityData, EntityKind, ToolOutcome } from './types';

const KIND_COLOR: Record<EntityKind, string> = {
  agent: '#FFB020',
  session: '#38BDF8',
  connection: '#A855F7',
  tool: '#9C9C9F',
  department: '#10B981',
  team: '#14B8A6',
  pipeline: '#EF4444',
  stage: '#64748B',
};

export const OUTCOME_LABEL: Record<ToolOutcome, string> = {
  allowed: 'allowed',
  would_deny: 'would deny',
  denied: 'denied',
  unscoped: 'not in scope',
};

const OUTCOME_COLOR: Record<ToolOutcome, string> = {
  allowed: '#10B981',
  would_deny: '#F59E0B',
  denied: '#EF4444',
  unscoped: '#6B6B6E',
};

const HANDLE = { width: 8, height: 8, background: '#0C0C0E', border: '2px solid #3A3A3E' };

export const EntityNode = memo(({ data, selected }: NodeProps<EntityData>) => {
  const color = KIND_COLOR[data.kind];
  return (
    <div
      aria-label={`${data.kind} ${data.label}`}
      className="rounded-[8px] border px-3 py-2 text-left"
      style={{
        width: 200,
        background: '#141416',
        borderColor: selected ? '#FFB020' : `${color}80`,
        borderWidth: selected ? 2 : 1,
        opacity: data.muted ? 0.5 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} style={HANDLE} />
      <div className="text-[9px] uppercase tracking-wide font-mono" style={{ color }}>
        {data.kind}
      </div>
      <div className="text-[12px] text-white truncate">{data.label}</div>
      {data.subtitle && <div className="text-[10px] font-mono text-[#6B6B6E] truncate">{data.subtitle}</div>}
      {data.outcome && (
        <div className="mt-1 text-[10px] font-mono" style={{ color: OUTCOME_COLOR[data.outcome] }}>
          {OUTCOME_LABEL[data.outcome]}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={HANDLE} />
    </div>
  );
});
EntityNode.displayName = 'EntityNode';

/** Passed to every mode's <ReactFlow nodeTypes>; defined once so it is stable. */
export const canvasNodeTypes = { entity: EntityNode };

export const EDGE_STYLES: Record<EdgeKind, { stroke: string; label: string; dashed?: boolean }> = {
  reports_to: { stroke: '#FFB020', label: 'manages' },
  delegation: { stroke: '#38BDF8', label: 'delegated', dashed: true },
  session_of: { stroke: '#38BDF8', label: 'session' },
  member_of: { stroke: '#10B981', label: 'member of', dashed: true },
  binding: { stroke: '#A855F7', label: 'bound' },
  binding_disabled: { stroke: '#6B6B6E', label: 'binding disabled', dashed: true },
  provides: { stroke: '#3A3A3E', label: 'provides' },
  effective_allowed: { stroke: '#10B981', label: 'allowed' },
  effective_would_deny: { stroke: '#F59E0B', label: 'would deny', dashed: true },
  effective_denied: { stroke: '#EF4444', label: 'denied', dashed: true },
  step: { stroke: '#64748B', label: 'next' },
};

export function edge(
  id: string,
  source: string,
  target: string,
  kind: EdgeKind,
  extra: { entityId?: string; deletable?: boolean } = {}
): CanvasEdge {
  const look = EDGE_STYLES[kind];
  const data: EdgeData = { kind, entityId: extra.entityId };
  return {
    id,
    source,
    target,
    data,
    type: 'smoothstep',
    label: look.label,
    deletable: extra.deletable ?? false,
    style: { stroke: look.stroke, strokeDasharray: look.dashed ? '5 4' : undefined },
    labelStyle: { fill: '#9C9C9F', fontSize: 9 },
    labelBgStyle: { fill: '#0A0A0B' },
  };
}

/**
 * Column-per-rank layout: presentation only, recomputed from server data on
 * every render. ponytail: no graph layout engine, add one when ranks get wide.
 */
export function placeByRank(items: Array<{ id: string; rank: number }>): Map<string, XYPosition> {
  const rows = new Map<number, number>();
  const out = new Map<string, XYPosition>();
  for (const { id, rank } of items) {
    const row = rows.get(rank) ?? 0;
    rows.set(rank, row + 1);
    out.set(id, { x: rank * 260, y: row * 110 });
  }
  return out;
}
