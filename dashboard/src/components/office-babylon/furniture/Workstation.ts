import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  Color3,
  Vector3,
  TransformNode,
  Scene,
} from '@babylonjs/core';

/**
 * Reusable workstation: desk + monitor + keyboard + chair + desk lamp.
 * All meshes parented to a single TransformNode for easy placement.
 */
export function createWorkstation(
  id: string,
  position: Vector3,
  rotationY: number,
  screenColor: string,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`ws_${id}`, scene);
  root.position = position;
  root.rotation.y = rotationY;

  // ─── Desk ───
  const desk = MeshBuilder.CreateBox(`${id}_desk`, { width: 1.6, height: 0.06, depth: 0.8 }, scene);
  desk.position = new Vector3(0, 0.72, 0);
  desk.parent = root;
  const deskMat = new PBRMaterial(`${id}_deskMat`, scene);
  deskMat.albedoColor = new Color3(0.08, 0.09, 0.14);
  deskMat.metallic = 0.3;
  deskMat.roughness = 0.6;
  desk.material = deskMat;
  desk.checkCollisions = true;

  // Desk legs (4)
  const legMat = new PBRMaterial(`${id}_legMat`, scene);
  legMat.albedoColor = new Color3(0.05, 0.05, 0.08);
  legMat.metallic = 0.7;
  legMat.roughness = 0.3;
  for (const [lx, lz] of [[-0.7, -0.35], [0.7, -0.35], [-0.7, 0.35], [0.7, 0.35]]) {
    const leg = MeshBuilder.CreateCylinder(`${id}_leg`, { diameter: 0.04, height: 0.72 }, scene);
    leg.position = new Vector3(lx, 0.36, lz);
    leg.parent = root;
    leg.material = legMat;
  }

  // ─── Monitor ───
  const monitorStand = MeshBuilder.CreateCylinder(`${id}_mstand`, { diameter: 0.08, height: 0.2 }, scene);
  monitorStand.position = new Vector3(0, 0.85, -0.2);
  monitorStand.parent = root;
  monitorStand.material = legMat;

  const monitorFrame = MeshBuilder.CreateBox(`${id}_mframe`, { width: 0.7, height: 0.45, depth: 0.03 }, scene);
  monitorFrame.position = new Vector3(0, 1.1, -0.2);
  monitorFrame.parent = root;
  monitorFrame.material = deskMat;

  // Screen (emissive)
  const screen = MeshBuilder.CreateBox(`${id}_screen`, { width: 0.62, height: 0.38, depth: 0.01 }, scene);
  screen.position = new Vector3(0, 1.1, -0.185);
  screen.parent = root;
  const screenMat = new StandardMaterial(`${id}_screenMat`, scene);
  screenMat.emissiveColor = Color3.FromHexString(screenColor).scale(0.5);
  screenMat.diffuseColor = new Color3(0.02, 0.03, 0.05);
  screen.material = screenMat;

  // ─── Keyboard ───
  const keyboard = MeshBuilder.CreateBox(`${id}_kb`, { width: 0.4, height: 0.015, depth: 0.15 }, scene);
  keyboard.position = new Vector3(0, 0.74, 0.1);
  keyboard.parent = root;
  keyboard.material = deskMat;

  // ─── Mouse ───
  const mouse = MeshBuilder.CreateBox(`${id}_mouse`, { width: 0.06, height: 0.02, depth: 0.1 }, scene);
  mouse.position = new Vector3(0.35, 0.74, 0.1);
  mouse.parent = root;
  mouse.material = deskMat;

  // ─── Chair ───
  const chairRoot = new TransformNode(`${id}_chair`, scene);
  chairRoot.position = new Vector3(0, 0, 0.55);
  chairRoot.parent = root;

  // Seat
  const seat = MeshBuilder.CreateBox(`${id}_seat`, { width: 0.45, height: 0.06, depth: 0.45 }, scene);
  seat.position = new Vector3(0, 0.42, 0);
  seat.parent = chairRoot;
  const chairMat = new PBRMaterial(`${id}_chairMat`, scene);
  chairMat.albedoColor = new Color3(0.06, 0.06, 0.1);
  chairMat.metallic = 0.2;
  chairMat.roughness = 0.8;
  seat.material = chairMat;

  // Backrest
  const back = MeshBuilder.CreateBox(`${id}_back`, { width: 0.42, height: 0.5, depth: 0.05 }, scene);
  back.position = new Vector3(0, 0.7, -0.2);
  back.parent = chairRoot;
  back.material = chairMat;

  // Chair pole
  const pole = MeshBuilder.CreateCylinder(`${id}_pole`, { diameter: 0.04, height: 0.35 }, scene);
  pole.position = new Vector3(0, 0.2, 0);
  pole.parent = chairRoot;
  pole.material = legMat;

  // Chair base (5 star)
  const cbase = MeshBuilder.CreateCylinder(`${id}_cbase`, { diameterTop: 0.35, diameterBottom: 0.4, height: 0.04 }, scene);
  cbase.position = new Vector3(0, 0.04, 0);
  cbase.parent = chairRoot;
  cbase.material = legMat;

  return root;
}
