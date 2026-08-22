import {
  GlowLayer,
  DefaultRenderingPipeline,
  Color4,
  Scene,
} from '@babylonjs/core';

/**
 * Post-processing effects: glow layer for emissive elements + rendering pipeline
 * with subtle bloom, FXAA, and vignette for cinematic look.
 */
export function setupPostProcessing(scene: Scene): void {
  // Glow layer — makes all emissive materials bloom
  const glow = new GlowLayer('glowLayer', scene, {
    mainTextureFixedSize: 512,
    blurKernelSize: 32,
  });
  glow.intensity = 0.6;

  // Default rendering pipeline — bloom, FXAA, vignette
  const pipeline = new DefaultRenderingPipeline('pipeline', true, scene, [scene.activeCamera!]);

  // Bloom
  pipeline.bloomEnabled = true;
  pipeline.bloomThreshold = 0.3;
  pipeline.bloomWeight = 0.4;
  pipeline.bloomKernel = 64;
  pipeline.bloomScale = 0.5;

  // Anti-aliasing
  pipeline.fxaaEnabled = true;

  // Vignette (subtle darkening at edges)
  pipeline.imageProcessingEnabled = true;
  pipeline.imageProcessing.vignetteEnabled = true;
  pipeline.imageProcessing.vignetteWeight = 2.0;
  pipeline.imageProcessing.vignetteCentreX = 0;
  pipeline.imageProcessing.vignetteCentreY = 0;
  pipeline.imageProcessing.vignetteColor = new Color4(0, 0, 0, 1);
  pipeline.imageProcessing.vignetteStretch = 0.5;

  // Slight color grading — cool tint
  pipeline.imageProcessing.colorCurvesEnabled = true;
  if (pipeline.imageProcessing.colorCurves) {
    pipeline.imageProcessing.colorCurves.globalHue = 220;
    pipeline.imageProcessing.colorCurves.globalSaturation = 10;
  }
}
