import { useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { status3DColors } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';

interface AgentCharacterProps {
  agent: MockAgent3D;
  position: [number, number, number];
  onClick?: (agent: MockAgent3D) => void;
  isSelected?: boolean;
}

/**
 * 3D agent avatar: capsule/sphere body with colored glow matching status.
 * Includes idle bobbing animation and typing animation when working.
 */
export function AgentCharacter({ agent, position, onClick, isSelected = false }: AgentCharacterProps) {
  const groupRef = useRef<THREE.Group>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);

  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const isWorking = agent.status === 'working';

  useFrame((state) => {
    if (!groupRef.current) return;
    const t = state.clock.elapsedTime;

    // Idle bobbing animation
    const bobSpeed = isWorking ? 4 : 2;
    const bobAmount = isWorking ? 0.03 : 0.06;
    groupRef.current.position.y = position[1] + 0.8 + Math.sin(t * bobSpeed + position[0]) * bobAmount;

    // Typing animation - slight forward/back tilt when working
    if (isWorking) {
      groupRef.current.rotation.x = Math.sin(t * 6) * 0.04;
    }

    // Glow pulse
    if (glowRef.current) {
      const mat = glowRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = 0.3 + Math.sin(t * 2 + position[0] * 2) * 0.15;
    }
  });

  const handleClick = (e: THREE.Event) => {
    (e as unknown as { stopPropagation: () => void }).stopPropagation();
    onClick?.(agent);
  };

  return (
    <group
      ref={groupRef}
      position={[position[0], position[1] + 0.8, position[2] + 0.3]}
      onClick={handleClick}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
    >
      {/* Body - capsule shape */}
      <mesh>
        <capsuleGeometry args={[0.15, 0.3, 8, 16]} />
        <meshStandardMaterial
          color={agent.status === 'offline' ? '#2a2a3e' : '#1e2035'}
          roughness={0.4}
          metalness={0.3}
        />
      </mesh>

      {/* Head - sphere */}
      <mesh position={[0, 0.35, 0]}>
        <sphereGeometry args={[0.18, 16, 16]} />
        <meshStandardMaterial
          color={statusColor}
          emissive={statusColor}
          emissiveIntensity={isSelected || hovered ? 1.2 : 0.6}
          roughness={0.3}
          metalness={0.5}
        />
      </mesh>

      {/* Status glow ring */}
      <mesh ref={glowRef} position={[0, -0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.25, 0.35, 32]} />
        <meshBasicMaterial
          color={statusColor}
          transparent
          opacity={0.4}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Selection indicator */}
      {(isSelected || hovered) && (
        <mesh position={[0, -0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.35, 0.45, 32]} />
          <meshBasicMaterial
            color={statusColor}
            transparent
            opacity={0.6}
            side={THREE.DoubleSide}
          />
        </mesh>
      )}

      {/* Name label */}
      {hovered && (
        <mesh position={[0, 0.65, 0]}>
          <sphereGeometry args={[0.04, 8, 8]} />
          <meshBasicMaterial color="#ffffff" />
        </mesh>
      )}
    </group>
  );
}
