import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  Color3,
  Vector3,
  TransformNode,
  Scene,
  PointLight,
} from '@babylonjs/core';

export type AgentStatus = 'working' | 'idle' | 'review' | 'offline' | 'error' | 'paused';

export interface AgentData {
  id: string;
  name: string;
  role: string;
  status: AgentStatus;
  roomId: string;
  color: string;
  model?: string;
  currentTask?: string;
}

const STATUS_COLORS: Record<AgentStatus, string> = {
  working: '#22C55E',
  idle: '#3B82F6',
  review: '#F97316',
  offline: '#64748B',
  error: '#EF4444',
  paused: '#EAB308',
};

/**
 * Creates a futuristic robot agent mesh.
 * Body (capsule) + head (sphere) + status ring + antenna + nameplate light.
 */
export function createAgentModel(data: AgentData, position: Vector3, scene: Scene): TransformNode {
  const root = new TransformNode(`agent_${data.id}`, scene);
  root.position = position;

  const statusColor = Color3.FromHexString(STATUS_COLORS[data.status]);
  const accentColor = Color3.FromHexString(data.color);

  // ─── Body (capsule shape via cylinder + 2 hemispheres) ───
  const bodyMat = new PBRMaterial(`${data.id}_bodyMat`, scene);
  bodyMat.albedoColor = new Color3(0.08, 0.09, 0.14);
  bodyMat.metallic = 0.6;
  bodyMat.roughness = 0.35;

  const body = MeshBuilder.CreateCylinder(`${data.id}_body`, {
    diameter: 0.35,
    height: 0.5,
  }, scene);
  body.position = new Vector3(0, 0.45, 0);
  body.parent = root;
  body.material = bodyMat;

  // Body accent ring
  const ring = MeshBuilder.CreateTorus(`${data.id}_ring`, {
    diameter: 0.38,
    thickness: 0.03,
  }, scene);
  ring.position = new Vector3(0, 0.5, 0);
  ring.parent = root;
  const ringMat = new StandardMaterial(`${data.id}_ringMat`, scene);
  ringMat.emissiveColor = accentColor.scale(0.7);
  ringMat.diffuseColor = accentColor.scale(0.3);
  ring.material = ringMat;

  // ─── Head (sphere) ───
  const head = MeshBuilder.CreateSphere(`${data.id}_head`, { diameter: 0.3, segments: 12 }, scene);
  head.position = new Vector3(0, 0.85, 0);
  head.parent = root;

  const headMat = new PBRMaterial(`${data.id}_headMat`, scene);
  headMat.albedoColor = new Color3(0.06, 0.07, 0.12);
  headMat.metallic = 0.7;
  headMat.roughness = 0.25;
  head.material = headMat;

  // Face/screen (small emissive rectangle on head front)
  const face = MeshBuilder.CreatePlane(`${data.id}_face`, { width: 0.15, height: 0.08 }, scene);
  face.position = new Vector3(0, 0.85, 0.14);
  face.parent = root;
  const faceMat = new StandardMaterial(`${data.id}_faceMat`, scene);
  faceMat.emissiveColor = statusColor;
  faceMat.diffuseColor = Color3.Black();
  face.material = faceMat;

  // ─── Antenna ───
  const antenna = MeshBuilder.CreateCylinder(`${data.id}_ant`, { diameter: 0.02, height: 0.15 }, scene);
  antenna.position = new Vector3(0, 1.05, 0);
  antenna.parent = root;
  antenna.material = bodyMat;

  const antTip = MeshBuilder.CreateSphere(`${data.id}_antTip`, { diameter: 0.05 }, scene);
  antTip.position = new Vector3(0, 1.13, 0);
  antTip.parent = root;
  const tipMat = new StandardMaterial(`${data.id}_tipMat`, scene);
  tipMat.emissiveColor = statusColor;
  tipMat.diffuseColor = statusColor.scale(0.3);
  antTip.material = tipMat;

  // ─── Status glow ring (on ground) ───
  const statusRing = MeshBuilder.CreateTorus(`${data.id}_sring`, {
    diameter: 0.5,
    thickness: 0.02,
  }, scene);
  statusRing.position = new Vector3(0, 0.02, 0);
  statusRing.rotation.x = Math.PI / 2;
  statusRing.parent = root;
  const sringMat = new StandardMaterial(`${data.id}_sringMat`, scene);
  sringMat.emissiveColor = statusColor;
  sringMat.diffuseColor = Color3.Black();
  sringMat.alpha = 0.7;
  statusRing.material = sringMat;

  // ─── Status point light ───
  const glow = new PointLight(`${data.id}_glow`, new Vector3(0, 0.5, 0), scene);
  glow.parent = root;
  glow.diffuse = statusColor;
  glow.intensity = 0.3;
  glow.range = 2;

  // Make pickable
  body.isPickable = true;
  head.isPickable = true;
  body.metadata = { agentId: data.id, type: 'agent' };
  head.metadata = { agentId: data.id, type: 'agent' };

  return root;
}
