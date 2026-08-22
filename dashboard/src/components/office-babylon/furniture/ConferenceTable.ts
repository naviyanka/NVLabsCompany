import {
  MeshBuilder,
  PBRMaterial,
  Color3,
  Vector3,
  TransformNode,
  Scene,
} from '@babylonjs/core';

/**
 * Conference/meeting table with N chairs around it.
 */
export function createConferenceTable(
  id: string,
  position: Vector3,
  chairCount: number,
  tableWidth: number,
  tableDepth: number,
  scene: Scene,
): TransformNode {
  const root = new TransformNode(`conf_${id}`, scene);
  root.position = position;

  const tableMat = new PBRMaterial(`${id}_tableMat`, scene);
  tableMat.albedoColor = new Color3(0.06, 0.07, 0.12);
  tableMat.metallic = 0.4;
  tableMat.roughness = 0.5;

  // Table top
  const top = MeshBuilder.CreateBox(`${id}_top`, { width: tableWidth, height: 0.06, depth: tableDepth }, scene);
  top.position = new Vector3(0, 0.74, 0);
  top.parent = root;
  top.material = tableMat;
  top.checkCollisions = true;

  // Table legs
  const legMat = new PBRMaterial(`${id}_legMat`, scene);
  legMat.albedoColor = new Color3(0.04, 0.04, 0.07);
  legMat.metallic = 0.7;
  legMat.roughness = 0.3;

  const lw = tableWidth / 2 - 0.2;
  const ld = tableDepth / 2 - 0.2;
  for (const [lx, lz] of [[-lw, -ld], [lw, -ld], [-lw, ld], [lw, ld]]) {
    const leg = MeshBuilder.CreateCylinder(`${id}_leg`, { diameter: 0.06, height: 0.74 }, scene);
    leg.position = new Vector3(lx, 0.37, lz);
    leg.parent = root;
    leg.material = legMat;
  }

  // Chairs around the table
  const chairMat = new PBRMaterial(`${id}_chairMat`, scene);
  chairMat.albedoColor = new Color3(0.05, 0.05, 0.09);
  chairMat.metallic = 0.2;
  chairMat.roughness = 0.8;

  for (let i = 0; i < chairCount; i++) {
    const angle = (i / chairCount) * Math.PI * 2;
    const radius = Math.max(tableWidth, tableDepth) / 2 + 0.5;
    const cx = Math.cos(angle) * radius;
    const cz = Math.sin(angle) * radius;

    // Simple chair: seat + back
    const seat = MeshBuilder.CreateBox(`${id}_cseat_${i}`, { width: 0.4, height: 0.05, depth: 0.4 }, scene);
    seat.position = new Vector3(cx, 0.42, cz);
    seat.parent = root;
    seat.material = chairMat;

    const back = MeshBuilder.CreateBox(`${id}_cback_${i}`, { width: 0.38, height: 0.4, depth: 0.04 }, scene);
    // Backrest faces away from table center
    const backDist = radius + 0.18;
    back.position = new Vector3(Math.cos(angle) * backDist, 0.62, Math.sin(angle) * backDist);
    back.rotation.y = -angle + Math.PI;
    back.parent = root;
    back.material = chairMat;
  }

  return root;
}
