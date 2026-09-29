/** UI state for a voice session, driven by the gateway's JSON events. Pure, so it is easy to test. */

export type VoicePhase =
  | 'offline'
  | 'connecting'
  | 'listening'
  | 'hearing'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'interrupted'
  | 'error';
export type VoiceMode = 'auto' | 'hi' | 'en' | 'mixed';

export interface VoiceUiState {
  phase: VoicePhase;
  /** True while a session socket is up (even in the error phase). */
  open: boolean;
  partial: string;
  transcript: string;
  language: string | null;
  reply: string;
  error: string | null;
  errorCode: string | null;
  notice: string | null;
  /** Set while waiting to reconnect automatically. */
  reconnect: { attempt: number; max: number } | null;
  /** A session was tried and ended: show Retry. */
  canRetry: boolean;
}

export const initialVoiceState: VoiceUiState = {
  phase: 'offline',
  open: false,
  partial: '',
  transcript: '',
  language: null,
  reply: '',
  error: null,
  errorCode: null,
  notice: null,
  reconnect: null,
  canRetry: false,
};

export type VoiceEvent = { type: string; [key: string]: unknown };

/** Closes that a new session cannot fix: never retried, whatever the user presses. */
export const FINAL_CODES = new Set(['CEO_CHANGED', 'SESSION_REVOKED', 'BAD_PROTOCOL', 'VOICE_DISABLED', 'HUMAN_REQUIRED']);
/** Closes that are transient: retried automatically with backoff. */
export const TRANSIENT_CODES = new Set(['WORKER_UNAVAILABLE', 'SHARED_STATE_UNAVAILABLE', 'INTERNAL']);
export const MAX_RECONNECTS = 4;

/** 1 s, 2 s, 4 s, then capped at 8 s. */
export const backoffMs = (attempt: number): number => Math.min(1000 * 2 ** attempt, 8000);

/** Reconnect automatically only after an abnormal drop (no reason given) or a transient error. */
export function autoReconnect(code: string | null, attempt: number): boolean {
  if (attempt >= MAX_RECONNECTS) return false;
  return code === null || TRANSIENT_CODES.has(code);
}

export function reduceVoice(state: VoiceUiState, ev: VoiceEvent): VoiceUiState {
  switch (ev.type) {
    case 'connecting':
      return { ...initialVoiceState, phase: 'connecting', canRetry: state.canRetry, reconnect: state.reconnect };
    case 'reconnecting':
      return { ...state, phase: 'offline', open: false, reconnect: { attempt: Number(ev.attempt), max: MAX_RECONNECTS } };
    case 'ended': // the user ended it: back to a clean start
      return { ...initialVoiceState };
    case 'closed':
      return { ...state, phase: 'offline', open: false, partial: '', canRetry: true };
    case 'ready':
    case 'listening':
      return { ...state, phase: 'listening', open: true, error: null, errorCode: null, reconnect: null };
    case 'speech_started':
      return { ...state, phase: 'hearing', partial: '', reply: '' };
    case 'partial':
      return { ...state, partial: String(ev.text ?? '') };
    case 'speech_ended':
    case 'transcribing':
      return { ...state, phase: 'transcribing' };
    case 'transcript':
      return { ...state, transcript: String(ev.text ?? ''), language: (ev.language as string) ?? null, partial: '' };
    case 'thinking':
      return { ...state, phase: 'thinking', reply: '' };
    case 'text_delta':
      return { ...state, reply: state.reply + String(ev.text ?? '') };
    case 'speaking':
      return { ...state, phase: 'speaking' };
    case 'interrupted':
      return { ...state, phase: 'interrupted' };
    case 'completed':
      return { ...state, phase: 'listening' };
    case 'notice':
      return { ...state, notice: String(ev.message ?? ev.code ?? '') };
    case 'error':
      return {
        ...state,
        phase: 'error',
        error: String(ev.message ?? ev.code ?? 'Voice error'),
        errorCode: typeof ev.code === 'string' ? ev.code : null,
      };
    case 'failed':
      // No session at all (network, permission): offline with a message.
      return { ...state, phase: 'offline', open: false, error: String(ev.message ?? 'Voice could not start.'), canRetry: true, reconnect: null };
    default:
      return state;
  }
}
