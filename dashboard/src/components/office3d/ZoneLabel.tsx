import { Html } from '@react-three/drei';

interface ZoneLabelProps {
  text: string;
  position: [number, number, number];
  color: string;
}

/**
 * Floating text label for a zone that always faces the camera.
 * Uses drei Html for crisp text rendering over the 3D scene.
 */
export function ZoneLabel({ text, position, color }: ZoneLabelProps) {
  return (
    <Html
      position={[position[0], position[1] + 2.5, position[2]]}
      center
      distanceFactor={20}
      style={{ pointerEvents: 'none' }}
    >
      <div
        className="px-2 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap select-none"
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
