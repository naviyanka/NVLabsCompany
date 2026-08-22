import {
  MeshBuilder,
  PBRMaterial,
  Color3,
  Vector3,
  TransformNode,
  Scene,
} from '@babylonjs/core';

/**
 * Sofa + coffee table + plant.
 */
export function createSofa(
  id: string,
  position: Vector3,
  rotationY: number,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`sofa_${id}`, scene);
  root.position = position;
  root.rotation.y = rotationY;

  const mat = new PBRMaterial(`${id}_sofaMat`, scene);
  mat.albedoColor = new Color3(0.08, 0.06, 0.04);
  mat.metallic = 0.1;
  mat.roughness = 0.9;

  // Seat
  const seat = MeshBuilder.CreateBox(`${id}_seat`, { width: 1.8, height: 0.3, depth: 0.7 }, scene);
  seat.position = new Vector3(0, 0.3, 0);
  seat.parent = root;
  seat.material = mat;
  seat.checkCollisions = true;

  // Backrest
  const back = MeshBuilder.CreateBox(`${id}_back`, { width: 1.8, height: 0.5, depth: 0.15 }, scene);
  back.position = new Vector3(0, 0.6, -0.3);
  back.parent = root;
  back.material = mat;

  // Armrests
  for (const side of [-1, 1]) {
    const arm = MeshBuilder.CreateBox(`${id}_arm_${side}`, { width: 0.12, height: 0.25, depth: 0.6 }, scene);
    arm.position = new Vector3(side * 0.85, 0.5, 0.05);
    arm.parent = root;
    arm.material = mat;
  }

  return root;
}

export function createCoffeeTable(
  id: string,
  position: Vector3,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`ctable_${id}`, scene);
  root.position = position;

  const mat = new PBRMaterial(`${id}_ctMat`, scene);
  mat.albedoColor = new Color3(0.05, 0.05, 0.08);
  mat.metallic = 0.5;
  mat.roughness = 0.4;

  const top = MeshBuilder.CreateCylinder(`${id}_top`, { diameter: 0.8, height: 0.04 }, scene);
  top.position = new Vector3(0, 0.4, 0);
  top.parent = root;
  top.material = mat;

  const leg = MeshBuilder.CreateCylinder(`${id}_leg`, { diameter: 0.06, height: 0.4 }, scene);
  leg.position = new Vector3(0, 0.2, 0);
  leg.parent = root;
  leg.material = mat;

  return root;
}

export function createPlant(
  id: string,
  position: Vector3,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`plant_${id}`, scene);
  root.position = position;

  // Pot
  const potMat = new PBRMaterial(`${id}_potMat`, scene);
  potMat.albedoColor = new Color3(0.12, 0.08, 0.05);
  potMat.roughness = 0.9;

  const pot = MeshBuilder.CreateCylinder(`${id}_pot`, { diameterTop: 0.3, diameterBottom: 0.22, height: 0.4 }, scene);
  pot.position = new Vector3(0, 0.2, 0);
  pot.parent = root;
  pot.material = potMat;

  // Foliage
  const leafMat = new PBRMaterial(`${id}_leafMat`, scene);
  leafMat.albedoColor = new Color3(0.05, 0.2, 0.08);
  leafMat.roughness = 0.95;

  const leaves = MeshBuilder.CreateSphere(`${id}_leaves`, { diameter: 0.5, segments: 6 }, scene);
  leaves.position = new Vector3(0, 0.6, 0);
  leaves.scaling = new Vector3(1, 1.3, 1);
  leaves.parent = root;
  leaves.material = leafMat;

  return root;
}
