import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Lock, ShieldAlert } from 'lucide-react';

import { ApiClientError } from '@/api/client';
import {
  listOpenEffects,
  resolveEffect,
  PAGE_SIZE,
  type ResolutionOutcome,
  type ToolEffectItem,
} from '@/api/toolEffects';
import { Badge } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { EmptyState } from '@/components/common/EmptyState';
import { Modal } from '@/components/common/Modal';
import { useAuth } from '@/contexts/AuthContext';

/**
 * Operator page for durable tool effects that need a person's decision.
 *
 * A non-idempotent tool call whose outcome is unknown is never rerun by the
 * platform; an administrator verifies the external system and records what
 * actually happened. The backend owns every rule this page obeys: the list is
 * its bounded model (identifiers and states only — never arguments, results,
 * errors or credentials), the cursor is its keyset cursor, and the two
 * decisions are the only ones it accepts. Hiding this page from non-admins is
 * convenience, not authorization; the routes enforce human-admin-only access
 * server-side.
 */

interface Notice {
  tone: 'success' | 'error';
  text: string;
}

/**
 * What a failed resolve means to the operator. The 409 and 404 texts come
 * from fixed backend state messages (an `EffectStateError` string, or the
 * indistinguishable "not found"), never from external error output.
 */
function decisionErrorFeedback(error: unknown): { text: string; closeDialog: boolean } {
  if (error instanceof ApiClientError) {
    if (error.status === 401) {
      return {
        text: 'Your session has expired. Sign in again to record a decision.',
        closeDialog: false,
      };
    }
    if (error.status === 403) {
      return {
        text:
          'You do not have permission to record recovery decisions. ' +
          'This page is limited to active human administrators.',
        closeDialog: false,
      };
    }
    if (error.status === 404) {
      return {
        text:
          'The server has no such effect awaiting a decision — it may have been resolved ' +
          'already or belong to another company, and by design the server does not say ' +
          'which. The list has been refreshed.',
        closeDialog: true,
      };
    }
    if (error.status === 409) {
      return {
        text:
          'Another decision was recorded first: the server reports the effect is no longer ' +
          `awaiting recovery (${error.detail}). The list has been refreshed.`,
        closeDialog: true,
      };
    }
    if (error.status === 422) {
      return {
        text:
          'The server rejected the decision as invalid. Provide a reason of 1–500 ' +
          'characters and a note of at most 500.',
        closeDialog: false,
      };
    }
  }
  return {
    text: 'Recording the decision failed. Nothing was changed — try again.',
    closeDialog: false,
  };
}

function loadErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.status === 401) return 'Your session has expired. Sign in again.';
    if (error.status === 403) {
      return (
        'You do not have permission to view tool effects. ' +
        'This page is limited to active human administrators.'
      );
    }
  }
  return 'Failed to load unresolved tool effects.';
}

function statusLabel(status: string): string {
  return status === 'manual_recovery_required' ? 'manual recovery required' : status;
}

