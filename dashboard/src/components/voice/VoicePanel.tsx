/**
 * VoicePanel — talk to the CEO. Push-to-talk by default; hands-free is an opt-in setting.
 * The microphone opens only after the user presses a button. Transcripts are stored
 * as normal chat messages; raw audio is never stored. A dropped session reconnects with a
 * fresh ticket and bounded backoff; it never replays audio, transcripts or turns.
 */

import { useCallback, useEffect, useReducer, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, Brain, Ear, FileText, Hand, Loader2, Mic, Square, Volume2, WifiOff } from 'lucide-react';
import {
  createVoiceSession,
  endVoiceSession,
  fetchVoiceStatus,
  VoiceClient,
  type VoiceInfo,
  type VoiceStatus,
} from '@/lib/voice/voiceClient';
import { FAILURE_TEXT, micFailure, savedDevice } from '@/lib/voice/micPreflight';
import {
  autoReconnect,
  backoffMs,
  FINAL_CODES,
  initialVoiceState,
  MAX_RECONNECTS,
  reduceVoice,
  type VoiceEvent,
  type VoiceMode,
  type VoicePhase,
} from '@/lib/voice/voiceState';
import { MicCheck } from './MicCheck';

const MODES: { value: VoiceMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'hi', label: 'Hindi' },
  { value: 'en', label: 'English' },
  { value: 'mixed', label: 'Mixed' },
];
const HANDS_FREE_KEY = 'nexus.voice.handsFree';
const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FFB020]';

// Each phase has its own icon and words, so colour is never the only signal.
const PHASES: Record<VoicePhase, { label: string; icon: ReactNode }> = {
  offline: { label: 'Offline', icon: <WifiOff size={12} /> },
  connecting: { label: 'Connecting…', icon: <Loader2 size={12} className="motion-safe:animate-spin" /> },
  listening: { label: 'Listening', icon: <Mic size={12} /> },
  hearing: { label: 'Hearing you…', icon: <Ear size={12} /> },
  transcribing: { label: 'Transcribing…', icon: <FileText size={12} /> },
  thinking: { label: 'Thinking…', icon: <Brain size={12} /> },
  speaking: { label: 'Speaking', icon: <Volume2 size={12} /> },
  interrupted: { label: 'Interrupted', icon: <Hand size={12} /> },
  error: { label: 'Error', icon: <AlertTriangle size={12} /> },
};

function readHandsFree(): boolean {
  try {
    return localStorage.getItem(HANDS_FREE_KEY) === '1';
  } catch {
    return false;
  }
}

function voiceLabel(v: VoiceInfo): string {
  const notes = [
    v.restricted ? `non-commercial · ${v.license ?? 'restricted'}` : null,
    !v.installed ? 'not installed' : null,
    v.restricted && !v.selectable ? 'disabled' : null,
  ].filter(Boolean);
  return notes.length ? `${v.id} (${notes.join(', ')})` : v.id;
}

const usable = (v: VoiceInfo) => v.installed && v.selectable;

function VoiceSelect({ label, lang, voices, value, onChange }: { label: string; lang: 'en' | 'hi'; voices: VoiceInfo[]; value: string; onChange: (v: string) => void }) {
  const options = voices.filter((v) => v.language === lang);
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={`bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1 max-w-[14rem] ${FOCUS}`}>
      {!options.some(usable) && <option value="">No {lang === 'hi' ? 'Hindi' : 'English'} voice set up</option>}
      {options.map((v) => (
        <option key={v.id} value={v.id} disabled={!usable(v)}>
          {voiceLabel(v)}
        </option>
      ))}
    </select>
  );
}

