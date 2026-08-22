import {
  HemisphericLight,
  DirectionalLight,
  Vector3,
  Color3,
  Scene,
} from '@babylonjs/core';

/**
 * Layered lighting for dark cinematic office.
 * Hemisphere for ambient fill, directional for shadows/depth.
 */
export function setupLighting(scene: Scene): void {
  // Hemisphere: ground dark, sky dim blue-white
  const hemi = new HemisphericLight('hemi', new Vector3(0, 1, 0), scene);
  hemi.intensity = 0.35;
  hemi.diffuse = new Color3(0.6, 0.65, 0.8);      // cool white
  hemi.groundColor = new Color3(0.02, 0.03, 0.06); // very dark floor bounce
  hemi.specular = new Color3(0.1, 0.1, 0.15);

  // Main directional from above-right for depth
  const dir = new DirectionalLight('dirLight', new Vector3(-0.5, -1, -0.3), scene);
  dir.intensity = 0.4;
  dir.diffuse = new Color3(0.7, 0.75, 0.9);
  dir.specular = new Color3(0.3, 0.3, 0.5);
}
