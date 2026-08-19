import { useMemo, useCallback } from 'react';
import { useApi } from '@/hooks/useApi';
import { usePolling } from '@/hooks/usePolling';
import { agentsApi } from '@/api/agents';
import { tasksApi } from '@/api/tasks';
import { COMPANY_ID } from '@/config';
import { defaultRooms } from '@/config/officeLayout';
import { useAgentMovement } from '@/components/office/AgentMovement';
import type { Agent } from '@/types/agent';
import type { Task } from '@/types/task';
import type { PaginatedResponse } from '@/types/common';
import type {
  OfficeState,
  DelegationArrow,
  ActiveMeeting,
  OfficeEvent,
} from '@/types/office';

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
        const status: DelegationArrow['status'] = 'active';

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

/**
 * Simulated meetings heuristic for the office visualization demo.
 * There is no real meetings API endpoint backing this data. Meetings are
 * fabricated when 3+ agents are simultaneously busy, as a visual cue that
 * collaborative work may be occurring. This threshold reduces false positives
 * compared to triggering on only 2 busy agents.
 */
function computeMeetings(agents: Agent[]): ActiveMeeting[] {
  const busyAgents = agents.filter((a) => a.status === 'busy');
  const meetings: ActiveMeeting[] = [];

  if (busyAgents.length >= 3) {
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
  tasks: Task[];
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

  const meetings = useMemo(() => computeMeetings(agents), [agents]);

  // Delegate position computation to the canonical useAgentMovement hook
  const agentPositions = useAgentMovement({ agents, rooms: defaultRooms, meetings });

  const officeState = useMemo<OfficeState>(() => {
    const delegations = computeDelegations(tasks, agents);

    return {
      rooms: defaultRooms,
      agents: agentPositions,
      delegations,
      meetings,
    };
  }, [agents, tasks, agentPositions, meetings]);

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
    tasks,
    loading: agentsLoading || tasksLoading,
    error: agentsError || tasksError,
    refetch,
    stats,
  };
}
