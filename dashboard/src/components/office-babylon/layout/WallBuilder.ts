import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  Color3,
  Vector3,
  Scene,
} from '@babylonjs/core';
import { rooms, type RoomDefinition } from './roomDefinitions';

const WALL_THICK = 0.25;
const DOOR_WIDTH = 2.5;

/**
 * Generates interior walls for all rooms + colored floor sections + emissive accent strips.
 */
export function buildInteriorWalls(scene: Scene): void {
  const wallMat = createWallMaterial(scene);

  for (const room of rooms) {
    createRoomFloor(room, scene);
    createRoomWalls(room, wallMat, scene);
    createAccentStrip(room, scene);
  }
}

function createWallMaterial(scene: Scene): PBRMaterial {
  const mat = new PBRMaterial('interiorWallMat', scene);
  mat.albedoColor = new Color3(0.05, 0.06, 0.1);
  mat.metallic = 0.5;
  mat.roughness = 0.5;
  mat.reflectivityColor = new Color3(0.06, 0.08, 0.15);
  return mat;
}

function createRoomFloor(room: RoomDefinition, scene: Scene): void {
  // Skip hallway/workspace — they use the main floor
  if (room.type === 'hallway') return;

  const floor = MeshBuilder.CreateGround(
    `floor_${room.id}`,
    { width: room.width - 0.5, height: room.depth - 0.5 },
    scene,
  );
  floor.position = new Vector3(room.x, 0.02, room.z);

  const mat = new PBRMaterial(`floorMat_${room.id}`, scene);
  // Subtle tinted floor per room
  const c = Color3.FromHexString(room.color);
  mat.albedoColor = Color3.Lerp(new Color3(0.04, 0.05, 0.08), c, 0.12);
  mat.metallic = 0.1;
  mat.roughness = 0.8;
  floor.material = mat;
}

function createRoomWalls(room: RoomDefinition, wallMat: PBRMaterial, scene: Scene): void {
  const hw = room.width / 2;
  const hd = room.depth / 2;
  const h = room.wallHeight;

  // 4 walls — skip segment where door is
  // North wall (Z - side)
  if (!room.doors.includes('north')) {
    createWallBox(`${room.id}_wallN`, room.width, h, WALL_THICK,
      new Vector3(room.x, h / 2, room.z - hd), wallMat, scene);
  } else {
    // Two segments with door gap
    const segW = (room.width - DOOR_WIDTH) / 2;
    createWallBox(`${room.id}_wallN_L`, segW, h, WALL_THICK,
      new Vector3(room.x - segW / 2 - DOOR_WIDTH / 2, h / 2, room.z - hd), wallMat, scene);
    createWallBox(`${room.id}_wallN_R`, segW, h, WALL_THICK,
      new Vector3(room.x + segW / 2 + DOOR_WIDTH / 2, h / 2, room.z - hd), wallMat, scene);
  }

  // South wall (Z + side)
  if (!room.doors.includes('south')) {
    createWallBox(`${room.id}_wallS`, room.width, h, WALL_THICK,
      new Vector3(room.x, h / 2, room.z + hd), wallMat, scene);
  } else {
    const segW = (room.width - DOOR_WIDTH) / 2;
    createWallBox(`${room.id}_wallS_L`, segW, h, WALL_THICK,
      new Vector3(room.x - segW / 2 - DOOR_WIDTH / 2, h / 2, room.z + hd), wallMat, scene);
    createWallBox(`${room.id}_wallS_R`, segW, h, WALL_THICK,
      new Vector3(room.x + segW / 2 + DOOR_WIDTH / 2, h / 2, room.z + hd), wallMat, scene);
  }

  // West wall (X - side)
  if (!room.doors.includes('west')) {
    createWallBox(`${room.id}_wallW`, WALL_THICK, h, room.depth,
      new Vector3(room.x - hw, h / 2, room.z), wallMat, scene);
  } else {
    const segD = (room.depth - DOOR_WIDTH) / 2;
    createWallBox(`${room.id}_wallW_T`, WALL_THICK, h, segD,
      new Vector3(room.x - hw, h / 2, room.z - segD / 2 - DOOR_WIDTH / 2), wallMat, scene);
    createWallBox(`${room.id}_wallW_B`, WALL_THICK, h, segD,
      new Vector3(room.x - hw, h / 2, room.z + segD / 2 + DOOR_WIDTH / 2), wallMat, scene);
  }

  // East wall (X + side)
  if (!room.doors.includes('east')) {
    createWallBox(`${room.id}_wallE`, WALL_THICK, h, room.depth,
      new Vector3(room.x + hw, h / 2, room.z), wallMat, scene);
  } else {
    const segD = (room.depth - DOOR_WIDTH) / 2;
    createWallBox(`${room.id}_wallE_T`, WALL_THICK, h, segD,
      new Vector3(room.x + hw, h / 2, room.z - segD / 2 - DOOR_WIDTH / 2), wallMat, scene);
    createWallBox(`${room.id}_wallE_B`, WALL_THICK, h, segD,
      new Vector3(room.x + hw, h / 2, room.z + segD / 2 + DOOR_WIDTH / 2), wallMat, scene);
  }
}

function createWallBox(
  name: string, width: number, height: number, depth: number,
  position: Vector3, mat: PBRMaterial, scene: Scene,
): void {
  const wall = MeshBuilder.CreateBox(name, { width, height, depth }, scene);
  wall.position = position;
  wall.material = mat;
  wall.checkCollisions = true;
}

/** Emissive accent strip at the base of each room — uses room color */
function createAccentStrip(room: RoomDefinition, scene: Scene): void {
  if (room.type === 'hallway' || room.type === 'workspace') return;

  const mat = new StandardMaterial(`accent_${room.id}`, scene);
  mat.emissiveColor = Color3.FromHexString(room.color).scale(0.7);
  mat.diffuseColor = Color3.FromHexString(room.color).scale(0.3);
  mat.alpha = 0.85;

  const hw = room.width / 2;
  const hd = room.depth / 2;

  // North strip
  const stripN = MeshBuilder.CreateBox(`${room.id}_stripN`, { width: room.width, height: 0.06, depth: 0.08 }, scene);
  stripN.position = new Vector3(room.x, 0.03, room.z - hd + 0.04);
  stripN.material = mat;

  // South strip
  const stripS = MeshBuilder.CreateBox(`${room.id}_stripS`, { width: room.width, height: 0.06, depth: 0.08 }, scene);
  stripS.position = new Vector3(room.x, 0.03, room.z + hd - 0.04);
  stripS.material = mat;

  // West strip
  const stripW = MeshBuilder.CreateBox(`${room.id}_stripW`, { width: 0.08, height: 0.06, depth: room.depth }, scene);
  stripW.position = new Vector3(room.x - hw + 0.04, 0.03, room.z);
  stripW.material = mat;

  // East strip
  const stripE = MeshBuilder.CreateBox(`${room.id}_stripE`, { width: 0.08, height: 0.06, depth: room.depth }, scene);
  stripE.position = new Vector3(room.x + hw - 0.04, 0.03, room.z);
  stripE.material = mat;
}
