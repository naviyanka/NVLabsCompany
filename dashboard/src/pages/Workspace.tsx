import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { getSession, sessionKeys } from '@/api/sessions';
import { useEventStream } from '@/hooks/useEventStream';
import { AgentRail } from '@/components/workspace/AgentRail';
import {
  SessionPane,
  WORKSPACE_TABS,
  WorkspaceTabs,
  type WorkspaceTab,
} from '@/components/workspace/SessionPane';
import { ContextPanel } from '@/components/workspace/ContextPanel';
import { CanvasView } from '@/components/canvas/CanvasView';
import { CANVAS_MODES, type CanvasMode } from '@/components/canvas/types';

interface SessionEvent {
  event_type?: string;
  payload?: { session_id?: string };
}

/**
 * Agent Workspace: agent/session rail, session-aware main pane, context panel.
 *
 * The URL (`?agent=&session=&tab=&mode=&pipeline=`) is the only client-side state: it names
 * what is selected, so a reload or a shared link lands in the same place.
 * Everything shown about that selection is server state from React Query,
 * refreshed by the `sessions` SSE channel rather than patched locally.
 */
export function Workspace() {
  const [params, setParams] = useSearchParams();
  const sessionId = params.get('session');
  const tabParam = params.get('tab') as WorkspaceTab | null;
  const tab: WorkspaceTab = tabParam && WORKSPACE_TABS.includes(tabParam) ? tabParam : 'chat';
  const modeParam = params.get('mode') as CanvasMode | null;
  const mode: CanvasMode = modeParam && CANVAS_MODES.includes(modeParam) ? modeParam : 'network';

  const session = useQuery({
    queryKey: sessionKeys.detail(sessionId ?? ''),
    queryFn: () => getSession(sessionId!),
    enabled: !!sessionId,
  });
  // The session's owner is the server's answer; the URL's agent is only a hint.
  const agentId = session.data?.agent_id ?? params.get('agent');

  const select = useCallback(
    (next: {
      agent?: string | null;
      session?: string | null;
      tab?: WorkspaceTab | null;
      mode?: CanvasMode | null;
      pipeline?: string | null;
    }) => {
      setParams((prev) => {
        const out = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(next)) {
          if (value) out.set(key, value);
          else out.delete(key);
        }
        return out;
      });
    },
    [setParams]
  );

  const queryClient = useQueryClient();
  useEventStream<SessionEvent>(
    'sessions',
    useCallback(
      (event: SessionEvent) => {
        const changed = event?.payload?.session_id;
        void queryClient.invalidateQueries({
          predicate: ({ queryKey }) =>
            queryKey[0] === 'sessions' && (queryKey[1] === 'list' || queryKey[2] === changed),
        });
      },
      [queryClient]
    )
  );

  const onTab = (t: WorkspaceTab) => select({ tab: t === 'chat' ? null : t });

  return (
    <div
      data-testid="workspace"
      className="h-full flex-1 flex min-h-0 bg-[#0A0A0B] border border-white/[0.08] rounded-[10px] overflow-hidden"
    >
      <AgentRail
        agentId={agentId}
        sessionId={sessionId}
        onSelectAgent={(id) => select({ agent: id, session: null })}
        onSelectSession={(s) => select({ agent: s.agent_id, session: s.id })}
      />
      {tab === 'canvas' ? (
        <section aria-label="Canvas" className="flex-1 flex flex-col min-w-0 min-h-0">
          <WorkspaceTabs tab={tab} onTab={onTab} />
          <CanvasView
            mode={mode}
            onMode={(m) => select({ mode: m })}
            ctx={{ agentId, sessionId, pipelineId: params.get('pipeline'), select }}
          />
        </section>
      ) : (
        <SessionPane
          sessionId={sessionId}
          session={session}
          tab={tab}
          onTab={onTab}
          onClear={() => select({ session: null })}
        />
      )}
      <ContextPanel agentId={agentId} session={session.data ?? null} />
    </div>
  );
}
