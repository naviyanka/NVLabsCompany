import { Html } from '@react-three/drei';

interface ZoneLabelProps {
  text: string;
  position: [number, number, number];
  color: string;
}

/**
 * Fixed-size floating label above a zone.
 * No distanceFactor — stays constant size regardless of zoom.
 * sprite mode keeps it facing camera. pointerEvents none so controls work.
 */
export function ZoneLabel({ text, position, color }: ZoneLabelProps) {
  return (
    <Html
      position={[position[0], position[1] + 1.5, position[2]]}
      center
      sprite
      style={{ pointerEvents: 'none' }}
    >
      <div
        className="px-1.5 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap select-none pointer-events-none"
        style={{
          color,
          backgroundColor: 'rgba(15, 17, 23, 0.85)',
          border: `1px solid ${color}40`,
          textShadow: `0 0 6px ${color}80`,
        }}
      >
        {text}
      </div>
    </Html>
  );
}
