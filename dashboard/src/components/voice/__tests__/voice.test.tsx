import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { floatToPcm16, packUp, parseDown } from '@/lib/voice/protocol';
import { autoReconnect, backoffMs, initialVoiceState, reduceVoice, type VoiceUiState } from '@/lib/voice/voiceState';

const client = vi.hoisted(() => ({
  open: vi.fn(async (_session?: unknown) => {}),
  enableMic: vi.fn(async (_device?: string) => {}),
  startTalking: vi.fn(),
  stopTalking: vi.fn(),
  stop: vi.fn(),
  configure: vi.fn(),
  setOpenMic: vi.fn(),
  close: vi.fn(),
  micOn: true,
  emit: null as null | ((ev: { type: string; [k: string]: unknown }) => void),
}));
const create = vi.hoisted(() => vi.fn());
const status = vi.hoisted(() => vi.fn());
const endSession = vi.hoisted(() => vi.fn(async (_id?: string) => {}));

vi.mock('@/lib/voice/voiceClient', () => ({
  createVoiceSession: create,
  fetchVoiceStatus: status,
  endVoiceSession: endSession,
  CAPTURE_WORKLET: '',
  VoiceClient: class {
    constructor(onEvent: (ev: { type: string }) => void) {
      client.emit = onEvent;
      Object.assign(this, client);
    }
  },
}));

import { VoicePanel } from './../VoicePanel';

const voice = (id: string, language: 'en' | 'hi', extra: object = {}) => ({
  id, language, license: 'MIT', commercial: true, attribution: null,
  restricted: false, selectable: true, installed: true, ...extra,
});
const CATALOG = {
  enabled: true, ceo_id: 'ceo1', worker_reachable: true, allow_noncommercial_models: false,
  default_voices: { en: 'en-free', hi: '' },
  voices: [
    voice('en-free', 'en'),
    voice('en-nc', 'en', { license: 'CC BY-NC-SA 4.0', commercial: false, restricted: true, selectable: false }),
    voice('hi-nc', 'hi', { license: 'CC BY-NC-SA 4.0', commercial: false, restricted: true, selectable: false }),
  ],
};
let ticket = 0;

describe('voice protocol', () => {
  it('packs the 8-byte header and PCM', () => {
    const buf = packUp(5, Int16Array.of(1, -2, 3));
    const v = new DataView(buf);
    expect([v.getUint8(0), v.getUint8(1), v.getUint32(4), buf.byteLength]).toEqual([1, 1, 5, 14]);
    expect(new Int16Array(buf, 8)[1]).toBe(-2);
  });

  it('rejects empty and oversized frames', () => {
    expect(() => packUp(0, new Int16Array(0))).toThrow();
    expect(() => packUp(0, new Int16Array(5000))).toThrow();
  });

  it('parses a down frame and refuses malformed ones', () => {
    const buf = new ArrayBuffer(16);
    const v = new DataView(buf);
    v.setUint8(0, 1);
    v.setUint8(1, 3);
    v.setUint16(2, 1);
    v.setUint32(4, 9);
    v.setUint32(8, 22050);
    new Int16Array(buf, 12).set([7, 8]);
    expect(parseDown(buf)).toMatchObject({ seq: 9, sampleRate: 22050, last: true });
    expect(parseDown(buf)!.pcm[1]).toBe(8);
    expect(parseDown(new ArrayBuffer(12))).toBeNull();
    expect(parseDown(new ArrayBuffer(15))).toBeNull();
  });

  it('clips floats to 16-bit', () => {
    expect(Array.from(floatToPcm16(Float32Array.of(2, -2, 0)))).toEqual([32767, -32768, 0]);
  });
});

