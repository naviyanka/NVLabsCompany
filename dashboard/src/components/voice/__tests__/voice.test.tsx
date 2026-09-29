import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { floatToPcm16, packUp, parseDown } from '@/lib/voice/protocol';
import { initialVoiceState, reduceVoice, type VoiceUiState } from '@/lib/voice/voiceState';

const client = vi.hoisted(() => ({
  open: vi.fn(async () => {}),
  enableMic: vi.fn(async () => {}),
  startTalking: vi.fn(),
  stopTalking: vi.fn(),
  stop: vi.fn(),
  configure: vi.fn(),
  setOpenMic: vi.fn(),
  close: vi.fn(),
  emit: null as null | ((ev: { type: string }) => void),
}));
const create = vi.hoisted(() => vi.fn());

vi.mock('@/lib/voice/voiceClient', () => ({
  createVoiceSession: create,
  VoiceClient: class {
    constructor(onEvent: (ev: { type: string }) => void) {
      client.emit = onEvent;
      Object.assign(this, client);
    }
  },
}));

import { VoicePanel } from './../VoicePanel';

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
    expect(run('ready').phase).toBe('listening');
    expect(run('ready', 'speech_started').phase).toBe('hearing');
    expect(run('ready', 'speech_started', 'speech_ended', 'transcribing').phase).toBe('transcribing');
    expect(run('ready', 'thinking').phase).toBe('thinking');
    expect(run('ready', 'thinking', 'speaking').phase).toBe('speaking');
    expect(run('ready', 'thinking', 'speaking', 'interrupted').phase).toBe('listening');
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
});

describe('VoicePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    create.mockResolvedValue({ ticket: 't', ws_path: '/api/v1/voice/ws', mode: 'auto', voices: { en: 'a', hi: 'b' } });
  });

  it('does not open the microphone until the user starts voice', () => {
    render(<VoicePanel />);
    expect(client.enableMic).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByText(/Raw audio is processed on this machine and never stored/)).toBeInTheDocument();
    expect(screen.getByLabelText('Language mode')).toHaveValue('auto');
    expect(screen.getByLabelText('English voice')).toBeInTheDocument();
    expect(screen.getByLabelText('Hindi voice')).toBeInTheDocument();
  });

  it('defaults to push-to-talk and never streams before a press', async () => {
    render(<VoicePanel />);
    expect(screen.getByLabelText('Hands-free')).not.toBeChecked();
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.enableMic).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith('auto', expect.any(String), expect.any(String));
    expect(client.setOpenMic).not.toHaveBeenCalled();
    client.emit!({ type: 'listening' });
    const talk = await screen.findByLabelText('Hold to talk');
    fireEvent.pointerDown(talk);
    fireEvent.pointerUp(talk);
    expect(client.startTalking).toHaveBeenCalled();
    expect(client.stopTalking).toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Stop'));
    expect(client.stop).toHaveBeenCalled();
  });

  it('opts in to hands-free and remembers it', async () => {
    render(<VoicePanel />);
    fireEvent.click(screen.getByLabelText('Hands-free'));
    expect(localStorage.getItem('nexus.voice.handsFree')).toBe('1');
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.setOpenMic).toHaveBeenCalledWith(true));
  });

  it('pushes mode and voice changes to a live session', async () => {
    render(<VoicePanel />);
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.enableMic).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText('Language mode'), { target: { value: 'hi' } });
    expect(client.configure).toHaveBeenCalledWith('hi', 'en_US-lessac-medium', 'hi_IN-pratham-medium');
  });

  it('shows a permission error with a text fallback', async () => {
    client.enableMic.mockRejectedValueOnce(new DOMException('no', 'NotAllowedError'));
    const fallback = vi.fn();
    render(<VoicePanel onTextFallback={fallback} />);
    fireEvent.click(screen.getByText('Start voice'));
    expect(await screen.findByRole('alert')).toHaveTextContent(/permission was denied/i);
    fireEvent.click(screen.getByText('Type instead'));
    expect(fallback).toHaveBeenCalled();
    expect(client.close).toHaveBeenCalled();
  });

  it('shows live status, partial and final transcript with language', async () => {
    render(<VoicePanel />);
    fireEvent.click(screen.getByText('Start voice'));
    await waitFor(() => expect(client.enableMic).toHaveBeenCalled());
    client.emit!({ type: 'listening' });
    expect(await screen.findByRole('status')).toHaveTextContent('Listening');
    client.emit!({ type: 'partial', text: 'give me' } as never);
    expect(await screen.findByLabelText('Transcript')).toHaveTextContent('give me');
    client.emit!({ type: 'transcript', text: 'give me the status', language: 'en' } as never);
    await waitFor(() => expect(screen.getByLabelText('Transcript')).toHaveTextContent(/give me the status.*en/));
    client.emit!({ type: 'thinking' });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Thinking'));
  });
});
