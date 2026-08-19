import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface DeskProps {
  position: [number, number, number];
  isOccupied?: boolean;
  screenColor?: string;
}

/**
 * A 3D desk object with table surface and glowing computer screen.
 * Screen flickers when occupied (agent working).
 */
export function Desk({ position, isOccupied = false, screenColor = '#3b82f6' }: DeskProps) {
  const screenRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (screenRef.current && isOccupied) {
      // Subtle screen flicker effect for active desks
      const emissiveIntensity = 0.8 + Math.sin(state.clock.elapsedTime * 3 + position[0]) * 0.2;
      const mat = screenRef.current.material as THREE.MeshStandardMaterial;
      mat.emissiveIntensity = emissiveIntensity;
    }
  });

  return (
    <group position={position}>
      {/* Desk surface (table top) */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[1.2, 0.08, 0.7]} />
        <meshStandardMaterial color="#2a2a3e" roughness={0.6} metalness={0.3} />
      </mesh>

      {/* Desk legs */}
      {[[-0.5, -0.25, -0.25], [0.5, -0.25, -0.25], [-0.5, -0.25, 0.25], [0.5, -0.25, 0.25]].map(
        (legPos, i) => (
          <mesh key={i} position={legPos as [number, number, number]}>
            <boxGeometry args={[0.05, 0.5, 0.05]} />
            <meshStandardMaterial color="#1a1a2e" roughness={0.8} />
          </mesh>
        )
      )}

      {/* Monitor (screen) */}
      <mesh ref={screenRef} position={[0, 0.45, -0.2]} rotation={[0.1, 0, 0]}>
        <boxGeometry args={[0.7, 0.5, 0.03]} />
        <meshStandardMaterial
          color={isOccupied ? '#0a0a1a' : '#1a1a2e'}
          emissive={isOccupied ? screenColor : '#111122'}
          emissiveIntensity={isOccupied ? 0.8 : 0.1}
          roughness={0.2}
          metalness={0.5}
        />
      </mesh>

      {/* Monitor stand */}
      <mesh position={[0, 0.2, -0.2]}>
        <boxGeometry args={[0.06, 0.35, 0.06]} />
        <meshStandardMaterial color="#1a1a2e" roughness={0.7} metalness={0.4} />
      </mesh>
    </group>
  );
}
