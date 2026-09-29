/**
 * MicCheck — local microphone preflight. Device labels, ids and audio never leave this
 * browser tab. The microphone opens only when the user presses "Test microphone".
 */

import { useEffect, useRef, useState } from 'react';
import { Mic } from 'lucide-react';
import {
  FAILURE_TEXT,
  inputDevices,
  micFailure,
  micPermission,
  MicTest,
  saveDevice,
  type MicFailure,
  type MicPermission,
  type MicReading,
} from '@/lib/voice/micPreflight';

const PERMISSION_TEXT: Record<MicPermission, string> = {
  granted: 'Permission granted',
  denied: 'Permission denied',
  prompt: 'Permission not asked yet',
  unknown: 'Permission state unknown',
};

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#FFB020]';

export function MicCheck({ deviceId, onDevice }: { deviceId: string; onDevice: (id: string) => void }) {
  const [permission, setPermission] = useState<MicPermission>('unknown');
  const [devices, setDevices] = useState<{ id: string; label: string }[]>([]);
  const [reading, setReading] = useState<MicReading | null>(null);
  const [flowing, setFlowing] = useState(false);
  const [failure, setFailure] = useState<MicFailure | null>(null);
  const test = useRef<MicTest | null>(null);
  const lastFrames = useRef(0);
  const testing = reading !== null;

  const refresh = async () => {
    const p = await micPermission();
    setPermission(p);
    // Labels exist only after permission; never trigger a prompt just to list devices.
    if (p === 'granted') setDevices(await inputDevices());
  };

  useEffect(() => {
    void refresh();
    return () => test.current?.stop();
  }, []);

  const stop = () => {
    test.current?.stop();
    test.current = null;
    setReading(null);
    setFlowing(false);
    lastFrames.current = 0;
  };

  const start = async () => {
    setFailure(null);
    const t = new MicTest();
    test.current = t;
    try {
      await t.start(deviceId, (r) => {
        setFlowing(r.frames > lastFrames.current);
        lastFrames.current = r.frames;
        setReading(r);
      });
      await refresh(); // permission is now granted: real device labels are available
    } catch (err) {
      test.current = null;
      setFailure(micFailure(err));
      void refresh();
    }
  };

  return (
    <div aria-label="Microphone check" className="space-y-1.5 rounded border border-white/[0.08] p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span>{PERMISSION_TEXT[permission]}</span>
        {devices.length > 0 && (
          <select
            aria-label="Input device"
            value={deviceId}
            onChange={(e) => {
              saveDevice(e.target.value);
              onDevice(e.target.value);
              stop();
            }}
            className={`bg-[#141416] border border-white/[0.12] rounded px-1.5 py-1 ${FOCUS}`}
          >
            <option value="">System default</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          onClick={() => (testing ? stop() : void start())}
          className={`ml-auto flex items-center gap-1 px-2 py-1 rounded-[6px] border border-white/[0.2] ${FOCUS}`}
        >
          <Mic size={12} /> {testing ? 'Stop test' : 'Test microphone'}
        </button>
      </div>

      {reading && (
        <div className="space-y-1">
          <meter aria-label="Input level" min={0} max={1} value={reading.level} className="w-full h-2 motion-reduce:transition-none" />
          <p className="font-mono text-[10px]">
            {reading.sampleRate} Hz · AudioWorklet {reading.workletLoaded ? 'loaded' : 'not loaded'} · frames {flowing ? 'flowing' : 'not flowing'}
          </p>
          <p className="text-[10px] text-[#6B6B6E]">Local test: no audio is sent to NEXUS.</p>
        </div>
      )}
      {failure && (
        <p role="alert" className="text-red-400">
          {FAILURE_TEXT[failure]}
        </p>
      )}
    </div>
  );
}
