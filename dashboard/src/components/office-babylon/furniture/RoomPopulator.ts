import { Vector3, Scene, MeshBuilder, PBRMaterial, Color3 } from '@babylonjs/core';
import { rooms } from '../layout/roomDefinitions';
import { createWorkstation } from './Workstation';
import { createConferenceTable } from './ConferenceTable';
import { createServerRack } from './ServerRack';
import { createSofa, createCoffeeTable, createPlant } from './Lounge';

/**
 * Populates all rooms with appropriate furniture based on room type.
 */
export function populateRooms(scene: Scene): void {
  for (const room of rooms) {
    switch (room.type) {
      case 'team':
        populateTeamCabin(room.id, room.x, room.z, room.width, room.depth, room.color, scene);
        break;
      case 'workspace':
        populateOpenWorkspace(room.x, room.z, room.width, room.depth, room.color, scene);
        break;
      case 'manager':
        populateManagerCabin(room.x, room.z, room.color, scene);
        break;
      case 'meeting':
        populateMeetingHall(room.x, room.z, room.color, scene);
        break;
      case 'discussion':
        populateDiscussion(room.id, room.x, room.z, room.color, scene);
        break;
      case 'server':
        populateServerRoom(room.x, room.z, scene);
        break;
      case 'rest':
        populateRestArea(room.x, room.z, scene);
        break;
      case 'reception':
        populateReception(room.x, room.z, room.color, scene);
        break;
      case 'waiting':
        populateWaiting(room.x, room.z, scene);
        break;
    }
    // Plants in corners of most rooms
    if (room.type !== 'hallway' && room.type !== 'storage' && room.type !== 'utility') {
      createPlant(`${room.id}_p1`, new Vector3(room.x - room.width / 2 + 0.6, 0, room.z - room.depth / 2 + 0.6), scene);
      createPlant(`${room.id}_p2`, new Vector3(room.x + room.width / 2 - 0.6, 0, room.z - room.depth / 2 + 0.6), scene);
    }
  }
}

function populateTeamCabin(id: string, cx: number, cz: number, w: number, d: number, color: string, scene: Scene): void {
  // 4 desks in 2 rows of 2
  const offsets = [
    [-1.8, -1.2, 0],
    [1.8, -1.2, 0],
    [-1.8, 1.2, Math.PI],
    [1.8, 1.2, Math.PI],
  ];
  offsets.forEach(([ox, oz, rot], i) => {
    createWorkstation(`${id}_ws_${i}`, new Vector3(cx + ox, 0, cz + oz), rot, color, scene);
  });
}

function populateOpenWorkspace(cx: number, cz: number, w: number, d: number, color: string, scene: Scene): void {
  // 4x3 grid of workstations (12 total) — proper spacing for 25×8 room
  const cols = 4;
  const rows = 3;
  const spacingX = 4.5;
  const spacingZ = 2.8;
  const startX = cx - (cols - 1) * spacingX / 2;
  const startZ = cz - (rows - 1) * spacingZ / 2;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = startX + c * spacingX;
      const z = startZ + r * spacingZ;
      const rot = r % 2 === 0 ? 0 : Math.PI;
      createWorkstation(`ows_${r}_${c}`, new Vector3(x, 0, z), rot, color, scene);
    }
  }
}

function populateManagerCabin(cx: number, cz: number, color: string, scene: Scene): void {
  // Large desk
  createWorkstation('mgr_desk', new Vector3(cx, 0, cz - 2), 0, color, scene);
  // Visitor chairs
  createSofa('mgr_sofa', new Vector3(cx - 3, 0, cz + 3), 0, scene);
  createCoffeeTable('mgr_ct', new Vector3(cx - 3, 0, cz + 1.5), scene);
}

function populateMeetingHall(cx: number, cz: number, color: string, scene: Scene): void {
  createConferenceTable('meeting_main', new Vector3(cx, 0, cz), 8, 4, 2, scene);
}

function populateDiscussion(id: string, cx: number, cz: number, color: string, scene: Scene): void {
  createConferenceTable(id, new Vector3(cx, 0, cz), 6, 2.5, 2.5, scene);
}

function populateServerRoom(cx: number, cz: number, scene: Scene): void {
  for (let i = 0; i < 3; i++) {
    createServerRack(`srv_${i}`, new Vector3(cx - 3 + i * 3, 0, cz - 2), 0, scene);
  }
  createWorkstation('srv_ws', new Vector3(cx + 4, 0, cz + 3), Math.PI, '#06B6D4', scene);
}

function populateRestArea(cx: number, cz: number, scene: Scene): void {
  createSofa('rest_s1', new Vector3(cx - 3, 0, cz - 2), 0, scene);
  createSofa('rest_s2', new Vector3(cx + 3, 0, cz - 2), 0, scene);
  createCoffeeTable('rest_ct', new Vector3(cx, 0, cz), scene);

  // Vending machine
  const vm = MeshBuilder.CreateBox('rest_vend', { width: 0.8, height: 1.8, depth: 0.6 }, scene);
  vm.position = new Vector3(cx + 5, 0.9, cz + 3);
  const vmMat = new PBRMaterial('rest_vendMat', scene);
  vmMat.albedoColor = new Color3(0.05, 0.06, 0.1);
  vmMat.metallic = 0.6;
  vmMat.roughness = 0.4;
  vm.material = vmMat;
}

function populateReception(cx: number, cz: number, color: string, scene: Scene): void {
  createWorkstation('recv_ws', new Vector3(cx, 0, cz - 2), Math.PI, color, scene);
}

function populateWaiting(cx: number, cz: number, scene: Scene): void {
  createSofa('wait_s1', new Vector3(cx - 4, 0, cz - 2), Math.PI / 2, scene);
  createSofa('wait_s2', new Vector3(cx + 4, 0, cz - 2), -Math.PI / 2, scene);
  createCoffeeTable('wait_ct', new Vector3(cx, 0, cz - 2), scene);
}
