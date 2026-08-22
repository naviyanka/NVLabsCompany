import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  PointLight,
  Color3,
  Vector3,
  Scene,
} from '@babylonjs/core';
import { OFFICE_WIDTH, OFFICE_DEPTH } from './Floor';

/**
 * Environmental polish: hallway wall lights, ceiling panels, cable conduits, pillars.
 */
export function createEnvironmentDetails(scene: Scene): void {
  createHallwayLights(scene);
  createCeilingPanels(scene);
  createPillars(scene);
}

/** Small wall-mounted lights along hallways */
function createHallwayLights(scene: Scene): void {
  const lightMat = new StandardMaterial('hallLightMat', scene);
  lightMat.emissiveColor = new Color3(0.2, 0.35, 0.8);
  lightMat.diffuseColor = new Color3(0.1, 0.15, 0.3);

  // Lights along the main horizontal hallway (Z ~ -12)
  const hallZ = -12;
  for (let x = -24; x <= 24; x += 8) {
    // Wall light fixture
    const fixture = MeshBuilder.CreateBox(`hlight_${x}`, { width: 0.3, height: 0.15, depth: 0.08 }, scene);
    fixture.position = new Vector3(x, 2.5, hallZ);
    fixture.material = lightMat;

    // Actual point light
    const light = new PointLight(`hplight_${x}`, new Vector3(x, 2.2, hallZ), scene);
    light.intensity = 0.3;
    light.diffuse = new Color3(0.3, 0.5, 1.0);
    light.range = 5;
  }

  // Vertical hallway lights (along left/right corridors)
  for (const x of [-20, 20]) {
    for (let z = -15; z <= 15; z += 7) {
      const fixture = MeshBuilder.CreateBox(`vlight_${x}_${z}`, { width: 0.08, height: 0.15, depth: 0.3 }, scene);
      fixture.position = new Vector3(x, 2.5, z);
      fixture.material = lightMat;

      const light = new PointLight(`vplight_${x}_${z}`, new Vector3(x, 2.2, z), scene);
      light.intensity = 0.2;
      light.diffuse = new Color3(0.2, 0.4, 0.9);
      light.range = 4;
    }
  }
}

/** Ceiling panels above rooms for depth */
function createCeilingPanels(scene: Scene): void {
  const ceilMat = new PBRMaterial('ceilMat', scene);
  ceilMat.albedoColor = new Color3(0.03, 0.04, 0.07);
  ceilMat.metallic = 0.3;
  ceilMat.roughness = 0.8;

  // Large ceiling covering most of the office
  const ceiling = MeshBuilder.CreateGround('ceiling', { width: OFFICE_WIDTH - 2, height: OFFICE_DEPTH - 2 }, scene);
  ceiling.position = new Vector3(0, 3.4, 0);
  ceiling.rotation.x = Math.PI; // flip to face down
  ceiling.material = ceilMat;

  // Ceiling beams (structural)
  const beamMat = new PBRMaterial('beamMat', scene);
  beamMat.albedoColor = new Color3(0.04, 0.05, 0.09);
  beamMat.metallic = 0.6;
  beamMat.roughness = 0.4;

  for (let x = -20; x <= 20; x += 10) {
    const beam = MeshBuilder.CreateBox(`beamX_${x}`, { width: 0.2, height: 0.15, depth: OFFICE_DEPTH - 4 }, scene);
    beam.position = new Vector3(x, 3.3, 0);
    beam.material = beamMat;
  }
  for (let z = -15; z <= 15; z += 10) {
    const beam = MeshBuilder.CreateBox(`beamZ_${z}`, { width: OFFICE_WIDTH - 4, height: 0.15, depth: 0.2 }, scene);
    beam.position = new Vector3(0, 3.3, z);
    beam.material = beamMat;
  }
}

/** Structural pillars at key intersections */
function createPillars(scene: Scene): void {
  const pillarMat = new PBRMaterial('pillarMat', scene);
  pillarMat.albedoColor = new Color3(0.06, 0.07, 0.12);
  pillarMat.metallic = 0.5;
  pillarMat.roughness = 0.4;

  const pillarPositions: [number, number][] = [
    [-20, -12], [20, -12],
    [-20, 0], [20, 0],
    [-20, 10], [20, 10],
  ];

  for (const [px, pz] of pillarPositions) {
    const pillar = MeshBuilder.CreateCylinder(`pillar_${px}_${pz}`, {
      diameter: 0.5,
      height: 3.4,
    }, scene);
    pillar.position = new Vector3(px, 1.7, pz);
    pillar.material = pillarMat;
    pillar.checkCollisions = true;

    // Base
    const base = MeshBuilder.CreateCylinder(`pbase_${px}_${pz}`, {
      diameterTop: 0.6,
      diameterBottom: 0.7,
      height: 0.1,
    }, scene);
    base.position = new Vector3(px, 0.05, pz);
    base.material = pillarMat;
  }
}
