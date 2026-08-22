import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  Color3,
  Vector3,
  Scene,
  Mesh,
} from '@babylonjs/core';
import { OFFICE_WIDTH, OFFICE_DEPTH } from './Floor';

const WALL_HEIGHT = 3.5;
const WALL_THICKNESS = 0.4;

/**
 * Complete outer perimeter walls with collision.
 * Dark metal panels + blue emissive edge strips at base.
 */
export function createOuterWalls(scene: Scene): void {
  const wallMat = new PBRMaterial('outerWallMat', scene);
  wallMat.albedoColor = new Color3(0.06, 0.07, 0.12);
  wallMat.metallic = 0.6;
  wallMat.roughness = 0.4;
  wallMat.reflectivityColor = new Color3(0.08, 0.1, 0.2);

  const edgeMat = new StandardMaterial('edgeGlow', scene);
  edgeMat.emissiveColor = new Color3(0.15, 0.3, 0.9);   // blue glow
  edgeMat.diffuseColor = new Color3(0.05, 0.1, 0.3);
  edgeMat.alpha = 0.9;

  const hw = OFFICE_WIDTH / 2;
  const hd = OFFICE_DEPTH / 2;

  // Back wall (Z negative)
  createWallSegment('wallBack', OFFICE_WIDTH, WALL_HEIGHT, WALL_THICKNESS,
    new Vector3(0, WALL_HEIGHT / 2, -hd), 0, wallMat, edgeMat, scene);

  // Front wall (Z positive) — with gap for main gate (center 4 units)
  const frontSideWidth = (OFFICE_WIDTH - 5) / 2;
  createWallSegment('wallFrontL', frontSideWidth, WALL_HEIGHT, WALL_THICKNESS,
    new Vector3(-(frontSideWidth / 2 + 2.5), WALL_HEIGHT / 2, hd), 0, wallMat, edgeMat, scene);
  createWallSegment('wallFrontR', frontSideWidth, WALL_HEIGHT, WALL_THICKNESS,
    new Vector3((frontSideWidth / 2 + 2.5), WALL_HEIGHT / 2, hd), 0, wallMat, edgeMat, scene);

  // Gate frame posts
  createWallSegment('gateL', WALL_THICKNESS, WALL_HEIGHT + 1, WALL_THICKNESS * 2,
    new Vector3(-2.5, (WALL_HEIGHT + 1) / 2, hd), 0, wallMat, edgeMat, scene);
  createWallSegment('gateR', WALL_THICKNESS, WALL_HEIGHT + 1, WALL_THICKNESS * 2,
    new Vector3(2.5, (WALL_HEIGHT + 1) / 2, hd), 0, wallMat, edgeMat, scene);

  // Left wall (X negative)
  createWallSegment('wallLeft', WALL_THICKNESS, WALL_HEIGHT, OFFICE_DEPTH,
    new Vector3(-hw, WALL_HEIGHT / 2, 0), 0, wallMat, edgeMat, scene);

  // Right wall (X positive)
  createWallSegment('wallRight', WALL_THICKNESS, WALL_HEIGHT, OFFICE_DEPTH,
    new Vector3(hw, WALL_HEIGHT / 2, 0), 0, wallMat, edgeMat, scene);
}

function createWallSegment(
  name: string,
  width: number,
  height: number,
  depth: number,
  position: Vector3,
  rotationY: number,
  wallMat: PBRMaterial,
  edgeMat: StandardMaterial,
  scene: Scene,
): void {
  // Main wall body
  const wall = MeshBuilder.CreateBox(name, { width, height, depth }, scene);
  wall.position = position;
  wall.rotation.y = rotationY;
  wall.material = wallMat;
  wall.checkCollisions = true;

  // Blue edge strip at base
  const edgeWidth = width > depth ? width : depth;
  const edge = MeshBuilder.CreateBox(name + '_edge', {
    width: width > depth ? width : 0.1,
    height: 0.08,
    depth: depth > width ? depth : 0.1,
  }, scene);
  edge.position = position.clone();
  edge.position.y = 0.04;
  edge.rotation.y = rotationY;
  edge.material = edgeMat;
}