describe('voice state', () => {
  const run = (...types: string[]) => types.reduce<VoiceUiState>((s, type) => reduceVoice(s, { type }), initialVoiceState);

  it('walks a full turn', () => {
    expect(initialVoiceState.phase).toBe('offline');
    expect(run('ready').phase).toBe('listening');
    expect(run('ready', 'speech_started').phase).toBe('hearing');
    expect(run('ready', 'speech_started', 'speech_ended', 'transcribing').phase).toBe('transcribing');
    expect(run('ready', 'thinking').phase).toBe('thinking');
    expect(run('ready', 'thinking', 'speaking').phase).toBe('speaking');
    expect(run('ready', 'thinking', 'speaking', 'interrupted').phase).toBe('interrupted');
    expect(run('ready', 'thinking', 'speaking', 'interrupted', 'listening').phase).toBe('listening');
    expect(run('ready', 'closed').phase).toBe('offline');
    expect(reduceVoice(initialVoiceState, { type: 'error', code: 'X', message: 'm' })).toMatchObject({ phase: 'error', errorCode: 'X' });
  });

  it('keeps partials separate from the final transcript and shows the language', () => {
    let s = reduceVoice(initialVoiceState, { type: 'partial', text: 'kal ka' });
    expect(s.partial).toBe('kal ka');
    s = reduceVoice(s, { type: 'transcript', text: 'kal ka status batao', language: 'hi' });
    expect(s).toMatchObject({ partial: '', transcript: 'kal ka status batao', language: 'hi' });
  });

  it('accumulates reply text and reports errors', () => {
    let s = reduceVoice(initialVoiceState, { type: 'text_delta', text: 'All ' });
    s = reduceVoice(s, { type: 'text_delta', text: 'good' });
    expect(s.reply).toBe('All good');
    expect(reduceVoice(s, { type: 'error', message: 'nope' }).error).toBe('nope');
  });

  it('bounds reconnects and refuses final closes', () => {
    expect([0, 1, 2, 3, 4, 5].map(backoffMs)).toEqual([1000, 2000, 4000, 8000, 8000, 8000]);
    expect(autoReconnect(null, 0)).toBe(true);
    expect(autoReconnect('WORKER_UNAVAILABLE', 3)).toBe(true);
    expect(autoReconnect(null, 4)).toBe(false);
    for (const code of ['CEO_CHANGED', 'SESSION_REVOKED', 'BAD_PROTOCOL', 'IDLE_TIMEOUT', 'RATE_LIMITED']) {
      expect(autoReconnect(code, 0)).toBe(false);
    }
  });
});

