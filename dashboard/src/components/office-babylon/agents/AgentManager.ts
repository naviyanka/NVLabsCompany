import { Vector3, Scene, TransformNode } from '@babylonjs/core';
import { createAgentModel, type AgentData } from './AgentModel';
import { AgentMover } from './AgentMovement';
import { planPath } from '../navigation/PathPlanner';
import { rooms } from '../layout/roomDefinitions';

/**
 * Demo agent definitions placed in various rooms.
 */
const DEMO_AGENTS: AgentData[] = [
  { id: 'alpha', name: 'Alpha', role: 'Backend Dev', status: 'working', roomId: 'open-workspace', color: '#22C55E', model: 'GPT-4o', currentTask: 'Building REST API' },
  { id: 'beta', name: 'Beta', role: 'Frontend Dev', status: 'working', roomId: 'open-workspace', color: '#3B82F6', model: 'Claude 3.5', currentTask: 'Dashboard components' },
  { id: 'gamma', name: 'Gamma', role: 'QA Engineer', status: 'review', roomId: 'team-cabin-3', color: '#F97316', model: 'Gemini', currentTask: 'Reviewing PR #142' },
  { id: 'delta', name: 'Delta', role: 'DevOps', status: 'working', roomId: 'team-cabin-4', color: '#06B6D4', model: 'GPT-4o', currentTask: 'Deploying v2.3' },
  { id: 'omega', name: 'Omega', role: 'Data Analyst', status: 'idle', roomId: 'team-cabin-1', color: '#8B5CF6', model: 'Claude 3.5', currentTask: 'Awaiting task' },
  { id: 'nova', name: 'Nova', role: 'Researcher', status: 'working', roomId: 'team-cabin-2', color: '#EAB308', model: 'Gemini', currentTask: 'Training model' },
  { id: 'cipher', name: 'Cipher', role: 'Security', status: 'review', roomId: 'server-room', color: '#EF4444', model: 'GPT-4o', currentTask: 'Security audit' },
  { id: 'echo', name: 'Echo', role: 'Support', status: 'working', roomId: 'team-cabin-5', color: '#EC4899', model: 'GPT-4o', currentTask: 'Ticket #8823' },
  { id: 'pulse', name: 'Pulse', role: 'Automation', status: 'idle', roomId: 'team-cabin-6', color: '#06B6D4', model: 'Gemini', currentTask: 'Monitoring pipelines' },
  { id: 'nexus', name: 'Nexus', role: 'PM', status: 'working', roomId: 'meeting-hall', color: '#A78BFA', model: 'GPT-4o', currentTask: 'Sprint coordination' },
  { id: 'forge', name: 'Forge', role: 'Full Stack', status: 'working', roomId: 'open-workspace', color: '#14B8A6', model: 'Claude 3.5', currentTask: 'Notification system' },
  { id: 'architect', name: 'Architect', role: 'Manager', status: 'working', roomId: 'manager-cabin', color: '#6366F1', model: 'GPT-4o', currentTask: 'Delegating tasks' },
];

/**
 * Creates and places all agents in their assigned rooms.
 * Supports movement via walkAgentToRoom().
 */
export class AgentManager {
  public readonly agents: Map<string, TransformNode> = new Map();
  public readonly agentData: Map<string, AgentData> = new Map();
  private readonly _movers: Map<string, AgentMover> = new Map();
  private readonly _scene: Scene;

  constructor(scene: Scene) {
    this._scene = scene;

    for (const data of DEMO_AGENTS) {
      const pos = this._getAgentPosition(data);
      const model = createAgentModel(data, pos, scene);
      this.agents.set(data.id, model);
      this.agentData.set(data.id, data);

      const mover = new AgentMover(model);
      this._movers.set(data.id, mover);
    }

    // Register frame update for all movers
    scene.onBeforeRenderObservable.add(() => {
      const dt = scene.getEngine().getDeltaTime() / 1000;
      for (const mover of this._movers.values()) {
        mover.update(dt);
      }
    });

    // Demo: move one agent between rooms every 8 seconds
    this._startDemoMovement();
  }

  /** Move an agent to a different room */
  walkAgentToRoom(agentId: string, targetRoomId: string): void {
    const data = this.agentData.get(agentId);
    const mover = this._movers.get(agentId);
    if (!data || !mover || mover.isMoving) return;

    const path = planPath(data.roomId, targetRoomId);
    if (path.length < 2) return;

    mover.walkPath(path, 2.5, () => {
      data.roomId = targetRoomId;
    });
  }

  /** Get agent data by mesh metadata */
  getAgentByMesh(meshName: string, metadata: any): AgentData | undefined {
    if (metadata?.agentId) {
      return this.agentData.get(metadata.agentId);
    }
    return undefined;
  }

  private _startDemoMovement(): void {
    const demoRoutes = [
      { agentId: 'nexus', rooms: ['meeting-hall', 'open-workspace', 'manager-cabin', 'meeting-hall'] },
      { agentId: 'alpha', rooms: ['open-workspace', 'discussion-room-1', 'open-workspace'] },
    ];

    let routeIdx = 0;
    let stepIdx = 0;

    const moveNext = () => {
      const route = demoRoutes[routeIdx % demoRoutes.length];
      const target = route.rooms[stepIdx % route.rooms.length];
      this.walkAgentToRoom(route.agentId, target);

      stepIdx++;
      if (stepIdx >= route.rooms.length) {
        stepIdx = 0;
        routeIdx++;
      }
    };

    // Start first move after 3 seconds, then every 10 seconds
    setTimeout(moveNext, 3000);
    setInterval(moveNext, 10000);
  }

  private _getAgentPosition(data: AgentData): Vector3 {
    const room = rooms.find((r) => r.id === data.roomId);
    if (!room) return new Vector3(0, 0, 0);

    // Spread agents within the room (offset by index to avoid stacking)
    const agents = DEMO_AGENTS.filter((a) => a.roomId === data.roomId);
    const idx = agents.indexOf(data);
    const count = agents.length;

    // Distribute in a line or grid within room
    const spacing = Math.min(room.width / (count + 1), 2.5);
    const startX = room.x - (count - 1) * spacing / 2;

    return new Vector3(
      startX + idx * spacing,
      0,
      room.z + 0.5, // Slightly offset from center toward front
    );
  }
}
