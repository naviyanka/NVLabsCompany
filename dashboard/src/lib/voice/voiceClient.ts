/**
 * Browser side of the local CEO voice gateway: WebSocket, microphone capture
 * (16 kHz mono PCM via an AudioWorklet) and ordered playback that can be cut at once.
 * The microphone is opened only from an explicit user action, and no audio is stored.
 */

import { apiClient, apiUrl } from '@/api/client';
import { floatToPcm16, packUp, parseDown, VOICE_PROTOCOL } from './protocol';
import type { VoiceEvent, VoiceMode } from './voiceState';

export interface VoiceStatus {
  enabled: boolean;
  ceo_id: string | null;
  default_voices: { en: string; hi: string };
}

export interface VoiceSessionInfo {
  ticket: string;
  ws_path: string;
  mode: VoiceMode;
  voices: { en: string; hi: string };
}

export const fetchVoiceStatus = () => apiClient.get<VoiceStatus>('/api/v1/voice/status');

export const createVoiceSession = (mode: VoiceMode, voice_en: string, voice_hi: string) =>
  apiClient.post<VoiceSessionInfo>('/api/v1/voice/sessions', { mode, voice_en, voice_hi });

const WORKLET = `
class Capture extends AudioWorkletProcessor {
  buf = new Float32Array(512); n = 0;
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i];
      if (this.n === 512) { this.port.postMessage(this.buf.slice()); this.n = 0; }
    }
    return true;
  }
}
registerProcessor('capture', Capture);`;

function wsUrl(path: string): string {
  const url = new URL(apiUrl(path), window.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export class VoiceClient {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private seq = 0;
  private sending = false;
  private nextAt = 0;
  private playing = new Set<AudioBufferSourceNode>();

  constructor(private onEvent: (ev: VoiceEvent) => void) {}

  async open(session: VoiceSessionInfo): Promise<void> {
    const ws = new WebSocket(wsUrl(session.ws_path));
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    ws.onmessage = (m) => (typeof m.data === 'string' ? this.onJson(m.data) : this.play(m.data as ArrayBuffer));
    ws.onclose = () => {
      this.stopAudio();
      this.onEvent({ type: 'closed' });
    };
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error('Could not reach the voice gateway'));
    });
    ws.send(JSON.stringify({ type: 'hello', ticket: session.ticket, protocol: VOICE_PROTOCOL }));
  }

  /** Ask for the microphone. Call only from a click or key press. */
  async enableMic(): Promise<void> {
    if (this.stream) return;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot capture audio');
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    this.ctx = new AudioContext({ sampleRate: 16000 });
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }));
    await this.ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const node = new AudioWorkletNode(this.ctx, 'capture');
    node.port.onmessage = (m) => this.sendFrame(m.data as Float32Array);
    this.ctx.createMediaStreamSource(this.stream).connect(node);
  }

  private sendFrame(samples: Float32Array): void {
    if (!this.sending || this.ws?.readyState !== WebSocket.OPEN || this.ws.bufferedAmount > 256 * 1024) return;
    this.ws.send(packUp(this.seq++, floatToPcm16(samples)));
  }

  /** Push-to-talk press (or hands-free on): stops any speech at once and starts streaming. */
  startTalking(): void {
    this.stopPlayback();
    this.control({ type: 'ptt_start' });
    this.sending = true;
  }

  /** Hands-free: stream continuously and let the gateway's VAD find utterances and barge-in. */
  setOpenMic(on: boolean): void {
    this.sending = on;
  }

  stopTalking(): void {
    this.sending = false;
    this.control({ type: 'ptt_end' });
  }

  stop(): void {
    this.stopPlayback();
    this.control({ type: 'stop' });
  }

  configure(mode: VoiceMode, voice_en: string, voice_hi: string): void {
    this.control({ type: 'config', mode, voice_en, voice_hi });
  }

  close(): void {
    this.ws?.close();
    this.stopAudio();
  }

  private control(msg: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private onJson(raw: string): void {
    let ev: VoiceEvent;
    try {
      ev = JSON.parse(raw) as VoiceEvent;
    } catch {
      return;
    }
    if (ev.type === 'interrupted') this.stopPlayback();
    this.onEvent(ev);
  }

  private play(buf: ArrayBuffer): void {
    const frame = parseDown(buf);
    if (!frame) return;
    const ctx = (this.ctx ??= new AudioContext());
    const audio = ctx.createBuffer(1, frame.pcm.length, frame.sampleRate);
    audio.copyToChannel(Float32Array.from(frame.pcm, (v) => v / 0x8000), 0);
    const src = ctx.createBufferSource();
    src.buffer = audio;
    src.connect(ctx.destination);
    this.nextAt = Math.max(this.nextAt, ctx.currentTime + 0.02);
    src.start(this.nextAt);
    this.nextAt += audio.duration;
    this.playing.add(src);
    src.onended = () => this.playing.delete(src);
  }

  /** Cut playback immediately: every queued and playing chunk stops. */
  stopPlayback(): void {
    for (const s of this.playing) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.playing.clear();
    this.nextAt = 0;
  }

  private stopAudio(): void {
    this.sending = false;
    this.stopPlayback();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
