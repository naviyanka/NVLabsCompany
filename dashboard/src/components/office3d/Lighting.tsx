import { zones3D, managerCabin } from '@/config/office3dLayout';

/**
 * Office lighting: brighter ambient so geometry is visible,
 * colored zone lights for atmosphere, overhead directional for depth.
 */
export function Lighting() {
  return (
    <>
      {/* Global ambient - moderate so you can see walls/furniture */}
      <ambientLight intensity={0.35} color="#8090c0" />

      {/* Main directional - simulates overhead office fluorescents */}
      <directionalLight
        position={[10, 20, 10]}
        intensity={0.5}
        color="#c0d0f0"
      />

      {/* Secondary fill from opposite side */}
      <directionalLight
        position={[-15, 12, -10]}
        intensity={0.2}
        color="#8090b0"
      />

      {/* Zone-specific colored point lights (from above each zone) */}
      {zones3D.map((zone) => (
        <pointLight
          key={zone.id}
          position={[zone.position[0], 3, zone.position[2]]}
          intensity={0.8}
          color={zone.borderColor}
          distance={10}
          decay={2}
        />
      ))}

      {/* Manager cabin accent */}
      <pointLight
        position={[managerCabin.position[0], 4, managerCabin.position[2]]}
        intensity={1.0}
        color={managerCabin.borderColor}
        distance={8}
        decay={2}
      />
    </>
  );
}