describe('VoicePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    ticket = 0;
    client.micOn = true;
    status.mockResolvedValue(CATALOG);
    create.mockImplementation(async () => ({
      voice_session_id: `s${++ticket}`, ticket: `t${ticket}`, ws_path: '/api/v1/voice/ws', mode: 'auto',
      voices: { en: 'en-free', hi: '' }, ceo: { id: 'ceo1', name: 'CEO' },
    }));
  });
  afterEach(() => vi.useRealTimers());

  const start = async () => {
    render(<VoicePanel ceoId="ceo1" />);
    await screen.findByDisplayValue('en-free');
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.enableMic).toHaveBeenCalled());
  };
  const emit = (ev: { type: string; [k: string]: unknown }) => act(() => client.emit!(ev));
  const later = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  it('does not open the microphone or create a session until the user starts voice', () => {
    render(<VoicePanel />);
    expect(client.enableMic).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByText(/Raw audio is processed on this machine and never stored/)).toBeInTheDocument();
    expect(screen.getByLabelText('Language mode')).toHaveValue('auto');
    expect(screen.getByLabelText('English voice')).toBeInTheDocument();
    expect(screen.getByLabelText('Hindi voice')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Offline');
  });

  it('hides non-commercial voices by default and reports missing Hindi', async () => {
    render(<VoicePanel />);
    await screen.findByDisplayValue('en-free');
    expect(screen.queryByRole('option', { name: /en-nc/ })).toBeNull();
    expect(screen.queryByRole('option', { name: /hi-nc/ })).toBeNull();
    expect(screen.getByLabelText('Hindi voice')).toHaveValue('');
    expect(screen.getByText(/Hindi speech is not set up.*live check required/)).toBeInTheDocument();
    expect(screen.getByText(/Non-commercial voices are hidden/)).toBeInTheDocument();
  });

  it('defaults to push-to-talk and never streams before a press', async () => {
    await start();
    expect(screen.getByLabelText('Hands-free')).not.toBeChecked();
    expect(create).toHaveBeenCalledWith('auto', 'en-free', '');
    expect(client.setOpenMic).not.toHaveBeenCalled();
    await emit({ type: 'listening' });
    const talk = await screen.findByLabelText('Hold to talk');
    fireEvent.pointerDown(talk);
    fireEvent.pointerUp(talk);
    expect(client.startTalking).toHaveBeenCalled();
    expect(client.stopTalking).toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Stop'));
    expect(client.stop).toHaveBeenCalled();
  });

  it('push-to-talk works from the keyboard (Space and Enter)', async () => {
    await start();
    await emit({ type: 'listening' });
    const talk = await screen.findByLabelText('Hold to talk');
    for (const key of [' ', 'Enter']) {
      client.startTalking.mockClear();
      client.stopTalking.mockClear();
      fireEvent.keyDown(talk, { key });
      fireEvent.keyDown(talk, { key, repeat: true });
      expect(client.startTalking).toHaveBeenCalledTimes(1);
      fireEvent.keyUp(talk, { key });
      expect(client.stopTalking).toHaveBeenCalledTimes(1);
    }
  });

  it('opts in to hands-free and remembers it', async () => {
    render(<VoicePanel />);
    await screen.findByDisplayValue('en-free');
    fireEvent.click(screen.getByLabelText('Hands-free'));
    expect(localStorage.getItem('nexus.voice.handsFree')).toBe('1');
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.setOpenMic).toHaveBeenCalledWith(true));
  });

  it('pushes mode changes to a live session', async () => {
    await start();
    fireEvent.change(screen.getByLabelText('Language mode'), { target: { value: 'hi' } });
    expect(client.configure).toHaveBeenCalledWith('hi', 'en-free', '');
  });

  it('shows a permission error with a text fallback and Retry', async () => {
    client.enableMic.mockRejectedValueOnce(new DOMException('no', 'NotAllowedError'));
    const fallback = vi.fn();
    render(<VoicePanel onTextFallback={fallback} />);
    await screen.findByDisplayValue('en-free');
    fireEvent.click(screen.getByText('Start voice'));
    expect(await screen.findByRole('alert')).toHaveTextContent(/permission was denied/i);
    fireEvent.click(screen.getByText('Type instead'));
    expect(fallback).toHaveBeenCalled();
    expect(client.close).toHaveBeenCalled();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('shows every state with words, not colour alone', async () => {
    await start();
    const say = async (ev: { type: string }, text: string) => {
      await emit(ev);
      expect(screen.getByRole('status')).toHaveTextContent(text);
    };
    await say({ type: 'listening' }, 'Listening');
    await say({ type: 'speech_started' }, 'Hearing');
    await say({ type: 'transcribing' }, 'Transcribing');
    await say({ type: 'thinking' }, 'Thinking');
    await say({ type: 'speaking' }, 'Speaking');
    await say({ type: 'interrupted' }, 'Interrupted');
    await emit({ type: 'error', code: 'RATE_LIMITED', message: 'slow down' });
    expect(screen.getByRole('alert')).toHaveTextContent('slow down');
    expect(screen.getByRole('status')).toHaveTextContent('Error');
  });

  it('shows partial and final transcript with language, and non-fatal notices', async () => {
    await start();
    await emit({ type: 'listening' });
    await emit({ type: 'partial', text: 'give me' });
    expect(screen.getByLabelText('Transcript')).toHaveTextContent('give me');
    await emit({ type: 'transcript', text: 'give me the status', language: 'en' });
    expect(screen.getByLabelText('Transcript')).toHaveTextContent(/give me the status.*en/);
    await emit({ type: 'notice', code: 'NO_VOICE', message: 'No Hindi voice: text only' });
    expect(screen.getByText('No Hindi voice: text only')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Listening');
  });

  describe('recovery', () => {
    it('reconnects with a fresh ticket and bounded backoff, leaving the mic closed', async () => {
      await start();
      await emit({ type: 'listening' });
      vi.useFakeTimers();
      client.enableMic.mockClear();
      await emit({ type: 'closed' }); // abnormal drop
      expect(screen.getByRole('status')).toHaveTextContent('Reconnecting (attempt 1 of 4)');
      await later(1000);
      expect(create).toHaveBeenCalledTimes(2); // a new session and ticket
      expect(client.open).toHaveBeenLastCalledWith(expect.objectContaining({ ticket: 't2' }));
      expect(client.enableMic).not.toHaveBeenCalled(); // no automatic mic
      await emit({ type: 'closed' });
      await later(1000);
      expect(create).toHaveBeenCalledTimes(2); // second wait is 2 s
      await later(1000);
      expect(create).toHaveBeenCalledTimes(3);
    });

    it('gives up after the attempt bound and offers Retry', async () => {
      await start();
      await emit({ type: 'listening' });
      vi.useFakeTimers();
      for (let i = 0; i < 4; i++) {
        await emit({ type: 'closed' });
        await later(9000);
      }
      const calls = create.mock.calls.length;
      await emit({ type: 'closed' });
      await later(60000);
      expect(create.mock.calls.length).toBe(calls);
      expect(screen.getByText('Retry')).toBeInTheDocument();
    });

    it('reopens the mic on reconnect only when hands-free is on', async () => {
      localStorage.setItem('nexus.voice.handsFree', '1');
      render(<VoicePanel ceoId="ceo1" />);
      await screen.findByDisplayValue('en-free');
      fireEvent.click(screen.getByText('Start voice'));
      await waitFor(() => expect(client.setOpenMic).toHaveBeenCalledWith(true));
      await emit({ type: 'listening' });
      vi.useFakeTimers();
      client.enableMic.mockClear();
      await emit({ type: 'closed' });
      await later(1000);
      expect(client.enableMic).toHaveBeenCalledTimes(1);
    });

    it('opens the mic from the press that follows a reconnect', async () => {
      client.micOn = false;
      await start();
      client.enableMic.mockClear();
      await emit({ type: 'listening' });
      fireEvent.pointerDown(await screen.findByLabelText('Hold to talk'));
      await waitFor(() => expect(client.startTalking).toHaveBeenCalled());
      expect(client.enableMic).toHaveBeenCalledTimes(1);
    });

    it.each(['CEO_CHANGED', 'SESSION_REVOKED'])('does not reconnect or retry after %s', async (code) => {
      await start();
      await emit({ type: 'listening' });
      vi.useFakeTimers();
      await emit({ type: 'error', code, message: 'ended' });
      await emit({ type: 'closed' });
      await later(60000);
      expect(create).toHaveBeenCalledTimes(1);
      expect(screen.getByText('Start voice').closest('button')).toBeDisabled();
    });

    it('refuses a session that belongs to a different CEO than this chat', async () => {
      create.mockResolvedValueOnce({ voice_session_id: 's9', ticket: 't9', ws_path: '/', ceo: { id: 'someone-else', name: 'New' } });
      render(<VoicePanel ceoId="ceo1" />);
      await screen.findByDisplayValue('en-free');
      fireEvent.click(screen.getByText('Start voice'));
      expect(await screen.findByRole('alert')).toHaveTextContent(/CEO changed/);
      expect(client.open).not.toHaveBeenCalled();
      expect(endSession).toHaveBeenCalledWith('s9');
    });

    it('ending voice revokes the session and does not reconnect', async () => {
      await start();
      await emit({ type: 'listening' });
      vi.useFakeTimers();
      fireEvent.click(screen.getByText('End voice'));
      await later(20000);
      expect(endSession).toHaveBeenCalledWith('s1');
      expect(create).toHaveBeenCalledTimes(1);
    });
  });
});
