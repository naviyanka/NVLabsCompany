import type { AgentData, AgentStatus } from './agents/AgentModel';
import type { AgentManager } from './agents/AgentManager';

/**
 * Bridge API for React ↔ Babylon communication.
 * Allows external code (WebSocket handlers, React UI) to control the 3D scene.
 *
 * Usage:
 *   const bridge = new OfficeBridge(agentManager);
 *   bridge.moveAgent('alpha', 'meeting-hall');
 *   bridge.updateAgentStatus('alpha', 'idle');
 */
export class OfficeBridge {
  private _agentManager: AgentManager;

  constructor(agentManager: AgentManager) {
    this._agentManager = agentManager;
  }

  /** Move an agent to a room (navigates via hallways) */
  moveAgent(agentId: string, targetRoomId: string): void {
    this._agentManager.walkAgentToRoom(agentId, targetRoomId);
  }

  /** Update agent status (changes glow color) */
  updateAgentStatus(agentId: string, newStatus: AgentStatus): void {
    const data = this._agentManager.agentData.get(agentId);
    if (data) {
      data.status = newStatus;
      // ponytail: visual update requires re-creating materials — skip for now,
      // agent glow color reflects initial status. Full re-render on status change
      // if real-time visual feedback needed.
    }
  }

  /** Update agent's current task */
  updateAgentTask(agentId: string, task: string): void {
    const data = this._agentManager.agentData.get(agentId);
    if (data) {
      data.currentTask = task;
    }
  }

  /** Get all agent data for React panels */
  getAllAgents(): AgentData[] {
    return Array.from(this._agentManager.agentData.values());
  }

  /** Get agents in a specific room */
  getAgentsInRoom(roomId: string): AgentData[] {
    return Array.from(this._agentManager.agentData.values())
      .filter((a) => a.roomId === roomId);
  }
}
