import { useMemo } from 'react';
import type { Agent } from '@/types/agent';
import type { AgentPosition, ActiveMeeting, OfficeRoom } from '@/types/office';
import { departmentRoomMap } from '@/config/officeLayout';

interface AgentMovementProps {
  agents: Agent[];
  rooms: OfficeRoom[];
  meetings: ActiveMeeting[];
}

/**
 * Computes agent positions within rooms, handling:
 * - Assigning agents to rooms based on their department/role
 * - Positioning agents in a grid layout within each room
 * - Moving meeting participants to meeting rooms
 */
export function useAgentMovement({ agents, rooms, meetings }: AgentMovementProps): AgentPosition[] {
  return useMemo(() => {
    const positions: AgentPosition[] = [];
    const meetingParticipants = new Set<string>();

    // Identify all agents currently in meetings
    for (const meeting of meetings) {
      for (const participantId of meeting.participantIds) {
        meetingParticipants.add(participantId);
      }
    }

    // Group non-meeting agents by their assigned room
    const roomAgents: Record<string, Agent[]> = {};

    for (const agent of agents) {
      if (meetingParticipants.has(agent.id)) {
        continue; // Skip - will be positioned in meeting room
      }

      const roomId = getAgentRoomId(agent);
      if (!roomAgents[roomId]) {
        roomAgents[roomId] = [];
      }
      roomAgents[roomId].push(agent);
    }

    // Position agents in their assigned rooms (grid layout)
    for (const [roomId, agentsInRoom] of Object.entries(roomAgents)) {
      const room = rooms.find((r) => r.id === roomId);
      if (!room) continue;

      const cols = Math.max(2, Math.ceil(Math.sqrt(agentsInRoom.length)));
      const cellWidth = (room.width - 40) / cols;
      const cellHeight = 50;

      agentsInRoom.forEach((agent, index) => {
        const col = index % cols;
        const row = Math.floor(index / cols);

        positions.push({
          agentId: agent.id,
          roomId,
          x: room.x + 20 + col * cellWidth + cellWidth / 2,
          y: room.y + 40 + row * cellHeight + cellHeight / 2,
          status: getPositionStatus(agent),
        });
      });
    }

    // Position meeting participants in meeting rooms
    for (const meeting of meetings) {
      const room = rooms.find((r) => r.id === meeting.roomId);
      if (!room) continue;

      const centerX = room.x + room.width / 2;
      const centerY = room.y + room.height / 2 + 10;
      const radius = Math.min(room.width, room.height) * 0.28;
      const participantCount = meeting.participantIds.length;

      meeting.participantIds.forEach((agentId, index) => {
        const angle = (2 * Math.PI * index) / participantCount - Math.PI / 2;
        positions.push({
          agentId,
          roomId: meeting.roomId,
          x: centerX + radius * Math.cos(angle),
          y: centerY + radius * Math.sin(angle),
          status: 'meeting',
        });
      });
    }

    return positions;
  }, [agents, rooms, meetings]);
}

function getAgentRoomId(agent: Agent): string {
  const roleKeywords = agent.role.toLowerCase();
  const titleKeywords = agent.title.toLowerCase();

  for (const [keyword, roomId] of Object.entries(departmentRoomMap)) {
    if (roleKeywords.includes(keyword) || titleKeywords.includes(keyword)) {
      return roomId;
    }
  }

  return 'common-area';
}

function getPositionStatus(agent: Agent): AgentPosition['status'] {
  switch (agent.status) {
    case 'active':
    case 'busy':
      return 'working';
    case 'idle':
      return 'idle';
    case 'offline':
    case 'error':
      return 'away';
    default:
      return 'idle';
  }
}

/**
 * AgentMovement is a utility component that renders nothing -
 * it provides the useAgentMovement hook for computing agent positions.
 * Can be used as a component wrapper if needed for context.
 */
export function AgentMovement(_props: AgentMovementProps) {
  return null;
}
