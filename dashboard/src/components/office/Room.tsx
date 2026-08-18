import type { OfficeRoom, AgentPosition } from '@/types/office';
import type { Agent } from '@/types/agent';
import { AgentAvatar } from '@/components/office/AgentAvatar';

interface RoomProps {
  room: OfficeRoom;
  agents: Agent[];
  positions: AgentPosition[];
  showLabels: boolean;
  hasActiveWork: boolean;
  taskMap: Map<string, string>;
}

export function Room({ room, agents, positions, showLabels, hasActiveWork, taskMap }: RoomProps) {
  const agentCount = positions.length;

  return (
    <div
      className={`absolute rounded-lg border-2 transition-all duration-300 ${hasActiveWork ? 'shadow-md' : 'shadow-sm'}`}
      style={{
        left: `${room.x}px`,
        top: `${room.y}px`,
        width: `${room.width}px`,
        height: `${room.height}px`,
        backgroundColor: room.color,
        borderColor: room.borderColor,
        borderWidth: hasActiveWork ? '3px' : '2px',
      }}
    >
      {/* Room header */}
      <div className="flex items-center justify-between px-2 pt-1.5">
        <span
          className="text-[10px] font-semibold truncate"
          style={{ color: room.borderColor }}
        >
          {room.name}
        </span>
        {agentCount > 0 && (
          <span
            className="text-[9px] px-1.5 py-0.5 rounded-full text-white font-medium"
            style={{ backgroundColor: room.borderColor }}
          >
            {agentCount}
          </span>
        )}
      </div>

      {/* Agents inside room */}
      {agents.map((agent) => {
        const pos = positions.find((p) => p.agentId === agent.id);
        if (!pos) return null;

        // Calculate relative position within the room
        const relX = pos.x - room.x;
        const relY = pos.y - room.y;

        return (
          <AgentAvatar
            key={agent.id}
            agent={agent}
            x={relX}
            y={relY}
            status={pos.status}
            currentTask={taskMap.get(agent.id)}
            showLabel={showLabels}
          />
        );
      })}
    </div>
  );
}
