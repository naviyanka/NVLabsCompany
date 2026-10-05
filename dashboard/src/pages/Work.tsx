import { apiClient } from '@/api/client';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { EmptyState } from '@/components/common/EmptyState';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';

interface AttemptState {
  attempt_id: string;
  attempt_number: number;
  status: string;
  awaiting_review: boolean;
  verification: string | null;
  deliverable?: string | null;
  error_code: string | null;
  stale: boolean;
}

interface WorkItem {
  id: string;
  title: string;
  status: string;
  assignee: { id: string; name: string | null } | null;
  attempt: AttemptState | null;
  result: string | null;
  failure: string | null;
  updated_at: string | null;
  tasks?: WorkItem[];
}

interface WorkList {
  metrics: { awaiting_review: number; stale_attempts: number };
  work: WorkItem[];
}

const VARIANT: Record<string, BadgeVariant> = {
  pending: 'pending',
  delegated: 'info',
  in_progress: 'in_progress',
  in_review: 'warning',
  completed: 'completed',
  failed: 'failed',
  blocked: 'failed',
  cancelled: 'neutral',
};

const CLOSED = new Set(['completed', 'cancelled']);

function newKey(): string {
  return crypto.randomUUID();
}

function TaskRow({
  item,
  onReview,
  busy,
}: {
  item: WorkItem;
  onReview: (attemptId: string, decision: 'verify' | 'reject', reason: string) => void;
  busy: boolean;
}) {
  const [reason, setReason] = useState('');
  const attempt = item.attempt;
  return (
    <div className="border-t border-white/[0.06] py-2 text-sm" data-testid="work-task">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[#F2F1EE]">{item.title}</span>
        <Badge variant={VARIANT[item.status] ?? 'default'}>{item.status}</Badge>
        <span className="text-xs text-[#A8A8AB]">{item.assignee?.name ?? 'unassigned'}</span>
        {attempt && (
          <span className="text-xs text-[#A8A8AB]">
            attempt {attempt.attempt_number}: {attempt.awaiting_review ? 'awaiting review' : attempt.status}
            {attempt.verification ? ` · verification ${attempt.verification}` : ''}
            {attempt.stale ? ' · stale' : ''}
          </span>
        )}
      </div>
      {item.failure && <p className="mt-1 text-xs text-[#EF4444]">Failure: {item.failure}</p>}
      {item.result && <p className="mt-1 text-xs text-[#A8A8AB]">Result: {item.result}</p>}
      {attempt?.awaiting_review && (
        <div className="mt-2 space-y-2">
          {attempt.deliverable && (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white/[0.03] p-2 text-xs text-[#F2F1EE]">
              {attempt.deliverable}
            </pre>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="xs" disabled={busy} onClick={() => onReview(attempt.attempt_id, 'verify', '')}>
              Verify
            </Button>
            <input
              aria-label="Rejection reason"
              className="rounded border border-white/[0.12] bg-transparent px-2 py-1 text-xs text-[#F2F1EE]"
              placeholder="Reason to reject"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button
              size="xs"
              variant="danger"
              disabled={busy || !reason.trim()}
              onClick={() => onReview(attempt.attempt_id, 'reject', reason.trim())}
            >
              Reject
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Work() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  // One key per form fill: a double click or a retry after reconnect is the same work order.
  const createKey = useRef(newKey());

  const { data, isLoading } = useQuery({
    queryKey: ['work'],
    queryFn: () => apiClient.get<WorkList>('/api/v1/work'),
    refetchInterval: 5000,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['work'] });
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : 'Request failed');

  const create = useMutation({
    mutationFn: () =>
      apiClient.post(
        '/api/v1/work',
        { title: title.trim(), description: description.trim() || null },
        { 'Idempotency-Key': createKey.current }
      ),
    onSuccess: () => {
      setTitle('');
      setDescription('');
      createKey.current = newKey();
      setError(null);
      refresh();
    },
    onError: fail,
  });

  const review = useMutation({
    mutationFn: (v: { attemptId: string; decision: 'verify' | 'reject'; reason: string }) =>
      apiClient.post(`/api/v1/work/attempts/${v.attemptId}/review`, {
        decision: v.decision,
        reason: v.reason || null,
      }),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (e) => {
      fail(e);
      refresh();
    },
  });

  const cancel = useMutation({
    mutationFn: (id: string) => apiClient.post(`/api/v1/work/${id}/cancel`),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (e) => {
      fail(e);
      refresh();
    },
  });

  const busy = review.isPending || cancel.isPending;
  const onReview = (attemptId: string, decision: 'verify' | 'reject', reason: string) =>
    review.mutate({ attemptId, decision, reason });

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-display text-[#F2F1EE]">Company Work</h1>
        <p className="text-sm text-[#A8A8AB]">
          Work orders and their tasks, read from stored state.
          {data ? ` ${data.metrics.awaiting_review} awaiting review.` : ''}
        </p>
      </div>

      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim() && !create.isPending) create.mutate();
        }}
      >
        <input
          aria-label="Work title"
          className="w-full rounded border border-white/[0.12] bg-transparent px-3 py-2 text-sm text-[#F2F1EE]"
          placeholder="What should the company get done?"
          value={title}
          maxLength={255}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          aria-label="Work description"
          className="w-full rounded border border-white/[0.12] bg-transparent px-3 py-2 text-sm text-[#F2F1EE]"
          placeholder="Details (optional)"
          value={description}
          maxLength={4000}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Button type="submit" disabled={!title.trim() || create.isPending}>
          Create work order
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-[#EF4444]">
          {error}
        </p>
      )}

      {isLoading ? (
        <p className="text-sm text-[#A8A8AB]">Loading…</p>
      ) : !data || data.work.length === 0 ? (
        <EmptyState title="No work yet" description="Create a work order to start." />
      ) : (
        <div className="space-y-3">
          {data.work.map((w) => (
            <section
              key={w.id}
              className="rounded-[10px] border border-white/[0.08] bg-[#141416] p-4"
              data-testid="work-order"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-medium text-[#F2F1EE]">{w.title}</h2>
                <Badge variant={VARIANT[w.status] ?? 'default'}>{w.status}</Badge>
                <span className="text-xs text-[#A8A8AB]">{w.assignee?.name ?? 'unassigned'}</span>
                <span className="ml-auto text-xs text-[#6B6B6E]">{w.updated_at ?? ''}</span>
                {!CLOSED.has(w.status) && (
                  <Button size="xs" variant="danger" disabled={busy} onClick={() => cancel.mutate(w.id)}>
                    Cancel
                  </Button>
                )}
              </div>
              {w.failure && <p className="mt-1 text-xs text-[#EF4444]">Failure: {w.failure}</p>}
              {w.result && <p className="mt-1 text-xs text-[#A8A8AB]">Result: {w.result}</p>}
              {(w.tasks ?? []).map((t) => (
                <TaskRow key={t.id} item={t} onReview={onReview} busy={busy} />
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
