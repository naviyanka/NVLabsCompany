import {
  MeshBuilder,
  PBRMaterial,
  Color3,
  Texture,
  Scene,
} from '@babylonjs/core';

/** Office dimensions */
export const OFFICE_WIDTH = 60;
export const OFFICE_DEPTH = 40;

/**
 * Large dark polished floor with subtle tile grid.
 * PBR material: dark, slight metalness, subtle reflections.
 */
export function createFloor(scene: Scene): void {
  const floor = MeshBuilder.CreateGround(
    'floor',
    { width: OFFICE_WIDTH, height: OFFICE_DEPTH, subdivisions: 1 },
    scene,
  );
  floor.position.y = 0;

  const mat = new PBRMaterial('floorMat', scene);
  mat.albedoColor = new Color3(0.04, 0.05, 0.08);  // very dark blue-black
  mat.metallic = 0.15;
  mat.roughness = 0.7;
  mat.reflectivityColor = new Color3(0.05, 0.06, 0.1);

  // Create procedural tile grid via a dynamic texture
  const gridSize = 512;
  const gridTex = new Texture('data:image/svg+xml,' + encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="${gridSize}" height="${gridSize}">
      <rect width="${gridSize}" height="${gridSize}" fill="#0a0d18"/>
      ${Array.from({ length: 30 }, (_, i) => `
        <line x1="${(i + 1) * (gridSize / 30)}" y1="0" x2="${(i + 1) * (gridSize / 30)}" y2="${gridSize}" stroke="#151a2a" stroke-width="1"/>
        <line x1="0" y1="${(i + 1) * (gridSize / 30)}" x2="${gridSize}" y2="${(i + 1) * (gridSize / 30)}" stroke="#151a2a" stroke-width="1"/>
      `).join('')}
    </svg>
  `), scene);
  gridTex.uScale = 15;
  gridTex.vScale = 10;
  mat.albedoTexture = gridTex;

  floor.material = mat;
  floor.receiveShadows = true;
}
