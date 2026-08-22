import { useState, useEffect, useRef } from 'react';

/**
 * RealisticAvatar — renders a frame from a character spritesheet.
 */
interface RealisticAvatarProps {
  /** Path to the spritesheet image */
  src: string;
  /** Which row to show: 0=front, 1=back, 2=side */
  direction?: 0 | 1 | 2;
  /** Whether to animate the walk cycle */
  walking?: boolean;
  /** Display size (height in px, width scales proportionally) */
  size?: number;
  /** Specific frame to show (0-7), overrides animation */
  frame?: number;
}

// Spritesheet layout
const COLS = 8;
const ROWS = 3;

export function RealisticAvatar({ src, direction = 0, walking = false, size = 48, frame: fixedFrame }: RealisticAvatarProps) {
  const [frame, setFrame] = useState(fixedFrame ?? 0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Walk animation cycle
  useEffect(() => {
    if (fixedFrame !== undefined) { setFrame(fixedFrame); return; }
    if (!walking) { setFrame(0); return; }

    let f = 0;
    intervalRef.current = setInterval(() => {
      f = (f + 1) % COLS;
      setFrame(f);
    }, 120);

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [walking, fixedFrame]);

  // Frame dimensions (percentage-based for background-position)
  const frameWidthPct = 100 / COLS;
  const frameHeightPct = 100 / ROWS;
  const bgPosX = frame * frameWidthPct;
  const bgPosY = direction * frameHeightPct;

  // Aspect ratio of each frame (96:170 ≈ 0.565)
  const frameAspect = (768 / COLS) / (512 / ROWS);
  const width = size * frameAspect;

  return (
    <div
      style={{
        width,
        height: size,
        backgroundImage: `url(${src})`,
        backgroundSize: `${COLS * 100}% ${ROWS * 100}%`,
        backgroundPosition: `${bgPosX}% ${bgPosY}%`,
        backgroundRepeat: 'no-repeat',
        imageRendering: 'auto',
      }}
    />
  );
}
