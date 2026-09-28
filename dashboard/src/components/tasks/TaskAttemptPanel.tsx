import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Ban, FileCheck2, Loader2, Play, RotateCcw } from 'lucide-react';
import { apiClient } from '@/api/client';
import { Badge } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { useEventStream } from '@/hooks/useEventStream';
import { COMPLETION_REASON_LABELS, type Task, type TaskAttempt } from '@/types/task';
import type { Agent } from '@/types/agent';

const RETRYABLE = new Set(['failed', 'blocked', 'cancelled', 'expired']);
const TERMINAL = new Set([...RETRYABLE, 'completed']);
// Polling backs up the session event stream while an attempt is live.
const POLL_MS = 3000;

interface AttemptEvent {
  event_type?: string;
  payload?: { task_id?: string; attempt_status?: string };
}

export const attemptsKey = (taskId: string) => ['task-attempts', taskId] as const;

/**
 * The employee's work on one task: the latest attempt's live state, progress,
 * evidence and controls. All state comes from the server, so a refresh
 * restores it, and each task has its own query and mutations, so work on one
 * task never blocks another.
 */
export function TaskAttemptPanel({ task, agents }: { task: Task; agents: Agent[] }) {
  const queryClient = useQueryClient();
  const base = `/api/v1/tasks/${task.id}/attempts`;
  const attempts = useQuery({
    queryKey: attemptsKey(task.id),
    queryFn: () => apiClient.get<TaskAttempt[]>(base),
    refetchInterval: (query) => (query.state.data?.[0]?.active ? POLL_MS : false),
  });

  useEventStream<AttemptEvent>(
    'sessions',
    useCallback(
      (event: AttemptEvent) => {
        if (event?.event_type !== 'task.attempt' || event.payload?.task_id !== task.id) return;
        void queryClient.invalidateQueries({ queryKey: attemptsKey(task.id) });
        // A finished attempt moved the task itself; refresh the board too.
        if (TERMINAL.has(event.payload.attempt_status ?? '')) {
          void queryClient.invalidateQueries({ queryKey: ['tasks'] });
        }
      },
      [queryClient, task.id]
    )
  );

  const refresh = () => queryClient.invalidateQueries({ queryKey: attemptsKey(task.id) });
  const start = useMutation({
    mutationFn: () => apiClient.post<TaskAttempt>(base, {}),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => apiClient.post<TaskAttempt>(`${base}/${id}/cancel`),
    onSuccess: refresh,
  });
  const retry = useMutation({
    mutationFn: (id: string) => apiClient.post<TaskAttempt>(`${base}/${id}/retry`),
    onSuccess: refresh,
  });

  const latest = attempts.data?.[0];
  const report = latest?.report;
  const employee = agents.find((a) => a.id === (latest?.agent_id ?? task.assigned_agent_id));
  const error = start.error ?? cancel.error ?? retry.error;
  const tests = latest?.verification?.commands ?? [];

  return (
    <section
      aria-label="Employee work"
      className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-3 text-xs font-mono"
    >
      <div className="flex items-center justify-between">
        <span className="text-gray-400">
          Employee: <strong className="text-[#FFB020]">{employee?.name ?? 'Unassigned'}</strong>
        </span>
        {latest && (
          <Badge variant={latest.status as any}>
            {`Attempt ${latest.attempt_number}: ${latest.status}`}
          </Badge>
        )}
      </div>

      {latest && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
          <dt className="text-gray-500">State</dt>
          <dd data-testid="attempt-state">{report?.state ?? latest.status}</dd>
          <dt className="text-gray-500">Step</dt>
          <dd>{report?.current_step ?? '—'}</dd>
          <dt className="text-gray-500">Progress</dt>
          <dd>{report?.progress_percent != null ? `${report.progress_percent}%` : '—'}</dd>
          <dt className="text-gray-500">Backend</dt>
          <dd>{latest.usage?.backend ?? '—'}</dd>
          <dt className="text-gray-500">Execution</dt>
          <dd className="truncate">{latest.execution_id ?? '—'}</dd>
          {latest.completion_reason && (
            <>
              <dt className="text-gray-500">Outcome</dt>
              <dd>
                {COMPLETION_REASON_LABELS[latest.completion_reason] ?? latest.completion_reason}
                {latest.error_code ? ` (${latest.error_code})` : ''}
              </dd>
            </>
          )}
        </dl>
      )}

      {report?.summary && <p className="text-[#C8C8CB] font-sans">{report.summary}</p>}

      {!!report?.blockers?.length && (
        <ul aria-label="Blockers" className="text-[#F97316] list-disc pl-4">
          {report.blockers.map((b) => <li key={b}>{b}</li>)}
        </ul>
      )}

      {!!latest?.artifacts.length && (
        <ul aria-label="Artifacts" className="space-y-0.5">
          {latest.artifacts.map((a) => (
            <li key={a.path} className="flex items-center gap-1.5">
              <FileCheck2 size={12} className="text-emerald-400" />
              <span>{a.path}</span>
              <span className="text-gray-500">{a.validation}</span>
              <span className="text-gray-600" title={a.sha256}>{a.sha256.slice(0, 12)}</span>
            </li>
          ))}
        </ul>
      )}

      {tests.length > 0 && (
        <ul aria-label="Tests" className="space-y-0.5">
          {tests.map((c) => (
            <li key={c.id} className={c.passed ? 'text-emerald-400' : 'text-[#EF4444]'}>
              {c.command} exit {c.exit_code ?? 'timeout'}
              {c.tests ? ` · ${Object.entries(c.tests).map(([k, n]) => `${n} ${k}`).join(', ')}` : ''}
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p role="alert" className="text-[#EF4444]">
          {error.message}
        </p>
      )}

      <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
        {(!latest || (!latest.active && latest.status !== 'completed' && !RETRYABLE.has(latest.status))) && (
          <Button
            size="xs"
            icon={start.isPending ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            disabled={start.isPending || !task.assigned_agent_id}
            onClick={() => start.mutate()}
          >
            Start work
          </Button>
        )}
        {latest?.active && (
          <Button
            size="xs"
            variant="danger"
            icon={<Ban size={13} />}
            disabled={cancel.isPending || latest.cancel_requested}
            onClick={() => cancel.mutate(latest.id)}
          >
            {latest.cancel_requested ? 'Cancelling…' : 'Cancel attempt'}
          </Button>
        )}
        {latest && RETRYABLE.has(latest.status) && (
          <Button
            size="xs"
            variant="secondary"
            icon={<RotateCcw size={13} />}
            disabled={retry.isPending}
            onClick={() => retry.mutate(latest.id)}
          >
            Retry
          </Button>
        )}
        {latest?.session_id && (
          <Link
            className="ml-auto text-[#38BDF8] hover:underline"
            to={`/workspace?agent=${latest.agent_id}&session=${latest.session_id}`}
          >
            Open session
          </Link>
        )}
      </div>
    </section>
  );
}
