import { useMemo } from 'react';
import type { OfficeState } from '@/types/office';
import type { Agent } from '@/types/agent';
import type { Task } from '@/types/task';
import { Room } from '@/components/office/Room';
import { MeetingRoom } from '@/components/office/MeetingRoom';

interface FloorPlanProps {
  officeState: OfficeState;
  agents: Agent[];
  tasks: Task[];
  showLabels: boolean;
  departmentFilter: string | null;
}

export function FloorPlan({
  officeState,
  agents,
  tasks,
  showLabels,
  departmentFilter,
}: FloorPlanProps) {
  // Build a map of agent_id -> current task title
  const taskMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const task of tasks) {
      if (
        task.assigned_agent_id &&
        (task.status === 'in_progress' || task.status === 'assigned')
      ) {
        map.set(task.assigned_agent_id, task.title);
      }
    }
    return map;
  }, [tasks]);

  // Build agent lookup
  const agentMap = useMemo(
    () => new Map(agents.map((a) => [a.id, a])),
    [agents]
  );

  // Filter rooms by department if filter is active
  const visibleRooms = useMemo(() => {
    if (!departmentFilter) return officeState.rooms;
    return officeState.rooms.filter(
      (room) => !room.departmentId || room.departmentId === departmentFilter
    );
  }, [officeState.rooms, departmentFilter]);

  // Determine which rooms have active work
  const activeRoomIds = useMemo(() => {
    const ids = new Set<string>();
    for (const pos of officeState.agents) {
      if (pos.status === 'working') {
        ids.add(pos.roomId);
      }
    }
    return ids;
  }, [officeState.agents]);

  return (
    <>
      {visibleRooms.map((room) => {
        // Meeting rooms get the MeetingRoom component
        if (room.type === 'meeting_room') {
          const meeting = officeState.meetings.find((m) => m.roomId === room.id) || null;
          const meetingAgents = meeting
            ? meeting.participantIds
                .map((id) => agentMap.get(id))
                .filter((a): a is Agent => a !== undefined)
            : [];

          return (
            <MeetingRoom
              key={room.id}
              room={room}
              meeting={meeting}
              agents={meetingAgents}
              showLabels={showLabels}
            />
          );
        }

        // Regular rooms
        const roomPositions = officeState.agents.filter((p) => p.roomId === room.id);
        const roomAgents = roomPositions
          .map((p) => agentMap.get(p.agentId))
          .filter((a): a is Agent => a !== undefined);

        return (
          <Room
            key={room.id}
            room={room}
            agents={roomAgents}
            positions={roomPositions}
            showLabels={showLabels}
            hasActiveWork={activeRoomIds.has(room.id)}
            taskMap={taskMap}
          />
        );
      })}
    </>
  );
}
