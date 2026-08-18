import type { OfficeRoom, ActiveMeeting } from '@/types/office';
import type { Agent } from '@/types/agent';
import { AgentAvatar } from '@/components/office/AgentAvatar';

interface MeetingRoomProps {
  room: OfficeRoom;
  meeting: ActiveMeeting | null;
  agents: Agent[];
  showLabels: boolean;
}

export function MeetingRoom({ room, meeting, agents, showLabels }: MeetingRoomProps) {
  const isActive = meeting !== null;
  const participants = meeting
    ? agents.filter((a) => meeting.participantIds.includes(a.id))
    : [];

  // Arrange participants in a circular layout within the room
  const centerX = room.width / 2;
  const centerY = room.height / 2 + 10;
  const radius = Math.min(room.width, room.height) * 0.28;

  return (
    <div
      className={`absolute rounded-lg border-2 transition-all duration-300 ${isActive ? 'animate-office-meeting-pulse shadow-lg' : 'shadow-sm'}`}
      style={{
        left: `${room.x}px`,
        top: `${room.y}px`,
        width: `${room.width}px`,
        height: `${room.height}px`,
        backgroundColor: room.color,
        borderColor: room.borderColor,
        borderWidth: isActive ? '3px' : '2px',
      }}
    >
      {/* Room header */}
      <div className="flex items-center justify-between px-2 pt-1.5">
        <span
          className="text-[10px] font-semibold truncate"
          style={{ color: room.borderColor }}
        >
          {meeting ? meeting.title : room.name}
        </span>
        {isActive && (
          <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-rose-500 text-white font-medium">
            LIVE
          </span>
        )}
      </div>

      {/* Meeting table visualization */}
      {isActive && (
        <div
          className="absolute rounded-full border-2 border-dashed opacity-30"
          style={{
            left: `${centerX - radius}px`,
            top: `${centerY - radius}px`,
            width: `${radius * 2}px`,
            height: `${radius * 2}px`,
            borderColor: room.borderColor,
          }}
        />
      )}

      {/* Participants in circular arrangement */}
      {participants.map((agent, index) => {
        const angle = (2 * Math.PI * index) / participants.length - Math.PI / 2;
        const x = centerX + radius * Math.cos(angle);
        const y = centerY + radius * Math.sin(angle);

        return (
          <AgentAvatar
            key={agent.id}
            agent={agent}
            x={x}
            y={y}
            status="meeting"
            showLabel={showLabels}
          />
        );
      })}

      {/* Empty state */}
      {!isActive && (
        <div className="flex items-center justify-center h-full -mt-4">
          <span className="text-xs text-gray-400">No active meeting</span>
        </div>
      )}
    </div>
  );
}
