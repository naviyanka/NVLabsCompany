import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import { managerCabin, managerAgent, status3DColors } from '@/config/office3dLayout';
import { Desk } from './Desk';
import { ZoneLabel } from './ZoneLabel';
import type { MockAgent3D } from '@/config/office3dLayout';

interface ManagerCabinProps {
  onAgentClick?: (agent: MockAgent3D) => void;
  isSelected?: boolean;
}

/**
 * Manager cabin with larger desk, glass partition effect, and the manager agent.
 */
export function ManagerCabin({ onAgentClick, isSelected = false }: ManagerCabinProps) {
  const managerRef = useRef<THREE.Group>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const statusColor = status3DColors[managerAgent.status] ?? '#9ca3af';

  useFrame((state) => {
    const t = state.clock.elapsedTime;

    if (managerRef.current) {
      managerRef.current.position.y = 0.8 + Math.sin(t * 3) * 0.03;
      managerRef.current.rotation.x = Math.sin(t * 5) * 0.03;
    }

    if (glowRef.current) {
      const mat = glowRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = 0.4 + Math.sin(t * 2) * 0.2;
    }
  });

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    onAgentClick?.(managerAgent);
  };

  return (
    <group position={managerCabin.position}>
      {/* Floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <planeGeometry args={[managerCabin.size[0], managerCabin.size[1]]} />
        <meshStandardMaterial
          color={managerCabin.color}
          transparent
          opacity={0.7}
          roughness={0.9}
        />
      </mesh>

      {/* Glass partition walls */}
      {/* Front wall */}
      <mesh position={[0, 1, managerCabin.size[1] / 2]}>
        <boxGeometry args={[managerCabin.size[0], 2, 0.05]} />
        <meshStandardMaterial
          color="#4060a0"
          transparent
          opacity={0.15}
          roughness={0.1}
          metalness={0.9}
        />
      </mesh>
      {/* Left wall */}
      <mesh position={[-managerCabin.size[0] / 2, 1, 0]}>
        <boxGeometry args={[0.05, 2, managerCabin.size[1]]} />
        <meshStandardMaterial
          color="#4060a0"
          transparent
          opacity={0.15}
          roughness={0.1}
          metalness={0.9}
        />
      </mesh>
      {/* Right wall */}
      <mesh position={[managerCabin.size[0] / 2, 1, 0]}>
        <boxGeometry args={[0.05, 2, managerCabin.size[1]]} />
        <meshStandardMaterial
          color="#4060a0"
          transparent
          opacity={0.15}
          roughness={0.1}
          metalness={0.9}
        />
      </mesh>

      {/* Border glow on floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <ringGeometry args={[2.8, 3.0, 4]} />
        <meshBasicMaterial
          color={managerCabin.borderColor}
          transparent
          opacity={0.5}
        />
      </mesh>

      {/* Manager desk */}
      <Desk position={[0, 0.5, -0.5]} isOccupied screenColor="#6366f1" />

      {/* Manager character */}
      <group ref={managerRef} position={[0, 0.8, 0.3]} onClick={handleClick}>
        {/* Body */}
        <mesh>
          <capsuleGeometry args={[0.18, 0.35, 8, 16]} />
          <meshStandardMaterial color="#1e2035" roughness={0.4} metalness={0.3} />
        </mesh>
        {/* Head */}
        <mesh position={[0, 0.4, 0]}>
          <sphereGeometry args={[0.22, 16, 16]} />
          <meshStandardMaterial
            color={statusColor}
            emissive={statusColor}
            emissiveIntensity={isSelected ? 1.5 : 0.8}
            roughness={0.3}
            metalness={0.5}
          />
        </mesh>
        {/* Crown/hat to distinguish manager */}
        <mesh position={[0, 0.62, 0]}>
          <coneGeometry args={[0.12, 0.15, 6]} />
          <meshStandardMaterial
            color="#fbbf24"
            emissive="#fbbf24"
            emissiveIntensity={0.5}
            metalness={0.7}
          />
        </mesh>
        {/* Status glow */}
        <mesh ref={glowRef} position={[0, -0.2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.3, 0.45, 32]} />
          <meshBasicMaterial color={statusColor} transparent opacity={0.4} side={THREE.DoubleSide} />
        </mesh>
      </group>

      {/* Label */}
      <ZoneLabel
        text="Manager Cabin"
        position={[0, 0, 0]}
        color={managerCabin.borderColor}
      />
    </group>
  );
}
