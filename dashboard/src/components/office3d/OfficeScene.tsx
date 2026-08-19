import { Canvas } from '@react-three/fiber';
import { OrthographicCamera } from '@react-three/drei';
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
 *
 * Uses frameloop="demand" when paused to stop continuous GPU rendering
 * when the browser tab is not visible.
 */
export function OfficeScene({ selectedAgent, onAgentClick, onBackgroundClick, paused = false }: OfficeSceneProps) {
  return (
    <Canvas
      className="w-full h-full"
      style={{ background: '#0a0b14' }}
      gl={{ antialias: true, alpha: false }}
      onPointerMissed={onBackgroundClick}
      frameloop={paused ? 'demand' : 'always'}
    >
      {/* Isometric-style orthographic camera - zoomed out to show all 9 zones */}
      <OrthographicCamera
        makeDefault
        position={[20, 25, 20]}
        zoom={18}
        near={0.1}
        far={200}
      />

      <CameraControls />
      <Lighting />

      {/* Floor grid - large background plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]}>
        <planeGeometry args={[60, 60]} />
        <meshStandardMaterial color="#0a0b14" roughness={1} />
      </mesh>

      {/* Grid lines for reference */}
      <gridHelper args={[60, 60, '#1a1b2e', '#12131f']} position={[0, 0, 0]} />

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