export function VoicePanel({ onTextFallback, ceoId }: { onTextFallback?: () => void; ceoId?: string }) {
  const [ui, dispatch] = useReducer(reduceVoice, initialVoiceState);
  const [mode, setMode] = useState<VoiceMode>('auto');
  const [voiceEn, setVoiceEn] = useState('');
  const [voiceHi, setVoiceHi] = useState('');
  const [catalog, setCatalog] = useState<VoiceStatus | null>(null);
  const [handsFree, setHandsFree] = useState(readHandsFree);
  const [deviceId, setDeviceId] = useState(savedDevice);
  const [micError, setMicError] = useState<string | null>(null);
  const client = useRef<VoiceClient | null>(null);
  const sessionId = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attempt = useRef(0);
  const lastCode = useRef<string | null>(null);
  const userEnded = useRef(false);
  const pressed = useRef(false);
  const connectRef = useRef<(auto: boolean) => Promise<void>>(async () => {});
  const settings = useRef({ mode, voiceEn, voiceHi, handsFree, deviceId });
  settings.current = { mode, voiceEn, voiceHi, handsFree, deviceId };

  const connected = ui.open;
  const finalStop = FINAL_CODES.has(ui.errorCode ?? '');
  const voices = catalog?.voices ?? [];

  useEffect(() => {
    let live = true;
    fetchVoiceStatus()
      .then((s) => {
        if (!live) return;
        setCatalog(s);
        const pick = (lang: 'en' | 'hi') => {
          const ok = s.voices.filter((v) => v.language === lang && usable(v));
          return ok.find((v) => v.id === s.default_voices[lang])?.id ?? ok[0]?.id ?? '';
        };
        setVoiceEn(pick('en'));
        setVoiceHi(pick('hi'));
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const release = (id: string | null) => {
    if (id) void endVoiceSession(id).catch(() => {});
  };

  const teardown = () => {
    clearTimer();
    client.current?.close();
    client.current = null;
  };

  useEffect(
    () => () => {
      userEnded.current = true;
      teardown();
      release(sessionId.current);
    },
    [],
  );

  const scheduleRetry = () => {
    attempt.current += 1;
    dispatch({ type: 'reconnecting', attempt: attempt.current });
    timer.current = setTimeout(() => void connectRef.current(true), backoffMs(attempt.current - 1));
  };

  /** `auto` reconnects never open the microphone unless hands-free was turned on. */
  const connect = useCallback(async (auto: boolean) => {
    clearTimer();
    userEnded.current = false;
    lastCode.current = null;
    setMicError(null);
    dispatch({ type: 'connecting' });
    const s = settings.current;
    try {
      const session = await createVoiceSession(s.mode, s.voiceEn, s.voiceHi); // a fresh ticket every time
      sessionId.current = session.voice_session_id;
      if (ceoId && session.ceo && session.ceo.id !== ceoId) {
        release(session.voice_session_id);
        dispatch({ type: 'error', code: 'CEO_CHANGED', message: 'The CEO changed. Reopen this chat with the current CEO.' });
        dispatch({ type: 'closed' });
        return;
      }
      const c: VoiceClient = new VoiceClient((ev: VoiceEvent) => {
        if (client.current !== c) return; // an old session: ignore
        dispatch(ev);
        if (ev.type === 'ready' || ev.type === 'listening') attempt.current = 0;
        if (ev.type === 'error' && typeof ev.code === 'string') lastCode.current = ev.code;
        if (ev.type === 'closed' && !userEnded.current && autoReconnect(lastCode.current, attempt.current)) scheduleRetry();
      });
      client.current = c;
      await c.open(session);
      if (!auto || s.handsFree) await c.enableMic(s.deviceId); // inside the click, or hands-free opted in
      if (s.handsFree) c.setOpenMic(true);
    } catch (err) {
      teardown();
      const failure = micFailure(err);
      if (auto && failure === 'failed' && autoReconnect(null, attempt.current)) return scheduleRetry();
      dispatch({ type: 'failed', message: failure === 'failed' && err instanceof Error ? err.message : FAILURE_TEXT[failure] });
    }
  }, [ceoId]);
  connectRef.current = connect;

  const disconnect = () => {
    userEnded.current = true;
    teardown();
    release(sessionId.current);
    sessionId.current = null;
    attempt.current = 0;
    dispatch({ type: 'ended' });
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
    if (client.current?.micOn || !on) client.current?.setOpenMic(on);
  };

  const press = () => {
    const c = client.current;
    if (!c || pressed.current) return;
    pressed.current = true;
    if (c.micOn) return c.startTalking();
    // Mic closed after a reconnect: this press is the user's gesture that opens it.
    void c
      .enableMic(deviceId)
      .then(() => pressed.current && c.startTalking())
      .catch((err) => {
        pressed.current = false;
        setMicError(FAILURE_TEXT[micFailure(err)]);
      });
  };
  const releaseKey = () => {
    if (!pressed.current) return;
    pressed.current = false;
    client.current?.stopTalking();
  };

  const phase = ui.reconnect ? null : PHASES[ui.phase];
  const error = micError ?? ui.error;
  const talkKey = (e: { key: string; repeat?: boolean; preventDefault: () => void }, down: boolean) => {
    if (e.key !== ' ' && e.key !== 'Enter') return;
    e.preventDefault(); // a native button would fire a click on key-up
    if (down) {
      if (!e.repeat) press();
    } else releaseKey();
  };

  return (
    <div aria-label="Voice" className="border-t border-white/[0.08] p-3 space-y-2 text-[11px] text-[#A8A8AB]">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Language mode" value={mode} onChange={(e) => change({ mode: e.target.value as VoiceMode })} className={`bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1 ${FOCUS}`}>
          {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <VoiceSelect label="English voice" lang="en" voices={voices} value={voiceEn} onChange={(v) => change({ en: v })} />
        <VoiceSelect label="Hindi voice" lang="hi" voices={voices} value={voiceHi} onChange={(v) => change({ hi: v })} />
        <label className="flex items-center gap-1 ml-auto">
          <input type="checkbox" checked={handsFree} onChange={(e) => toggleHandsFree(e.target.checked)} className={FOCUS} /> Hands-free
        </label>
      </div>
      {catalog && !voices.some((v) => v.language === 'hi' && usable(v)) && (
        <p>Hindi speech is not set up: no commercially licensed Hindi voice is installed (live check required). Hindi replies stay text-only.</p>
      )}
      {catalog && voices.some((v) => v.restricted) && !catalog.allow_noncommercial_models && (
        <p>Non-commercial voices are disabled. An operator can enable them with NEXUS_VOICE_ALLOW_NONCOMMERCIAL_MODELS.</p>
      )}

      {!connected && <MicCheck deviceId={deviceId} onDevice={setDeviceId} />}

      <div className="flex items-center gap-2">
        {!connected ? (
          <>
            <button
              type="button"
              onClick={() => { attempt.current = 0; void connect(false); }}
              disabled={ui.phase === 'connecting' || finalStop}
              className={`flex items-center gap-1 px-3 py-2 rounded-[6px] bg-[#FFB020] text-black disabled:opacity-40 ${FOCUS}`}
            >
              <Mic size={12} /> {ui.canRetry && !finalStop ? 'Retry' : 'Start voice'}
            </button>
            {ui.reconnect && <button type="button" onClick={disconnect} className={`px-2 py-2 hover:text-white ${FOCUS}`}>Cancel</button>}
          </>
        ) : (
          <>
            {!handsFree && (
              <button
                type="button"
                aria-label="Hold to talk"
                onPointerDown={press}
                onPointerUp={releaseKey}
                onPointerCancel={releaseKey}
                onPointerLeave={releaseKey}
                onBlur={releaseKey}
                onKeyDown={(e) => talkKey(e, true)}
                onKeyUp={(e) => talkKey(e, false)}
                className={`flex items-center gap-1 px-3 py-2 rounded-[6px] bg-[#FFB020] text-black ${FOCUS}`}
              >
                <Mic size={12} /> Hold to talk
              </button>
            )}
            <button type="button" aria-label="Stop" onClick={() => client.current?.stop()} className={`flex items-center gap-1 px-3 py-2 rounded-[6px] border border-red-400/50 text-red-300 ${FOCUS}`}>
              <Square size={12} /> Stop
            </button>
            <button type="button" onClick={disconnect} className={`px-2 py-2 text-[#9C9C9F] hover:text-white ${FOCUS}`}>End voice</button>
          </>
        )}
        {/* One short label per state change; audio frames are never announced. */}
        <span role="status" aria-live="polite" className="ml-auto flex items-center gap-1 font-mono">
          {phase ? (
            <>
              <span aria-hidden="true">{phase.icon}</span>
              {phase.label}
            </>
          ) : (
            <>Reconnecting (attempt {ui.reconnect!.attempt} of {MAX_RECONNECTS})…</>
          )}
        </span>
        {connected && <Mic size={10} className="text-[#FFB020]" aria-label="Microphone on" />}
      </div>

      {(ui.partial || ui.transcript) && (
        <p className="font-mono text-[#F2F1EE]" aria-label="Transcript">
          {ui.partial ? <span className="opacity-60">{ui.partial}</span> : ui.transcript}
          {ui.language && !ui.partial && <span className="ml-2 text-[#6B6B6E]">[{ui.language}]</span>}
        </p>
      )}
      {ui.notice && <p>{ui.notice}</p>}
      {error && (
        <p role="alert" className="text-red-400">
          {error}{' '}
          {onTextFallback && <button type="button" onClick={onTextFallback} className={`underline ${FOCUS}`}>Type instead</button>}
        </p>
      )}
      <p className="text-[10px] text-[#6B6B6E]">Your words are saved as normal chat messages. Raw audio is processed on this machine and never stored.</p>
    </div>
  );
}
