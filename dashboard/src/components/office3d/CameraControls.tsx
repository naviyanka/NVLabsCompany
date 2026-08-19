import { OrbitControls } from '@react-three/drei';

/**
 * Camera controls configured for isometric-style pan/zoom.
 * Allows drag-to-pan and scroll-to-zoom with limits.
 * Target is centered on the office layout to show all 9 zones.
 */
export function CameraControls() {
  return (
    <OrbitControls
      target={[-3, 0, -3]}
      enableRotate={true}
      enablePan={true}
      enableZoom={true}
      minZoom={0.5}
      maxZoom={3}
      minPolarAngle={Math.PI / 6}
      maxPolarAngle={Math.PI / 3}
      minAzimuthAngle={-Math.PI / 4}
      maxAzimuthAngle={Math.PI / 4}
      enableDamping={true}
      dampingFactor={0.05}
      panSpeed={0.8}
      zoomSpeed={0.8}
      mouseButtons={{
        LEFT: 2, // Right-click to orbit
        MIDDLE: 1, // Middle to zoom
        RIGHT: 0, // Left-click to pan (we use left-click for selecting)
      }}
      touches={{
        ONE: 1, // One finger to pan
        TWO: 2, // Two fingers to zoom
      }}
    />
  );
}
