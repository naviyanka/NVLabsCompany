import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MicCheck } from '../MicCheck';

vi.mock('@/lib/voice/voiceClient', () => ({ CAPTURE_WORKLET: 'class P{}' }));

const track = { stop: vi.fn() };
const getUserMedia = vi.fn();
const enumerateDevices = vi.fn();
const fetchSpy = vi.fn();
const wsSpy = vi.fn();
let permission = 'granted';

class FakeAudioContext {
  sampleRate = 48000;
  audioWorklet = { addModule: vi.fn(async () => {}) };
  createAnalyser() {
    return {
      fftSize: 1024,
      getFloatTimeDomainData: (b: Float32Array) => b.fill(0.1),
    };
  }
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
  close = vi.fn(async () => {});
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  permission = 'granted';
  getUserMedia.mockResolvedValue({ getTracks: () => [track] });
  enumerateDevices.mockResolvedValue([
    { kind: 'audioinput', deviceId: 'dev-a', label: 'Desk mic' },
    { kind: 'videoinput', deviceId: 'cam', label: 'Camera' },
  ]);
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia, enumerateDevices } });
  Object.defineProperty(navigator, 'permissions', { configurable: true, value: { query: async () => ({ state: permission }) } });
  vi.stubGlobal('AudioContext', FakeAudioContext);
  vi.stubGlobal('AudioWorkletNode', class { port: { onmessage: (() => void) | null } = { onmessage: null }; constructor() { setTimeout(() => this.port.onmessage?.(), 0); } });
  vi.stubGlobal('fetch', fetchSpy);
  vi.stubGlobal('WebSocket', wsSpy);
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

describe('MicCheck', () => {
  it('never opens the microphone on mount', async () => {
    render(<MicCheck deviceId="" onDevice={() => {}} />);
    await screen.findByText('Permission granted');
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('lists devices only after permission and persists the choice locally', async () => {
    const onDevice = vi.fn();
    render(<MicCheck deviceId="" onDevice={onDevice} />);
    const select = await screen.findByLabelText('Input device');
    expect(screen.getByRole('option', { name: 'Desk mic' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Camera' })).toBeNull();
    fireEvent.change(select, { target: { value: 'dev-a' } });
    expect(onDevice).toHaveBeenCalledWith('dev-a');
    expect(localStorage.getItem('nexus.voice.inputDevice')).toBe('dev-a');
  });

  it('does not enumerate devices before permission', async () => {
    permission = 'prompt';
    render(<MicCheck deviceId="" onDevice={() => {}} />);
    await screen.findByText('Permission not asked yet');
    expect(enumerateDevices).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Input device')).toBeNull();
  });

  it('tests locally: level, sample rate, worklet and frame flow; sends nothing', async () => {
    render(<MicCheck deviceId="dev-a" onDevice={() => {}} />);
    await screen.findByText('Permission granted');
    fireEvent.click(screen.getByText('Test microphone'));
    expect(await screen.findByLabelText('Input level')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/48000 Hz · AudioWorklet loaded/)).toBeInTheDocument());
    expect(getUserMedia).toHaveBeenCalledWith({ audio: expect.objectContaining({ deviceId: { exact: 'dev-a' } }) });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(wsSpy).not.toHaveBeenCalled();
    expect(screen.getByText(/no audio is sent to NEXUS/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Stop test'));
    expect(track.stop).toHaveBeenCalled();
    expect(screen.queryByLabelText('Input level')).toBeNull();
  });

  it.each([
    ['NotAllowedError', /permission was denied/i],
    ['NotFoundError', /No microphone was found/i],
    ['NotReadableError', /microphone is busy/i],
  ])('explains %s', async (name, text) => {
    getUserMedia.mockRejectedValueOnce(new DOMException('x', name));
    render(<MicCheck deviceId="" onDevice={() => {}} />);
    await screen.findByText('Permission granted');
    fireEvent.click(screen.getByText('Test microphone'));
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });
});
