import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { mockAgents3D, zones3D, managerCabin } from '@/config/office3dLayout';

/**
 * Animated envelope/document mesh that flies between agents
 * when reports are being shared (agents with status 'review').
 */
export function ReportAnimation() {
  // Agents in review send reports back to manager
  const reviewAgents = useMemo(
    () => mockAgents3D.filter((a) => a.status === 'review'),
    []
  );

  return (
    <group>
      {reviewAgents.map((agent) => {
        const zone = zones3D.find((z) => z.id === agent.zoneId);
        const desk = zone?.desks.find((d) => d.id === agent.deskId);
        if (!desk) return null;
        return (
          <ReportEnvelope
            key={agent.id}
            start={[desk.position[0], 1.5, desk.position[2]]}
            end={[managerCabin.position[0], 2, managerCabin.position[2]]}
            agentId={agent.id}
          />
        );
      })}
    </group>
  );
}

interface ReportEnvelopeProps {
  start: [number, number, number];
  end: [number, number, number];
  agentId: string;
}

function ReportEnvelope({ start, end, agentId }: ReportEnvelopeProps) {
  const envelopeRef = useRef<THREE.Group>(null);

  const offset = useMemo(() => {
    let hash = 0;
    for (let i = 0; i < agentId.length; i++) {
      hash = ((hash << 5) - hash) + agentId.charCodeAt(i);
      hash |= 0;
    }
    return (Math.abs(hash) % 100) / 100 * Math.PI * 2;
  }, [agentId]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    // Cycle every 5 seconds
    const progress = ((t + offset) % 5) / 5;

    if (envelopeRef.current) {
      const midY = 3.5;
      const invP = 1 - progress;
      const x = invP * invP * start[0] + 2 * invP * progress * ((start[0] + end[0]) / 2) + progress * progress * end[0];
      const y = invP * invP * start[1] + 2 * invP * progress * midY + progress * progress * end[1];
      const z = invP * invP * start[2] + 2 * invP * progress * ((start[2] + end[2]) / 2) + progress * progress * end[2];

      envelopeRef.current.position.set(x, y, z);
      // Gentle rotation while flying
      envelopeRef.current.rotation.y = t * 2;
      envelopeRef.current.rotation.z = Math.sin(t * 3) * 0.2;

      // Visibility
      envelopeRef.current.visible = progress > 0.05;
      const scale = progress < 0.1 ? progress * 10 : progress > 0.9 ? (1 - progress) * 10 : 1;
      envelopeRef.current.scale.setScalar(Math.max(0.01, scale));
    }
  });

  return (
    <group ref={envelopeRef}>
      {/* Envelope body */}
      <mesh>
        <boxGeometry args={[0.25, 0.02, 0.18]} />
        <meshStandardMaterial
          color="#a855f7"
          emissive="#a855f7"
          emissiveIntensity={0.6}
          roughness={0.4}
        />
      </mesh>
      {/* Envelope flap */}
      <mesh position={[0, 0.02, 0]} rotation={[0.3, 0, 0]}>
        <boxGeometry args={[0.25, 0.01, 0.1]} />
        <meshStandardMaterial
          color="#c084fc"
          emissive="#c084fc"
          emissiveIntensity={0.4}
          roughness={0.4}
        />
      </mesh>
    </group>
  );
}