export function ToolEffectRecovery() {
  const { isAdmin } = useAuth();
  const queryClient = useQueryClient();

  // Server-cursor state: `cursor` is the keyset position of the page on screen
  // (null for the first), and pageHistory remembers the exact cursors earlier
  // pages were fetched with, so Previous refetches the page the server served.
  const [cursor, setCursor] = useState<string | null>(null);
  const [pageHistory, setPageHistory] = useState<(string | null)[]>([]);

  const [selected, setSelected] = useState<ToolEffectItem | null>(null);
  const [outcome, setOutcome] = useState<ResolutionOutcome>('applied');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [resolving, setResolving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  // One resolve in flight at a time; the ref also guards the confirm handler
  // between the click and the state update, so a double submission can never
  // reach the API.
  const resolvingRef = useRef(false);
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogContainerRef = useRef<HTMLDivElement | null>(null);
  const dialogErrorRef = useRef<HTMLDivElement | null>(null);
  const noticeRef = useRef<HTMLParagraphElement | null>(null);

  const query = useQuery({
    queryKey: ['tool-effects', 'open', cursor],
    queryFn: () => listOpenEffects(cursor, PAGE_SIZE),
    enabled: isAdmin,
  });

  const items = query.data?.items ?? [];
  const nextCursor = query.data?.next_cursor ?? null;

  // A page the server emptied (its rows were resolved meanwhile) is not a
  // state to stare at: step back to the previous cursor, if there is one.
  useEffect(() => {
    if (isAdmin && query.data && query.data.items.length === 0 && pageHistory.length > 0) {
      const previous = pageHistory[pageHistory.length - 1] ?? null;
      setPageHistory((history) => history.slice(0, -1));
      setCursor(previous);
    }
  }, [isAdmin, query.data, pageHistory]);

  // Dialog focus: into the dialog when it opens, back to the trigger when it
  // closes — unless the refetch removed that row, in which case the success or
  // error notice takes focus below.
  useEffect(() => {
    if (selected) {
      dialogContainerRef.current?.focus();
    } else if (lastTriggerRef.current?.isConnected) {
      lastTriggerRef.current.focus();
    }
  }, [selected]);

  useEffect(() => {
    if (dialogError) dialogErrorRef.current?.focus();
  }, [dialogError]);

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  const openDialog = (item: ToolEffectItem, trigger: HTMLButtonElement) => {
    lastTriggerRef.current = trigger;
    setSelected(item);
    // Default to "applied": for a non-idempotent effect, marking it applied
    // (no rerun) is the fail-safe answer to a careless confirm — the ledger's
    // own principle is that an unknown effect is never rerun.
    setOutcome('applied');
    setReason('');
    setNote('');
    setDialogError(null);
    setNotice(null);
  };

  const closeDialog = () => {
    setSelected(null);
    setDialogError(null);
  };

  const submitDecision = async () => {
    if (!selected || resolvingRef.current) return;
    if (reason.trim().length === 0) {
      setDialogError(
        'A reason is required: describe what you checked in the external system and what you found.'
      );
      return;
    }
    resolvingRef.current = true;
    setResolving(true);
    setDialogError(null);
    try {
      const trimmedNote = note.trim();
      const result = await resolveEffect(selected.id, {
        outcome,
        reason: reason.trim(),
        note: trimmedNote ? trimmedNote : null,
      });
      await queryClient.invalidateQueries({ queryKey: ['tool-effects'] });
      setSelected(null);
      setNotice({
        tone: 'success',
        text:
          result.outcome === 'applied'
            ? 'Decision recorded: the effect was applied. The call is settled as succeeded in the ledger.'
            : 'Decision recorded: the effect was not applied. The call is settled as failed in the ledger.',
      });
    } catch (error) {
      const feedback = decisionErrorFeedback(error);
      if (feedback.closeDialog) {
        setSelected(null);
        setNotice({ tone: 'error', text: feedback.text });
        void queryClient.invalidateQueries({ queryKey: ['tool-effects'] });
      } else {
        setDialogError(feedback.text);
      }
    } finally {
      resolvingRef.current = false;
      setResolving(false);
    }
  };

  const goNext = () => {
    if (!nextCursor) return;
    setPageHistory((history) => [...history, cursor]);
    setCursor(nextCursor);
  };

  const goPrevious = () => {
    if (pageHistory.length === 0) return;
    const previous = pageHistory[pageHistory.length - 1] ?? null;
    setPageHistory((history) => history.slice(0, -1));
    setCursor(previous);
  };

  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeading />
        <Card>
          <div className="flex items-start gap-3">
            <Lock className="w-5 h-5 text-[#6B6B6E] shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h2 className="text-sm font-medium text-[#F2F1EE]">Administrator access required</h2>
              <p className="text-xs text-[#9C9C9F] leading-relaxed">
                Recovery decisions about ambiguous tool effects are recorded by active human
                administrators. Your session does not carry the administrator role, so no list
                was loaded. The API enforces this independently of this page.
              </p>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeading />
      <p className="text-xs font-mono text-[#6B6B6E] max-w-3xl leading-relaxed -mt-3">
        A non-idempotent tool call whose outcome is unknown — a timeout, a lost connection, an
        interrupted run — is never retried automatically. Verify the effect in the external
        system, then record what actually happened; the decision is audited and is the only way
        such a call becomes runnable again. Only identifiers and states are shown here, never
        tool arguments, results, errors or credentials.
      </p>

      {notice && (
        <p
          ref={noticeRef}
          tabIndex={-1}
          role={notice.tone === 'success' ? 'status' : 'alert'}
          className={`p-3 rounded-[8px] border text-xs font-mono focus:outline-none focus-visible:ring-1 focus-visible:ring-[#FFB020]/60 ${
            notice.tone === 'success'
              ? 'bg-[#22C55E]/10 border-[#22C55E]/20 text-[#22C55E]'
              : 'bg-[#EF4444]/10 border-[#EF4444]/20 text-[#EF4444]'
          }`}
        >
          {notice.text}
        </p>
      )}

      <section aria-busy={query.isFetching} className="space-y-3">
        {query.isLoading ? (
          <p role="status" className="flex items-center gap-2 p-6 text-xs font-mono text-[#A8A8AB]">
            <span className="w-4 h-4 border-2 border-[#FFB020] border-t-transparent rounded-full animate-spin" />
            Loading unresolved effects…
          </p>
        ) : query.error ? (
          <div
            role="alert"
            className="flex items-center gap-3 p-3 rounded-[8px] bg-[#EF4444]/10 border border-[#EF4444]/20 text-xs font-mono text-[#EF4444]"
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{loadErrorMessage(query.error)}</span>
            <Button variant="secondary" size="xs" onClick={() => void query.refetch()}>
              Retry
            </Button>
          </div>
        ) : (
          <>
            {items.length === 0 ? (
              <EmptyState
                title="No unresolved effects"
                description="Every recorded tool effect has a known outcome. When a call finishes ambiguously, it appears here for a decision."
                icon={<CheckCircle2 size={24} />}
              />
            ) : (
            <div className="w-full overflow-x-auto border border-white/[0.06] rounded-[8px]">
              <table className="w-full text-left text-sm border-collapse">
                <caption className="sr-only">
                  Tool effects awaiting an operator decision, oldest first
                </caption>
                <thead>
                  <tr className="border-b border-white/[0.08] text-xs font-mono text-[#6B6B6E] tracking-wider uppercase bg-[#101012]">
                    <th scope="col" className="px-4 py-3 font-medium select-none">Tool</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">State</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">Slot</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">Attempts</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">Turn</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">Args digest</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none">Discovered</th>
                    <th scope="col" className="px-4 py-3 font-medium select-none text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {items.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-white/[0.04] hover:bg-white/[0.01] transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-[#F2F1EE]">{item.tool_name}</td>
                      <td className="px-4 py-3">
                        <Badge variant={item.status === 'ambiguous' ? 'warning' : 'amber'}>
                          {statusLabel(item.status)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[#A8A8AB]">
                        round {item.round_index} · call {item.invocation_index}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[#A8A8AB]">{item.attempt_count}</td>
                      <td className="px-4 py-3 font-mono text-[11px] text-[#6B6B6E]" title={item.turn_id}>
                        {item.turn_id.slice(0, 8)}…
                      </td>
                      <td
                        className="px-4 py-3 font-mono text-[11px] text-[#6B6B6E]"
                        title={item.arguments_digest}
                      >
                        {item.arguments_digest.slice(0, 10)}…
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-[#6B6B6E]">
                        {new Date(item.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant="secondary"
                          size="xs"
                          disabled={resolving}
                          aria-label={`Review and resolve ${item.tool_name} effect ${item.id}`}
                          onClick={(event) => openDialog(item, event.currentTarget)}
                        >
                          Review
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}

            <div className="flex items-center justify-between">
              <Button
                variant="ghost"
                size="sm"
                onClick={goPrevious}
                disabled={pageHistory.length === 0 || query.isFetching || resolving}
              >
                Previous page
              </Button>
              <span className="text-[11px] font-mono text-[#6B6B6E]" aria-live="polite">
                Page {pageHistory.length + 1}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={goNext}
                disabled={!nextCursor || query.isFetching || resolving}
              >
                Next page
              </Button>
            </div>
          </>
        )}
      </section>

      <Modal
        isOpen={selected !== null}
        onClose={() => {
          if (!resolving) closeDialog();
        }}
        title="Record recovery decision"
      >
        {selected && (
          <div
            ref={dialogContainerRef}
            tabIndex={-1}
            aria-busy={resolving}
            className="space-y-4 focus:outline-none"
          >
            <div className="p-3.5 bg-[#FFB020]/10 border border-[#FFB020]/20 rounded-[8px] flex items-start gap-3">
              <AlertTriangle size={18} className="text-[#FFB020] shrink-0 mt-0.5" />
              <p className="text-xs text-[#FFB020]/90 leading-relaxed">
                Verify the external system before recording. The decision is audited under your
                account, and once recorded the effect leaves the recovery queue — the dashboard
                cannot record another decision for it.
              </p>
            </div>

            <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2 text-xs font-mono">
              <div className="flex justify-between gap-4">
                <span className="text-[#6B6B6E]">Tool:</span>
                <span className="text-[#F2F1EE] font-medium">{selected.tool_name}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#6B6B6E]">State:</span>
                <span className="text-[#A8A8AB]">{statusLabel(selected.status)}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#6B6B6E]">Turn:</span>
                <span className="text-[#A8A8AB] break-all">{selected.turn_id}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#6B6B6E]">Slot:</span>
                <span className="text-[#A8A8AB]">
                  round {selected.round_index} · call {selected.invocation_index}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[#6B6B6E]">Attempts:</span>
                <span className="text-[#A8A8AB]">{selected.attempt_count}</span>
              </div>
            </div>

            <fieldset className="space-y-2" disabled={resolving}>
              <legend className="text-xs font-medium text-[#F2F1EE]">
                What did you find in the external system?
              </legend>
              <label className="flex items-start gap-2.5 p-2.5 bg-[#141416] border border-white/[0.08] rounded-[6px] cursor-pointer hover:border-white/[0.16] transition-colors">
                <input
                  type="radio"
                  name="recovery-outcome"
                  value="applied"
                  checked={outcome === 'applied'}
                  onChange={() => setOutcome('applied')}
                  disabled={resolving}
                  className="mt-0.5 accent-[#FFB020]"
                />
                <span className="text-xs text-[#F2F1EE] leading-relaxed">
                  <span className="font-medium">Applied</span> — the effect happened. The call
                  settles as succeeded; a replay returns this recorded outcome.
                </span>
              </label>
              <label className="flex items-start gap-2.5 p-2.5 bg-[#141416] border border-white/[0.08] rounded-[6px] cursor-pointer hover:border-white/[0.16] transition-colors">
                <input
                  type="radio"
                  name="recovery-outcome"
                  value="not_applied"
                  checked={outcome === 'not_applied'}
                  onChange={() => setOutcome('not_applied')}
                  disabled={resolving}
                  className="mt-0.5 accent-[#FFB020]"
                />
                <span className="text-xs text-[#F2F1EE] leading-relaxed">
                  <span className="font-medium">Not applied</span> — verified that nothing
                  happened. The call settles as failed and the platform may run it again.
                </span>
              </label>
            </fieldset>

            <div className="space-y-1.5">
              <label htmlFor="recovery-reason" className="text-xs font-medium text-[#F2F1EE]">
                Reason (required, 1–500 characters)
              </label>
              <textarea
                id="recovery-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                rows={3}
                disabled={resolving}
                placeholder="What you checked and what you found"
                className="w-full p-2.5 bg-[#101012] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] placeholder:text-[#6B6B6E] focus:outline-none focus:border-[#FFB020]/60 disabled:opacity-40"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="recovery-note" className="text-xs font-medium text-[#F2F1EE]">
                Note (optional, up to 500 characters)
              </label>
              <textarea
                id="recovery-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={500}
                rows={2}
                disabled={resolving}
                placeholder="Anything a future replay should know"
                className="w-full p-2.5 bg-[#101012] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] placeholder:text-[#6B6B6E] focus:outline-none focus:border-[#FFB020]/60 disabled:opacity-40"
              />
            </div>

            {dialogError && (
              <div
                ref={dialogErrorRef}
                tabIndex={-1}
                role="alert"
                className="p-3 rounded-[8px] bg-[#EF4444]/10 border border-[#EF4444]/20 text-xs font-mono text-[#EF4444] focus:outline-none"
              >
                {dialogError}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/[0.08]">
              <Button variant="secondary" size="sm" onClick={closeDialog} disabled={resolving}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" loading={resolving} onClick={() => void submitDecision()}>
                Record decision
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function PageHeading() {
  return (
    <div className="pb-4 border-b border-white/[0.08]">
      <div className="flex items-center gap-2">
        <ShieldAlert className="w-5 h-5 text-[#FFB020]" />
        <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
          Tool Effect Recovery
        </h1>
      </div>
      <p className="text-xs font-mono text-[#6B6B6E] mt-1">
        Human decisions for tool calls whose outcome is ambiguous — manual, audited recovery
      </p>
    </div>
  );
}
