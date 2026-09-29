/** UI state for a voice session, driven by the gateway's JSON events. Pure, so it is easy to test. */

export type VoicePhase = 'idle' | 'connecting' | 'listening' | 'hearing' | 'transcribing' | 'thinking' | 'speaking';
export type VoiceMode = 'auto' | 'hi' | 'en' | 'mixed';

export interface VoiceUiState {
  phase: VoicePhase;
  partial: string;
  transcript: string;
  language: string | null;
  reply: string;
  error: string | null;
}

export const initialVoiceState: VoiceUiState = {
  phase: 'idle',
  partial: '',
  transcript: '',
  language: null,
  reply: '',
  error: null,
};

export type VoiceEvent = { type: string; [key: string]: unknown };

export function reduceVoice(state: VoiceUiState, ev: VoiceEvent): VoiceUiState {
  switch (ev.type) {
    case 'connecting':
      return { ...initialVoiceState, phase: 'connecting' };
    case 'closed':
      return { ...state, phase: 'idle', partial: '' };
    case 'ready':
    case 'listening':
      return { ...state, phase: 'listening', error: null };
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
      return { ...state, phase: 'listening' };
    case 'completed':
      return { ...state, phase: 'listening' };
    case 'error':
      return { ...state, error: String(ev.message ?? ev.code ?? 'Voice error') };
    default:
      return state;
  }
}
