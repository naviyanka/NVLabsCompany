import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { isTopologyQuery } from '@/api/canvas';
import { useEventStream } from '@/hooks/useEventStream';
import { describeError } from '@/components/workspace/describeError';
import { CanvasSurface } from './CanvasSurface';
import { CANVAS_MODE_DEFS } from './modes';
import { CANVAS_MODES, type CanvasMode, type CanvasModeDef, type CanvasNode, type ModeContext } from './types';

interface CanvasViewProps {
  mode: CanvasMode;
  onMode: (mode: CanvasMode) => void;
  ctx: ModeContext;
}

/**
 * Canvas: one surface, four projections of the same domain. Mode and
 * selection live in the URL; the graph is refetched whenever the server
 * announces a topology change for this company.
 */
export function CanvasView({ mode, onMode, ctx }: CanvasViewProps) {
  const queryClient = useQueryClient();
  useEventStream(
    'topology',
    useCallback(
      () => void queryClient.invalidateQueries({ predicate: ({ queryKey }) => isTopologyQuery(queryKey) }),
      [queryClient]
    )
  );

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <nav role="tablist" aria-label="Canvas mode" className="flex gap-1 px-3 py-1.5 border-b border-white/[0.08]">
        {CANVAS_MODES.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={m === mode}
            onClick={() => onMode(m)}
            className={`px-2.5 py-1 text-[11px] rounded ${m === mode ? 'bg-white/[0.08] text-[#F2F1EE]' : 'text-[#6B6B6E]'}`}
          >
            {CANVAS_MODE_DEFS[m].label}
          </button>
        ))}
      </nav>
      {/* Keyed so each mode's hooks start fresh: modes query different things. */}
      <ModeCanvas key={mode} def={CANVAS_MODE_DEFS[mode]} ctx={ctx} />
    </div>
  );
}

function ModeCanvas({ def, ctx }: { def: CanvasModeDef; ctx: ModeContext }) {
  const graph = def.useGraph(ctx);
  const open = (node: CanvasNode) => {
    if (node.data.kind === 'agent') ctx.select({ agent: node.data.entityId, session: null });
    if (node.data.kind === 'session') ctx.select({ session: node.data.entityId });
  };

  let body;
  if (graph.loading) body = <p className="p-4 text-sm text-[#6B6B6E]">Loading…</p>;
  else if (graph.error) {
    body = (
      <p role="alert" className="p-4 text-sm text-red-400">
        {describeError(graph.error)}
      </p>
    );
  } else if (graph.empty) body = <p className="p-4 text-sm text-[#6B6B6E]">{graph.empty}</p>;
  else body = <CanvasSurface graph={graph} onOpen={open} />;

  return (
    <section aria-label={`${def.label} canvas`} className="flex-1 flex flex-col min-h-0">
      {graph.toolbar && <div className="flex items-center gap-3 px-3 py-1.5 border-b border-white/[0.08]">{graph.toolbar}</div>}
      {body}
    </section>
  );
}
