/** Binary frames for the NEXUS voice WebSocket (protocol v1). Mirrors src/nexus/voice/protocol.py. */

export const VOICE_PROTOCOL = 1;
export const SAMPLE_RATE_IN = 16000;
export const MAX_PAYLOAD = 8192;
const KIND_AUDIO_UP = 1;
const KIND_AUDIO_DOWN = 3;

/** Header `!BBHI` (version, kind, reserved, seq) followed by s16le PCM. */
export function packUp(seq: number, pcm: Int16Array): ArrayBuffer {
  if (pcm.byteLength === 0 || pcm.byteLength > MAX_PAYLOAD) throw new RangeError('bad frame size');
  const out = new ArrayBuffer(8 + pcm.byteLength);
  const view = new DataView(out);
  view.setUint8(0, VOICE_PROTOCOL);
  view.setUint8(1, KIND_AUDIO_UP);
  view.setUint16(2, 0);
  view.setUint32(4, seq >>> 0);
  new Int16Array(out, 8).set(pcm);
  return out;
}

export interface DownFrame {
  seq: number;
  sampleRate: number;
  last: boolean;
  pcm: Int16Array;
}

/** Header `!BBHII` (version, kind, flags, seq, sample_rate); flag bit 0 ends a sentence. Null if malformed. */
export function parseDown(buf: ArrayBuffer): DownFrame | null {
  if (buf.byteLength <= 12 || (buf.byteLength - 12) % 2) return null;
  const view = new DataView(buf);
  if (view.getUint8(0) !== VOICE_PROTOCOL || view.getUint8(1) !== KIND_AUDIO_DOWN) return null;
  return {
    seq: view.getUint32(4),
    sampleRate: view.getUint32(8),
    last: (view.getUint16(2) & 1) === 1,
    pcm: new Int16Array(buf.slice(12)),
  };
}

export function floatToPcm16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]!));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
