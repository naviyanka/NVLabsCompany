import { useMemo, useCallback } from 'react';
import { useApi } from '@/hooks/useApi';
import { usePolling } from '@/hooks/usePolling';
import { agentsApi } from '@/api/agents';
import { tasksApi } from '@/api/tasks';
import { COMPANY_ID } from '@/config';
import { defaultRooms, departmentRoomMap } from '@/config/officeLayout';
import type { Agent } from '@/types/agent';
import type { Task } from '@/types/task';
import type { PaginatedResponse } from '@/types/common';
import type {
  OfficeState,
  AgentPosition,
  DelegationArrow,
  ActiveMeeting,
  OfficeEvent,
} from '@/types/office';

function getAgentRoomId(agent: Agent): string {
  // Map agent to room based on role/title keywords
  const roleKeywords = agent.role.toLowerCase();
  const titleKeywords = agent.title.toLowerCase();

  for (const [keyword, roomId] of Object.entries(departmentRoomMap)) {
    if (roleKeywords.includes(keyword) || titleKeywords.includes(keyword)) {
      return roomId;
    }
  }

  // Default: common area
  return 'common-area';
}

function getAgentPositionStatus(agent: Agent): AgentPosition['status'] {
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

function computeAgentPositions(agents: Agent[]): AgentPosition[] {
  // Group agents by room
  const roomAgents: Record<string, Agent[]> = {};
  for (const agent of agents) {
    const roomId = getAgentRoomId(agent);
    if (!roomAgents[roomId]) {
      roomAgents[roomId] = [];
    }
    roomAgents[roomId].push(agent);
  }

  const positions: AgentPosition[] = [];

  for (const [roomId, agentsInRoom] of Object.entries(roomAgents)) {
    const room = defaultRooms.find((r) => r.id === roomId);
    if (!room) continue;

    // Arrange agents in a grid within the room
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
        status: getAgentPositionStatus(agent),
      });
    });
  }

  return positions;
}

function computeDelegations(tasks: Task[], agents: Agent[]): DelegationArrow[] {
  const delegations: DelegationArrow[] = [];
  const agentMap = new Map(agents.map((a) => [a.id, a]));

  for (const task of tasks) {
    if (
      task.parent_task_id &&
      task.assigned_agent_id &&
      (task.status === 'in_progress' || task.status === 'assigned')
    ) {
      // Find parent task to get the delegating agent
      const parentTask = tasks.find((t) => t.id === task.parent_task_id);
      if (parentTask?.assigned_agent_id && agentMap.has(parentTask.assigned_agent_id)) {
        const status =
          task.status === 'in_progress'
            ? 'active'
            : task.status === 'completed'
              ? 'completed'
              : 'active';

        delegations.push({
          id: `del-${task.id}`,
          fromAgentId: parentTask.assigned_agent_id,
          toAgentId: task.assigned_agent_id,
          taskTitle: task.title,
          status,
        });
      }
    }
  }

  return delegations;
}

function computeMeetings(agents: Agent[]): ActiveMeeting[] {
  // Derive meetings from agents that are busy and in similar departments
  const busyAgents = agents.filter((a) => a.status === 'busy');
  const meetings: ActiveMeeting[] = [];

  if (busyAgents.length >= 2) {
    meetings.push({
      id: 'meeting-active-1',
      roomId: 'meeting-room-1',
      title: 'Sprint Planning',
      type: 'planning',
      participantIds: busyAgents.slice(0, Math.min(4, busyAgents.length)).map((a) => a.id),
    });
  }

  return meetings;
}

function generateEvents(agents: Agent[], tasks: Task[]): OfficeEvent[] {
  const events: OfficeEvent[] = [];
  const now = new Date();

  // Generate events from recently completed tasks
  const completedTasks = tasks
    .filter((t) => t.status === 'completed' && t.completed_at)
    .sort((a, b) => {
      const dateA = a.completed_at ? new Date(a.completed_at).getTime() : 0;
      const dateB = b.completed_at ? new Date(b.completed_at).getTime() : 0;
      return dateB - dateA;
    })
    .slice(0, 5);

  completedTasks.forEach((task, i) => {
    const agent = agents.find((a) => a.id === task.assigned_agent_id);
    events.push({
      id: `evt-task-${task.id}`,
      timestamp: task.completed_at || now.toISOString(),
      type: 'task_completed',
      message: `${agent?.name || 'Agent'} completed: ${task.title}`,
      agentName: agent?.name,
    });

    // Add delegation event for tasks with parent
    if (task.parent_task_id && i < 3) {
      const parentTask = tasks.find((t) => t.id === task.parent_task_id);
      const parentAgent = agents.find((a) => a.id === parentTask?.assigned_agent_id);
      if (parentAgent) {
        events.push({
          id: `evt-del-${task.id}`,
          timestamp: task.started_at || now.toISOString(),
          type: 'delegation',
          message: `${parentAgent.name} delegated task to ${agent?.name || 'agent'}`,
          agentName: parentAgent.name,
        });
      }
    }
  });

  // Add status events for agents with errors
  agents
    .filter((a) => a.status === 'error')
    .slice(0, 2)
    .forEach((agent) => {
      events.push({
        id: `evt-err-${agent.id}`,
        timestamp: now.toISOString(),
        type: 'issue',
        message: `${agent.name} encountered an error`,
        agentName: agent.name,
      });
    });

  return events.sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
}

export interface UseOfficeReturn {
  officeState: OfficeState;
  events: OfficeEvent[];
  agents: Agent[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
  stats: {
    agentsOnline: number;
    tasksRunning: number;
    meetingsActive: number;
  };
}

export function useOffice(): UseOfficeReturn {
  const {
    data: agentsData,
    loading: agentsLoading,
    error: agentsError,
    refetch: refetchAgents,
  } = useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(COMPANY_ID, { page_size: 50 }),
    [COMPANY_ID]
  );

  const {
    data: tasksData,
    loading: tasksLoading,
    error: tasksError,
    refetch: refetchTasks,
  } = useApi<PaginatedResponse<Task>>(
    () => tasksApi.list(COMPANY_ID, { page_size: 100 }),
    [COMPANY_ID]
  );

  const refetch = useCallback(() => {
    refetchAgents();
    refetchTasks();
  }, [refetchAgents, refetchTasks]);

  usePolling(refetch, { interval: 10000, enabled: true });

  const agents = agentsData?.items || [];
  const tasks = tasksData?.items || [];

  const officeState = useMemo<OfficeState>(() => {
    const agentPositions = computeAgentPositions(agents);
    const delegations = computeDelegations(tasks, agents);
    const meetings = computeMeetings(agents);

    return {
      rooms: defaultRooms,
      agents: agentPositions,
      delegations,
      meetings,
    };
  }, [agents, tasks]);

  const events = useMemo(() => generateEvents(agents, tasks), [agents, tasks]);

  const stats = useMemo(
    () => ({
      agentsOnline: agents.filter((a) => a.status !== 'offline').length,
      tasksRunning: tasks.filter((t) => t.status === 'in_progress').length,
      meetingsActive: officeState.meetings.length,
    }),
    [agents, tasks, officeState.meetings]
  );

  return {
    officeState,
    events,
    agents,
    loading: agentsLoading || tasksLoading,
    error: agentsError || tasksError,
    refetch,
    stats,
  };
}
