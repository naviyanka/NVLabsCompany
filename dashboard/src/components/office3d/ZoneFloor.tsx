import { useMemo } from 'react';
import { zones3D } from '@/config/office3dLayout';
import { ZoneLabel } from './ZoneLabel';
import * as THREE from 'three';

/**
 * Renders 9 office zones as solid colored rooms with carpet, partitions,
 * chairs, shelves, and ambient zone lighting.
 */
export function ZoneFloor() {
  return (
    <group>
      {zones3D.map((zone, idx) => (
        <ZoneRoom key={zone.id} zone={zone} index={idx} />
      ))}
    </group>
  );
}

interface ZoneRoomProps {
  zone: typeof zones3D[number];
  index: number;
}

function ZoneRoom({ zone, index }: ZoneRoomProps) {
  const w = zone.size[0];
  const h = zone.size[1];

  // Brighten zone color for visible carpet
  const carpetColor = useMemo(() => {
    const c = new THREE.Color(zone.color);
    c.multiplyScalar(1.8); // Make carpet visibly colored
    return '#' + c.getHexString();
  }, [zone.color]);

  // Darken border for partition walls
  const partitionColor = useMemo(() => {
    const c = new THREE.Color(zone.borderColor);
    c.multiplyScalar(0.3);
    return '#' + c.getHexString();
  }, [zone.borderColor]);

  return (
    <group position={zone.position}>
      {/* ─── Raised floor / carpet ─── */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
        <planeGeometry args={[w, h]} />
        <meshStandardMaterial color={carpetColor} roughness={0.95} metalness={0} />
      </mesh>

      {/* Raised edge / platform step (0.05 height) */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <planeGeometry args={[w + 0.1, h + 0.1]} />
        <meshStandardMaterial color="#0c0d18" roughness={0.8} />
      </mesh>

      {/* ─── Glowing border lines ─── */}
      {/* Bottom edge */}
      <mesh position={[0, 0.06, h / 2]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[w, 0.06]} />
        <meshBasicMaterial color={zone.borderColor} transparent opacity={0.8} />
      </mesh>
      {/* Top edge */}
      <mesh position={[0, 0.06, -h / 2]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[w, 0.06]} />
        <meshBasicMaterial color={zone.borderColor} transparent opacity={0.8} />
      </mesh>
      {/* Left edge */}
      <mesh position={[-w / 2, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[0.06, h]} />
        <meshBasicMaterial color={zone.borderColor} transparent opacity={0.8} />
      </mesh>
      {/* Right edge */}
      <mesh position={[w / 2, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[0.06, h]} />
        <meshBasicMaterial color={zone.borderColor} transparent opacity={0.8} />
      </mesh>

      {/* ─── Corner posts (small glowing pillars) ─── */}
      {([[-w/2, -h/2], [-w/2, h/2], [w/2, -h/2], [w/2, h/2]] as [number, number][]).map(([cx, cz], ci) => (
        <mesh key={`corner-${ci}`} position={[cx, 0.3, cz]}>
          <boxGeometry args={[0.12, 0.6, 0.12]} />
          <meshStandardMaterial
            color={zone.borderColor}
            emissive={zone.borderColor}
            emissiveIntensity={0.5}
            roughness={0.3}
            metalness={0.5}
          />
        </mesh>
      ))}

      {/* ─── Partition walls (half-height glass) ─── */}
      {/* Back partition */}
      <mesh position={[0, 0.6, -h / 2 + 0.05]}>
        <boxGeometry args={[w - 0.5, 1.0, 0.05]} />
        <meshStandardMaterial
          color={partitionColor}
          transparent
          opacity={0.3}
          roughness={0.1}
          metalness={0.8}
        />
      </mesh>
      {/* Left partition */}
      <mesh position={[-w / 2 + 0.05, 0.6, 0]}>
        <boxGeometry args={[0.05, 1.0, h - 0.5]} />
        <meshStandardMaterial
          color={partitionColor}
          transparent
          opacity={0.25}
          roughness={0.1}
          metalness={0.8}
        />
      </mesh>

      {/* ─── Office chair (one per zone, offset from desks) ─── */}
      <group position={[w * 0.25, 0, h * 0.2]}>
        {/* Seat */}
        <mesh position={[0, 0.4, 0]}>
          <boxGeometry args={[0.4, 0.06, 0.4]} />
          <meshStandardMaterial color="#1a1a2e" roughness={0.7} />
        </mesh>
        {/* Backrest */}
        <mesh position={[0, 0.7, -0.18]}>
          <boxGeometry args={[0.35, 0.5, 0.05]} />
          <meshStandardMaterial color="#1e1e35" roughness={0.7} />
        </mesh>
        {/* Base */}
        <mesh position={[0, 0.15, 0]}>
          <cylinderGeometry args={[0.2, 0.25, 0.05, 8]} />
          <meshStandardMaterial color="#111118" roughness={0.5} metalness={0.6} />
        </mesh>
        {/* Pole */}
        <mesh position={[0, 0.25, 0]}>
          <cylinderGeometry args={[0.03, 0.03, 0.3, 8]} />
          <meshStandardMaterial color="#2a2a3e" roughness={0.3} metalness={0.7} />
        </mesh>
      </group>

      {/* ─── Shelf / filing cabinet (back-left of zone) ─── */}
      <group position={[-w * 0.35, 0, -h * 0.35]}>
        <mesh position={[0, 0.5, 0]}>
          <boxGeometry args={[0.8, 1.0, 0.4]} />
          <meshStandardMaterial color="#141625" roughness={0.8} metalness={0.2} />
        </mesh>
        {/* Drawer handles */}
        <mesh position={[0, 0.7, 0.21]}>
          <boxGeometry args={[0.3, 0.03, 0.02]} />
          <meshStandardMaterial color="#3a3a55" roughness={0.3} metalness={0.6} />
        </mesh>
        <mesh position={[0, 0.4, 0.21]}>
          <boxGeometry args={[0.3, 0.03, 0.02]} />
          <meshStandardMaterial color="#3a3a55" roughness={0.3} metalness={0.6} />
        </mesh>
      </group>

      {/* ─── Zone point light (colored ambient from below) ─── */}
      <pointLight
        position={[0, 1.5, 0]}
        color={zone.borderColor}
        intensity={0.8}
        distance={w * 1.2}
      />

      {/* ─── Zone label ─── */}
      <ZoneLabel
        text={zone.name}
        position={[0, 0, 0]}
        color={zone.borderColor}
      />
    </group>
  );
}
