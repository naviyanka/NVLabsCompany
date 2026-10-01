/**
 * Browser-local microphone preflight. Nothing here talks to NEXUS: device ids, labels and
 * audio stay in this tab. The microphone opens only in `MicTest.start`, from a click.
 */

import { CAPTURE_WORKLET } from './voiceClient';

export type MicPermission = 'granted' | 'denied' | 'prompt' | 'unknown';
export type MicFailure = 'denied' | 'no-device' | 'busy' | 'unsupported' | 'failed';

const DEVICE_KEY = 'nexus.voice.inputDevice';

export function savedDevice(): string {
  try {
    return localStorage.getItem(DEVICE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function saveDevice(id: string): void {
  try {
    localStorage.setItem(DEVICE_KEY, id);
  } catch {
    /* choice just will not persist */
  }
}

/** Reads the permission state without opening the microphone. */
export async function micPermission(): Promise<MicPermission> {
  try {
    const s = await navigator.permissions.query({ name: 'microphone' as PermissionName });
    return s.state as MicPermission;
  } catch {
    return 'unknown';
  }
}

/** Input devices. Labels are empty until permission is granted, so callers ask only after it. */
export async function inputDevices(): Promise<{ id: string; label: string }[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === 'audioinput').map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
}

export function micFailure(err: unknown): MicFailure {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'no-device';
  if (name === 'NotReadableError' || name === 'AbortError') return 'busy';
  if (err instanceof TypeError || (err instanceof Error && /cannot capture/i.test(err.message))) return 'unsupported';
  return 'failed';
}

export const FAILURE_TEXT: Record<MicFailure, string> = {
  denied: 'Microphone permission was denied. Allow it in the browser and try again.',
  'no-device': 'No microphone was found, or the selected one is unplugged.',
  busy: 'The microphone is busy. Close other apps using it and try again.',
  unsupported: 'This browser cannot capture audio.',
  failed: 'The microphone could not be opened.',
};

export interface MicReading {
  /** RMS of the latest audio block, 0..1. */
  level: number;
  /** AudioContext rate actually granted by the browser (not the 16 kHz the gateway wants). */
  sampleRate: number;
  workletLoaded: boolean;
  /** Blocks delivered by the AudioWorklet since the test started. */
  frames: number;
}

/** One local microphone test: level, sample rate and worklet frame flow. Sends nothing anywhere. */
export class MicTest {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private frames = 0;

  async start(deviceId: string, onReading: (r: MicReading) => void): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot capture audio');
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
    });
    try {
      const ctx = (this.ctx = new AudioContext());
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      const source = ctx.createMediaStreamSource(this.stream);
      source.connect(analyser);
      let workletLoaded = false;
      try {
        const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'text/javascript' }));
        await ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);
        const node = new AudioWorkletNode(ctx, 'capture');
        node.port.onmessage = () => (this.frames += 1);
        source.connect(node);
        workletLoaded = true;
      } catch {
        /* reported as not loaded */
      }
      const buf = new Float32Array(analyser.fftSize);
      this.timer = setInterval(() => {
        analyser.getFloatTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((sum, v) => sum + v * v, 0) / buf.length);
        onReading({ level: Math.min(1, rms * 4), sampleRate: ctx.sampleRate, workletLoaded, frames: this.frames });
      }, 100);
    } catch (err) {
      this.stop();
      throw err;
    }
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.frames = 0;
  }
}
