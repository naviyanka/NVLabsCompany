import { useMemo } from 'react';
import { zones3D } from '@/config/office3dLayout';
import { ZoneLabel } from './ZoneLabel';
import * as THREE from 'three';

/**
 * Renders the 9 named floor zones as colored planes with subtle border glow.
 */
export function ZoneFloor() {
  return (
    <group>
      {zones3D.map((zone) => (
        <ZonePlane key={zone.id} zone={zone} />
      ))}
    </group>
  );
}

interface ZonePlaneProps {
  zone: typeof zones3D[number];
}

function ZonePlane({ zone }: ZonePlaneProps) {
  const borderGeometry = useMemo(() => {
    const shape = new THREE.Shape();
    const w = zone.size[0] / 2;
    const h = zone.size[1] / 2;
    // Outer rect
    shape.moveTo(-w, -h);
    shape.lineTo(w, -h);
    shape.lineTo(w, h);
    shape.lineTo(-w, h);
    shape.closePath();
    // Inner hole
    const hole = new THREE.Path();
    const inset = 0.08;
    hole.moveTo(-w + inset, -h + inset);
    hole.lineTo(w - inset, -h + inset);
    hole.lineTo(w - inset, h - inset);
    hole.lineTo(-w + inset, h - inset);
    hole.closePath();
    shape.holes.push(hole);
    return new THREE.ShapeGeometry(shape);
  }, [zone.size]);

  return (
    <group position={zone.position}>
      {/* Floor plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <planeGeometry args={[zone.size[0], zone.size[1]]} />
        <meshStandardMaterial
          color={zone.color}
          transparent
          opacity={0.6}
          roughness={0.9}
        />
      </mesh>

      {/* Border glow */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0.02, 0]}
        geometry={borderGeometry}
      >
        <meshBasicMaterial
          color={zone.borderColor}
          transparent
          opacity={0.7}
        />
      </mesh>

      {/* Zone label */}
      <ZoneLabel
        text={zone.name}
        position={[0, 0, 0]}
        color={zone.borderColor}
      />
    </group>
  );
}
