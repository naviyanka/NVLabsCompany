import {
  MeshBuilder,
  StandardMaterial,
  DynamicTexture,
  Color3,
  Vector3,
  Scene,
} from '@babylonjs/core';
import { rooms } from '../layout/roomDefinitions';

/**
 * Creates 3D room signs above each door — dark panel with emissive text.
 * Also creates the main gate NVLabs emblem.
 */
export function createSignage(scene: Scene): void {
  for (const room of rooms) {
    createRoomSign(room.id, room.name, room.x, room.z, room.width, room.depth, room.color, room.doors[0], scene);
  }

  // Main gate emblem
  createGateEmblem(scene);
}

function createRoomSign(
  id: string,
  name: string,
  cx: number,
  cz: number,
  width: number,
  depth: number,
  color: string,
  doorDir: string,
  scene: Scene,
): void {
  // Position sign above the door
  let signX = cx;
  let signZ = cz;
  let signRotY = 0;

  switch (doorDir) {
    case 'south':
      signZ = cz + depth / 2;
      break;
    case 'north':
      signZ = cz - depth / 2;
      signRotY = Math.PI;
      break;
    case 'east':
      signX = cx + width / 2;
      signRotY = -Math.PI / 2;
      break;
    case 'west':
      signX = cx - width / 2;
      signRotY = Math.PI / 2;
      break;
  }

  const signWidth = Math.min(name.length * 0.18 + 0.6, 3.5);
  const signHeight = 0.4;

  // Sign panel
  const panel = MeshBuilder.CreatePlane(`sign_${id}`, { width: signWidth, height: signHeight }, scene);
  panel.position = new Vector3(signX, 2.9, signZ);
  panel.rotation.y = signRotY;

  // Dynamic texture for text
  const texRes = 512;
  const tex = new DynamicTexture(`signTex_${id}`, { width: texRes, height: 64 }, scene, true);
  const ctx = tex.getContext();

  // Background
  ctx.fillStyle = 'rgba(5, 8, 20, 0.9)';
  ctx.fillRect(0, 0, texRes, 64);

  // Border
  const c = Color3.FromHexString(color);
  const borderColor = `rgba(${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)}, 0.6)`;
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, texRes - 2, 62);

  // Text
  ctx.fillStyle = `rgb(${Math.round(c.r * 255)}, ${Math.round(c.g * 255)}, ${Math.round(c.b * 255)})`;
  ctx.font = 'bold 24px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(name.toUpperCase(), texRes / 2, 32);

  tex.update();

  const mat = new StandardMaterial(`signMat_${id}`, scene);
  mat.diffuseTexture = tex;
  mat.emissiveColor = Color3.FromHexString(color).scale(0.4);
  mat.specularColor = Color3.Black();
  mat.backFaceCulling = false;
  panel.material = mat;
}

function createGateEmblem(scene: Scene): void {
  const emblemWidth = 4;
  const emblemHeight = 1.2;

  const panel = MeshBuilder.CreatePlane('gate_emblem', { width: emblemWidth, height: emblemHeight }, scene);
  panel.position = new Vector3(0, 3.5, 20.3);
  panel.rotation.y = Math.PI; // Face inward

  const texRes = 512;
  const tex = new DynamicTexture('gateEmblemTex', { width: texRes, height: 128 }, scene, true);
  const ctx = tex.getContext();

  // Dark background
  ctx.fillStyle = '#050a18';
  ctx.fillRect(0, 0, texRes, 128);

  // Blue border glow
  ctx.strokeStyle = 'rgba(59, 130, 246, 0.8)';
  ctx.lineWidth = 3;
  ctx.strokeRect(2, 2, texRes - 4, 124);

  // NVLabs text
  ctx.fillStyle = '#3B82F6';
  ctx.font = 'bold 48px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('NVLABS', texRes / 2, 50);

  // Subtitle
  ctx.fillStyle = '#64748B';
  ctx.font = '20px monospace';
  ctx.fillText('MISSION CONTROL', texRes / 2, 95);

  tex.update();

  const mat = new StandardMaterial('gateEmblemMat', scene);
  mat.diffuseTexture = tex;
  mat.emissiveColor = new Color3(0.15, 0.3, 0.8);
  mat.specularColor = Color3.Black();
  mat.backFaceCulling = false;
  panel.material = mat;

  // Also create a second emblem facing outward (for when you look from outside)
  const panelOuter = panel.clone('gate_emblem_outer');
  panelOuter.position.z = 20.5;
  panelOuter.rotation.y = 0;
}
