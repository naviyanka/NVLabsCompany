import { ArcRotateCamera, Vector3, Scene } from '@babylonjs/core';

/**
 * Isometric-style ArcRotateCamera.
 * Left-drag=rotate, right-drag=pan, scroll=zoom.
 * Constrained to prevent floor-clip and camera flip.
 */
export function setupCamera(scene: Scene, canvas: HTMLCanvasElement): ArcRotateCamera {
  const camera = new ArcRotateCamera(
    'officeCamera',
    -Math.PI / 4,       // alpha: horizontal rotation (45° from front)
    Math.PI / 3.5,      // beta: vertical angle (~51°, nice isometric)
    90,                  // radius: distance from target
    new Vector3(0, 0, 0), // target: center of office
    scene,
  );

  camera.attachControl(canvas, true);

  // Zoom limits
  camera.lowerRadiusLimit = 20;
  camera.upperRadiusLimit = 100;

  // Vertical angle limits (no floor clip, no top flip)
  camera.lowerBetaLimit = 0.3;          // ~17° from vertical
  camera.upperBetaLimit = Math.PI / 2.5; // ~72° from vertical

  // Pan settings
  camera.panningSensibility = 50;

  // Smooth inertia
  camera.inertia = 0.85;
  camera.panningInertia = 0.85;

  // Scroll zoom speed
  camera.wheelPrecision = 15;
  camera.wheelDeltaPercentage = 0.02;

  // Mouse buttons: left=rotate, right=pan, middle=zoom (default)
  camera.inputs.attached.pointers.buttons = [0, 2, 1];

  return camera;
}
