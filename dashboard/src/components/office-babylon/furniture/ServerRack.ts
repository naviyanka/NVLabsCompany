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
 * Server rack with LED indicators.
 */
export function createServerRack(
  id: string,
  position: Vector3,
  rotationY: number,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`rack_${id}`, scene);
  root.position = position;
  root.rotation.y = rotationY;

  const rackMat = new PBRMaterial(`${id}_rackMat`, scene);
  rackMat.albedoColor = new Color3(0.04, 0.04, 0.07);
  rackMat.metallic = 0.7;
  rackMat.roughness = 0.3;

  // Main cabinet
  const cabinet = MeshBuilder.CreateBox(`${id}_cab`, { width: 0.7, height: 2.2, depth: 0.8 }, scene);
  cabinet.position = new Vector3(0, 1.1, 0);
  cabinet.parent = root;
  cabinet.material = rackMat;
  cabinet.checkCollisions = true;

  // Front panel (slightly recessed)
  const panel = MeshBuilder.CreateBox(`${id}_panel`, { width: 0.6, height: 2.0, depth: 0.02 }, scene);
  panel.position = new Vector3(0, 1.1, 0.4);
  panel.parent = root;
  const panelMat = new PBRMaterial(`${id}_panelMat`, scene);
  panelMat.albedoColor = new Color3(0.02, 0.02, 0.04);
  panelMat.metallic = 0.5;
  panelMat.roughness = 0.4;
  panel.material = panelMat;

  // LED indicators (rows of small emissive dots)
  const ledColors = ['#06B6D4', '#22C55E', '#22C55E', '#F59E0B', '#22C55E', '#06B6D4'];
  for (let i = 0; i < 6; i++) {
    const led = MeshBuilder.CreateBox(`${id}_led_${i}`, { width: 0.04, height: 0.04, depth: 0.01 }, scene);
    led.position = new Vector3(-0.2 + (i % 3) * 0.15, 1.6 - Math.floor(i / 3) * 0.3, 0.42);
    led.parent = root;
    const ledMat = new StandardMaterial(`${id}_ledMat_${i}`, scene);
    ledMat.emissiveColor = Color3.FromHexString(ledColors[i]);
    ledMat.diffuseColor = Color3.FromHexString(ledColors[i]).scale(0.3);
    led.material = ledMat;
  }

  return root;
}
