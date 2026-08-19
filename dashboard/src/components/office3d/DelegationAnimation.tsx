import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { managerCabin, mockAgents3D, zones3D } from '@/config/office3dLayout';

/**
 * Glowing particle trail from manager to agents representing task assignment.
 * Creates animated particles that flow from the manager cabin to target agents.
 */
export function DelegationAnimation() {
  // Only animate to "working" agents
  const targetAgents = useMemo(
    () => mockAgents3D.filter((a) => a.status === 'working'),
    []
  );

  return (
    <group>
      {targetAgents.map((agent) => {
        const zone = zones3D.find((z) => z.id === agent.zoneId);
        const desk = zone?.desks.find((d) => d.id === agent.deskId);
        if (!desk) return null;
        return (
          <DelegationParticle
            key={agent.id}
            start={[managerCabin.position[0], 2, managerCabin.position[2]]}
            end={[desk.position[0], 1.5, desk.position[2]]}
            agentId={agent.id}
          />
        );
      })}
    </group>
  );
}

interface DelegationParticleProps {
  start: [number, number, number];
  end: [number, number, number];
  agentId: string;
}

function DelegationParticle({ start, end, agentId }: DelegationParticleProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const trailRef = useRef<THREE.Mesh>(null);

  // Calculate a unique offset so particles don't all sync
  const offset = useMemo(() => {
    let hash = 0;
    for (let i = 0; i < agentId.length; i++) {
      hash = ((hash << 5) - hash) + agentId.charCodeAt(i);
      hash |= 0;
    }
    return (Math.abs(hash) % 100) / 100 * Math.PI * 2;
  }, [agentId]);

  // Midpoint arc
  const midY = 4;

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    // Cycle every 4 seconds
    const progress = ((t + offset) % 4) / 4;

    if (meshRef.current) {
      // Quadratic Bezier curve: start -> mid(up) -> end
      const invP = 1 - progress;
      const x = invP * invP * start[0] + 2 * invP * progress * ((start[0] + end[0]) / 2) + progress * progress * end[0];
      const y = invP * invP * start[1] + 2 * invP * progress * midY + progress * progress * end[1];
      const z = invP * invP * start[2] + 2 * invP * progress * ((start[2] + end[2]) / 2) + progress * progress * end[2];

      meshRef.current.position.set(x, y, z);

      // Fade out near end
      const mat = meshRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = progress < 0.8 ? 0.8 : (1 - progress) * 4;
    }

    if (trailRef.current) {
      // Trail follows slightly behind
      const trailProgress = Math.max(0, progress - 0.05);
      const invTP = 1 - trailProgress;
      const tx = invTP * invTP * start[0] + 2 * invTP * trailProgress * ((start[0] + end[0]) / 2) + trailProgress * trailProgress * end[0];
      const ty = invTP * invTP * start[1] + 2 * invTP * trailProgress * midY + trailProgress * trailProgress * end[1];
      const tz = invTP * invTP * start[2] + 2 * invTP * trailProgress * ((start[2] + end[2]) / 2) + trailProgress * trailProgress * end[2];

      trailRef.current.position.set(tx, ty, tz);
      const mat = trailRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = progress < 0.8 ? 0.4 : (1 - progress) * 2;
    }
  });

  return (
    <group>
      {/* Main particle */}
      <mesh ref={meshRef}>
        <sphereGeometry args={[0.12, 8, 8]} />
        <meshBasicMaterial color="#6366f1" transparent opacity={0.8} />
      </mesh>
      {/* Trail particle */}
      <mesh ref={trailRef}>
        <sphereGeometry args={[0.06, 6, 6]} />
        <meshBasicMaterial color="#a5b4fc" transparent opacity={0.4} />
      </mesh>
    </group>
  );
}
