import { Canvas } from '@react-three/fiber';
import { Lighting } from './Lighting';
import { ZoneFloor } from './ZoneFloor';
import { Desk } from './Desk';
import { AgentCharacter } from './AgentCharacter';
import { ManagerCabin } from './ManagerCabin';
import { DelegationAnimation } from './DelegationAnimation';
import { ReportAnimation } from './ReportAnimation';
import { CameraControls } from './CameraControls';
import { mockAgents3D, zones3D } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';

interface OfficeSceneProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onBackgroundClick: () => void;
  /** When true, the render loop is paused to save GPU resources (e.g. tab hidden) */
  paused?: boolean;
}

/**
 * Main React Three Fiber Canvas with isometric camera view.
 * Composes the entire 3D office scene.
 */
export function OfficeScene({ selectedAgent, onAgentClick, onBackgroundClick, paused = false }: OfficeSceneProps) {
  return (
    <Canvas
      className="w-full h-full"
      style={{ background: '#0a0b14' }}
      gl={{ antialias: true, alpha: false }}
      orthographic
      camera={{ position: [20, 25, 20], zoom: 16, near: 0.1, far: 200 }}
      frameloop={paused ? 'demand' : 'always'}
    >
      <CameraControls />
      <Lighting />

      {/* ═══ OFFICE ENVIRONMENT ═══ */}

      {/* Main floor - polished dark concrete with slight reflection */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-3, -0.05, -3]} onClick={onBackgroundClick}>
        <planeGeometry args={[52, 40]} />
        <meshStandardMaterial color="#0e1018" roughness={0.7} metalness={0.15} />
      </mesh>

      {/* Floor tile grid */}
      <gridHelper args={[52, 26, '#1e2036', '#151726']} position={[-3, 0, -3]} />

      {/* ─── Walls ─── */}
      {/* Back wall */}
      <mesh position={[-3, 2, -19.5]}>
        <boxGeometry args={[54, 4, 0.3]} />
        <meshStandardMaterial color="#12141f" roughness={0.85} />
      </mesh>
      {/* Back wall baseboard accent */}
      <mesh position={[-3, 0.15, -19.35]}>
        <boxGeometry args={[54, 0.3, 0.1]} />
        <meshStandardMaterial color="#2a2d45" roughness={0.6} metalness={0.3} />
      </mesh>

      {/* Left wall */}
      <mesh position={[-29, 2, -3]}>
        <boxGeometry args={[0.3, 4, 38]} />
        <meshStandardMaterial color="#10121c" roughness={0.85} />
      </mesh>
      {/* Left wall baseboard */}
      <mesh position={[-28.85, 0.15, -3]}>
        <boxGeometry args={[0.1, 0.3, 38]} />
        <meshStandardMaterial color="#2a2d45" roughness={0.6} metalness={0.3} />
      </mesh>

      {/* Right wall */}
      <mesh position={[23, 2, -3]}>
        <boxGeometry args={[0.3, 4, 38]} />
        <meshStandardMaterial color="#10121c" roughness={0.85} />
      </mesh>

      {/* Front wall (partial - low wall / railing) */}
      <mesh position={[-3, 0.6, 16]}>
        <boxGeometry args={[54, 1.2, 0.2]} />
        <meshStandardMaterial color="#181a28" roughness={0.8} metalness={0.1} />
      </mesh>

      {/* ─── Pillars / Columns ─── */}
      {([[-18, -19], [-18, 10], [12, -19], [12, 10]] as [number, number][]).map(([x, z], i) => (
        <group key={`pillar-${i}`} position={[x, 0, z]}>
          <mesh position={[0, 2, 0]}>
            <boxGeometry args={[0.6, 4, 0.6]} />
            <meshStandardMaterial color="#1a1d2e" roughness={0.5} metalness={0.4} />
          </mesh>
          {/* Pillar base */}
          <mesh position={[0, 0.1, 0]}>
            <boxGeometry args={[0.9, 0.2, 0.9]} />
            <meshStandardMaterial color="#2a2d45" roughness={0.4} metalness={0.5} />
          </mesh>
          {/* Pillar top cap */}
          <mesh position={[0, 3.95, 0]}>
            <boxGeometry args={[0.8, 0.1, 0.8]} />
            <meshStandardMaterial color="#2a2d45" roughness={0.4} metalness={0.5} />
          </mesh>
        </group>
      ))}

      {/* ─── Ceiling beams ─── */}
      {[-15, -5, 5, 15].map((x, i) => (
        <mesh key={`beam-x-${i}`} position={[x, 3.9, -3]}>
          <boxGeometry args={[0.3, 0.2, 38]} />
          <meshStandardMaterial color="#0f1120" roughness={0.9} />
        </mesh>
      ))}
      {[-14, -3, 8].map((z, i) => (
        <mesh key={`beam-z-${i}`} position={[-3, 3.9, z]}>
          <boxGeometry args={[52, 0.2, 0.3]} />
          <meshStandardMaterial color="#0f1120" roughness={0.9} />
        </mesh>
      ))}

      {/* ─── Ceiling lights (fluorescent strip style) ─── */}
      {([[-12, -12], [-12, 4], [6, -12], [6, 4]] as [number, number][]).map(([x, z], i) => (
        <group key={`ceiling-light-${i}`} position={[x, 3.85, z]}>
          <mesh>
            <boxGeometry args={[4, 0.05, 0.4]} />
            <meshStandardMaterial
              color="#eef4ff"
              emissive="#4060aa"
              emissiveIntensity={0.4}
              roughness={0.2}
            />
          </mesh>
          <pointLight color="#3050aa" intensity={0.5} distance={12} position={[0, -0.5, 0]} />
        </group>
      ))}

      {/* ─── Wall decorations ─── */}
      {/* Whiteboard on back wall */}
      <mesh position={[-12, 2.5, -19.2]}>
        <boxGeometry args={[5, 2.5, 0.08]} />
        <meshStandardMaterial color="#1e2238" roughness={0.3} metalness={0.1} />
      </mesh>
      <mesh position={[-12, 2.5, -19.15]}>
        <boxGeometry args={[4.6, 2.2, 0.02]} />
        <meshStandardMaterial color="#252a40" roughness={0.2} metalness={0.05} />
      </mesh>

      {/* Monitor/display on back wall */}
      <mesh position={[8, 2.5, -19.2]}>
        <boxGeometry args={[4, 2.2, 0.1]} />
        <meshStandardMaterial color="#0a0c15" roughness={0.2} metalness={0.6} />
      </mesh>
      <mesh position={[8, 2.5, -19.1]}>
        <boxGeometry args={[3.6, 1.9, 0.02]} />
        <meshStandardMaterial
          color="#0a1525"
          emissive="#1a3050"
          emissiveIntensity={0.3}
          roughness={0.1}
        />
      </mesh>

      {/* ─── Potted plants (corner decor) ─── */}
      {([[-27, 0, -17], [21, 0, -17], [-27, 0, 14]] as [number, number, number][]).map(([x, y, z], i) => (
        <group key={`plant-${i}`} position={[x, y, z]}>
          {/* Pot */}
          <mesh position={[0, 0.4, 0]}>
            <cylinderGeometry args={[0.4, 0.3, 0.8, 8]} />
            <meshStandardMaterial color="#2a2018" roughness={0.8} />
          </mesh>
          {/* Plant leaves (sphere cluster) */}
          <mesh position={[0, 1.2, 0]}>
            <sphereGeometry args={[0.6, 8, 8]} />
            <meshStandardMaterial color="#1a4020" roughness={0.9} />
          </mesh>
          <mesh position={[0.3, 1.4, 0.2]}>
            <sphereGeometry args={[0.4, 8, 8]} />
            <meshStandardMaterial color="#1d4a25" roughness={0.9} />
          </mesh>
        </group>
      ))}

      {/* ─── Extra ambient lighting ─── */}
      <pointLight position={[-3, 6, -3]} color="#1a2040" intensity={0.4} distance={30} />
      <pointLight position={[-20, 5, -10]} color="#1a1a3a" intensity={0.2} distance={15} />
      <pointLight position={[15, 5, 5]} color="#1a1a3a" intensity={0.2} distance={15} />

      {/* Zone floors */}
      <ZoneFloor />

      {/* Desks with agents */}
      {zones3D.map((zone) =>
        zone.desks.map((desk) => {
          const agent = mockAgents3D.find((a) => a.deskId === desk.id);
          return (
            <group key={desk.id}>
              <Desk
                position={desk.position}
                isOccupied={!!agent && agent.status !== 'offline'}
                screenColor={zone.borderColor}
              />
              {agent && (
                <AgentCharacter
                  agent={agent}
                  position={desk.position}
                  onClick={onAgentClick}
                  isSelected={selectedAgent?.id === agent.id}
                />
              )}
            </group>
          );
        })
      )}

      {/* Manager cabin */}
      <ManagerCabin
        onAgentClick={onAgentClick}
        isSelected={selectedAgent?.id === 'agent-manager'}
      />

      {/* Animations */}
      <DelegationAnimation />
      <ReportAnimation />
    </Canvas>
  );
}
