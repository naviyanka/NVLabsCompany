import { zones3D, managerCabin } from '@/config/office3dLayout';

/**
 * Atmospheric lighting setup for the 3D office.
 * Dark ambient with colored point lights per zone for mood lighting.
 */
export function Lighting() {
  return (
    <>
      {/* Global ambient - very dim for dark atmosphere */}
      <ambientLight intensity={0.15} color="#8090b0" />

      {/* Directional light from above-right for soft shadows */}
      <directionalLight
        position={[10, 20, 5]}
        intensity={0.3}
        color="#b0c4de"
        castShadow={false}
      />

      {/* Zone-specific point lights for atmospheric coloring */}
      {zones3D.map((zone) => (
        <pointLight
          key={zone.id}
          position={[zone.position[0], 4, zone.position[2]]}
          intensity={0.6}
          color={zone.borderColor}
          distance={8}
          decay={2}
        />
      ))}

      {/* Manager cabin special lighting */}
      <pointLight
        position={[managerCabin.position[0], 5, managerCabin.position[2]]}
        intensity={0.8}
        color={managerCabin.borderColor}
        distance={8}
        decay={2}
      />

      {/* Overhead spots for key areas */}
      <spotLight
        position={[0, 15, 0]}
        intensity={0.2}
        angle={Math.PI / 4}
        penumbra={0.8}
        color="#4060a0"
      />
    </>
  );
}
