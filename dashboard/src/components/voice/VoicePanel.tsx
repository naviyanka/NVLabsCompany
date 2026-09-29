/**
 * VoicePanel — talk to the CEO. Push-to-talk by default; hands-free is an opt-in setting.
 * The microphone opens only after the user presses the button. Transcripts are stored
 * as normal chat messages; raw audio is never stored.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { createVoiceSession, VoiceClient } from '@/lib/voice/voiceClient';
import { initialVoiceState, reduceVoice, type VoiceMode, type VoiceUiState } from '@/lib/voice/voiceState';

const MODES: { value: VoiceMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'hi', label: 'Hindi' },
  { value: 'en', label: 'English' },
  { value: 'mixed', label: 'Mixed' },
];
const VOICES_EN = [{ id: 'en_US-lessac-medium', label: 'English · Lessac' }, { id: 'en_US-ryan-medium', label: 'English · Ryan' }];
const VOICES_HI = [{ id: 'hi_IN-pratham-medium', label: 'Hindi · Pratham' }, { id: 'hi_IN-priyamvada-medium', label: 'Hindi · Priyamvada' }];
const HANDS_FREE_KEY = 'nexus.voice.handsFree';

const PHASE_LABEL: Record<VoiceUiState['phase'], string> = {
  idle: 'Not connected',
  connecting: 'Connecting…',
  listening: 'Listening',
  hearing: 'Hearing you…',
  transcribing: 'Transcribing…',
  thinking: 'Thinking…',
  speaking: 'Speaking',
};

function micMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Microphone permission was denied. Allow it in the browser and try again.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.';
  return err instanceof Error ? err.message : 'Voice could not start.';
}

function readHandsFree(): boolean {
  try {
    return localStorage.getItem(HANDS_FREE_KEY) === '1';
  } catch {
    return false;
  }
}

export function VoicePanel({ onTextFallback }: { onTextFallback?: () => void }) {
  const [ui, dispatch] = useReducer(reduceVoice, initialVoiceState);
  const [mode, setMode] = useState<VoiceMode>('auto');
  const [voiceEn, setVoiceEn] = useState(VOICES_EN[0]!.id);
  const [voiceHi, setVoiceHi] = useState(VOICES_HI[0]!.id);
  const [handsFree, setHandsFree] = useState(readHandsFree);
  const [micError, setMicError] = useState<string | null>(null);
  const client = useRef<VoiceClient | null>(null);
  const connected = ui.phase !== 'idle' && ui.phase !== 'connecting';

  useEffect(() => () => client.current?.close(), []);

  const connect = useCallback(async () => {
    setMicError(null);
    dispatch({ type: 'connecting' });
    try {
      const session = await createVoiceSession(mode, voiceEn, voiceHi);
      const c = new VoiceClient(dispatch);
      client.current = c;
      await c.open(session);
      await c.enableMic(); // runs inside the user's click
      if (handsFree) c.setOpenMic(true);
    } catch (err) {
      client.current?.close();
      client.current = null;
      dispatch({ type: 'closed' });
      setMicError(micMessage(err));
    }
  }, [mode, voiceEn, voiceHi, handsFree]);

  const disconnect = () => {
    client.current?.close();
    client.current = null;
  };

  const change = (next: { mode?: VoiceMode; en?: string; hi?: string }) => {
    const m = next.mode ?? mode;
    const en = next.en ?? voiceEn;
    const hi = next.hi ?? voiceHi;
    setMode(m);
    setVoiceEn(en);
    setVoiceHi(hi);
    client.current?.configure(m, en, hi);
  };

  const toggleHandsFree = (on: boolean) => {
    setHandsFree(on);
    try {
      localStorage.setItem(HANDS_FREE_KEY, on ? '1' : '0');
    } catch {
      /* setting just will not persist */
    }
    client.current?.setOpenMic(on);
  };

  const error = micError ?? ui.error;

  return (
    <div aria-label="Voice" className="border-t border-white/[0.08] p-3 space-y-2 text-[11px] text-[#A8A8AB]">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Language mode" value={mode} onChange={(e) => change({ mode: e.target.value as VoiceMode })} className="bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1">
          {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <select aria-label="English voice" value={voiceEn} onChange={(e) => change({ en: e.target.value })} className="bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1">
          {VOICES_EN.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <select aria-label="Hindi voice" value={voiceHi} onChange={(e) => change({ hi: e.target.value })} className="bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1">
          {VOICES_HI.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <label className="flex items-center gap-1 ml-auto">
          <input type="checkbox" checked={handsFree} onChange={(e) => toggleHandsFree(e.target.checked)} /> Hands-free
        </label>
      </div>

      <div className="flex items-center gap-2">
        {!connected ? (
          <button type="button" onClick={() => void connect()} disabled={ui.phase === 'connecting'} className="flex items-center gap-1 px-3 py-2 rounded-[6px] bg-[#FFB020] text-black disabled:opacity-40">
            <Mic size={12} /> Start voice
          </button>
        ) : (
          <>
            {!handsFree && (
              <button
                type="button"
                aria-label="Hold to talk"
                onPointerDown={() => client.current?.startTalking()}
                onPointerUp={() => client.current?.stopTalking()}
                onPointerLeave={() => ui.phase === 'hearing' && client.current?.stopTalking()}
                onKeyDown={(e) => e.key === ' ' && !e.repeat && client.current?.startTalking()}
                onKeyUp={(e) => e.key === ' ' && client.current?.stopTalking()}
                className="flex items-center gap-1 px-3 py-2 rounded-[6px] bg-[#FFB020] text-black"
              >
                <Mic size={12} /> Hold to talk
              </button>
            )}
            <button type="button" aria-label="Stop" onClick={() => client.current?.stop()} className="flex items-center gap-1 px-3 py-2 rounded-[6px] border border-red-400/50 text-red-300">
              <Square size={12} /> Stop
            </button>
            <button type="button" onClick={disconnect} className="px-2 py-2 text-[#9C9C9F] hover:text-white">End voice</button>
          </>
        )}
        <span role="status" aria-live="polite" className="ml-auto font-mono">
          {connected && <Mic size={10} className="inline mr-1 text-[#FFB020]" aria-label="Microphone on" />}
          {PHASE_LABEL[ui.phase]}
        </span>
      </div>

      {(ui.partial || ui.transcript) && (
        <p className="font-mono text-[#F2F1EE]" aria-label="Transcript">
          {ui.partial ? <span className="opacity-60">{ui.partial}</span> : ui.transcript}
          {ui.language && !ui.partial && <span className="ml-2 text-[#6B6B6E]">[{ui.language}]</span>}
        </p>
      )}
      {error && (
        <p role="alert" className="text-red-400">
          {error}{' '}
          {onTextFallback && <button type="button" onClick={onTextFallback} className="underline">Type instead</button>}
        </p>
      )}
      <p className="text-[10px] text-[#6B6B6E]">Your words are saved as normal chat messages. Raw audio is processed on this machine and never stored.</p>
    </div>
  );
}
