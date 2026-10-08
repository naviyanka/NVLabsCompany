/**
 * Tool Effects API module — durable tool calls awaiting an operator decision.
 *
 * The backend (`src/nexus/api/routes/tool_effects.py`) lists the effects a
 * non-idempotent tool call left ambiguous, and records a human administrator's
 * decision about what actually happened in the external system. Both routes
 * refuse non-human principals server-side; this module only shapes the calls.
 *
 * The list response is a bounded model — identifiers and states only, never
 * arguments, results, errors or credentials. The cursor is the server's keyset
 * cursor: pass back exactly what `next_cursor` returned, never synthesize one,
 * and treat `null` as the last page. There are no other filters; the company
 * scope comes from the session and the page size is clamped to the server's
 * 1..500 window here so an out-of-range request is never sent.
 */

import { apiClient } from '@/api/client';

/** The exact decisions the server supports (`ResolveBody.outcome`). */
export const RESOLUTION_OUTCOMES = ['applied', 'not_applied'] as const;
export type ResolutionOutcome = (typeof RESOLUTION_OUTCOMES)[number];

/** The ledger states that await a decision (`nexus.tools.effects.list_open`). */
export const OPEN_EFFECT_STATUSES = ['ambiguous', 'manual_recovery_required'] as const;
export type OpenEffectStatus = (typeof OPEN_EFFECT_STATUSES)[number];

/** Exactly the fields the bounded list model returns. Nothing else exists to render. */
export interface ToolEffectItem {
  id: string;
  turn_id: string;
  round_index: number;
  invocation_index: number;
  tool_name: string;
  effect_class: string;
  status: OpenEffectStatus | string;
  attempt_count: number;
  arguments_digest: string;
  created_at: string;
}

export interface OpenEffectsPage {
  items: ToolEffectItem[];
  next_cursor: string | null;
}

export interface ResolveEffectBody {
  outcome: ResolutionOutcome;
  reason: string;
  note?: string | null;
}

export interface ResolveEffectResponse {
  id: string;
  status: string;
  outcome: ResolutionOutcome;
}

/** The server clamps any requested limit into 1..500 (`list_open`). */
export const MAX_PAGE_LIMIT = 500;

/** The server's default page size, used so a page is an explicit, known quantity. */
export const PAGE_SIZE = 100;

/** One page of effects awaiting a decision, oldest first; `cursor` must be a returned `next_cursor`. */
export async function listOpenEffects(
  cursor: string | null = null,
  limit: number = PAGE_SIZE
): Promise<OpenEffectsPage> {
  const clamped = Math.min(Math.max(1, Math.floor(limit)), MAX_PAGE_LIMIT);
  return apiClient.get<OpenEffectsPage>('/api/v1/tool-effects/open', {
    limit: clamped,
    ...(cursor ? { cursor } : {}),
  });
}

/**
 * Record whether an ambiguous effect was applied. Human admin only on the
 * server; audited there. A foreign or missing effect is indistinguishable
 * (404), and a decision already recorded answers 409.
 */
export function resolveEffect(
  effectId: string,
  body: ResolveEffectBody
): Promise<ResolveEffectResponse> {
  return apiClient.post<ResolveEffectResponse>(
    `/api/v1/tool-effects/${encodeURIComponent(effectId)}/resolve`,
    body
  );
}
