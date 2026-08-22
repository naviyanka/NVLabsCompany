import { Engine, Scene, Color4 } from '@babylonjs/core';
import { setupCamera } from './OfficeCamera';
import { setupLighting } from './OfficeLighting';
import { createFloor } from './environment/Floor';
import { createOuterWalls } from './environment/OuterWalls';
import { createSignage } from './environment/Signage';
import { createEnvironmentDetails } from './environment/EnvironmentDetails';
import { buildInteriorWalls } from './layout/WallBuilder';
import { DoorManager } from './doors/DoorManager';
import { populateRooms } from './furniture/RoomPopulator';
import { AgentManager } from './agents/AgentManager';
import { setupPostProcessing } from './effects/PostProcessing';
import { rooms } from './layout/roomDefinitions';
import type { SelectionState } from './BabylonCanvas';

/**
 * Initialize the complete 3D office scene.
 * onSelect callback bridges 3D picks to React UI panels.
 */
export function initOfficeScene(
  engine: Engine,
  canvas: HTMLCanvasElement,
  onSelect?: (selection: SelectionState) => void,
): Scene {
  const scene = new Scene(engine);

  scene.clearColor = new Color4(0.008, 0.03, 0.09, 1);
  scene.autoClear = true;
  scene.autoClearDepthAndStencil = true;

  setupCamera(scene, canvas);
  setupLighting(scene);

  createFloor(scene);
  createOuterWalls(scene);
  buildInteriorWalls(scene);

  const doorManager = new DoorManager(scene);

  populateRooms(scene);
  createSignage(scene);
  createEnvironmentDetails(scene);

  const agentManager = new AgentManager(scene);

  // Post-processing (glow + bloom + FXAA)
  setupPostProcessing(scene);

  // Click handler
  scene.onPointerDown = (_evt, pickResult) => {
    if (!pickResult?.hit || !pickResult.pickedMesh) {
      onSelect?.({ type: null });
      return;
    }

    const mesh = pickResult.pickedMesh;

    // Door toggle
    if (doorManager.handleClick(mesh.name)) return;

    // Agent selection
    if (mesh.metadata?.type === 'agent') {
      const agent = agentManager.getAgentByMesh(mesh.name, mesh.metadata);
      if (agent) {
        onSelect?.({ type: 'agent', agent });
        return;
      }
    }

    // Room floor selection (check if mesh name starts with "floor_")
    if (mesh.name.startsWith('floor_')) {
      const roomId = mesh.name.replace('floor_', '');
      const room = rooms.find((r) => r.id === roomId);
      if (room) {
        const agentCount = Array.from(agentManager.agentData.values())
          .filter((a) => a.roomId === roomId).length;
        onSelect?.({ type: 'room', room, agentCount });
        return;
      }
    }

    // Background click — deselect
    onSelect?.({ type: null });
  };

  return scene;
}
