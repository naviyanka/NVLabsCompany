import { X, Users, MapPin, Shield } from 'lucide-react';
import type { RoomDefinition } from '../layout/roomDefinitions';

interface RoomPanelProps {
  room: RoomDefinition;
  agentCount: number;
  onClose: () => void;
}

const ACCESS_LABELS: Record<string, { text: string; color: string }> = {
  public: { text: 'Public', color: '#22C55E' },
  team: { text: 'Team Only', color: '#3B82F6' },
  manager: { text: 'Manager Only', color: '#A78BFA' },
  restricted: { text: 'Restricted', color: '#EF4444' },
};

export function RoomPanel({ room, agentCount, onClose }: RoomPanelProps) {
  const access = ACCESS_LABELS[room.access] ?? ACCESS_LABELS.public ?? { text: 'Public', color: '#22C55E' };

  return (
    <div className="absolute top-4 right-4 w-72 bg-[#0B1626] border border-white/10 rounded-xl shadow-2xl z-20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded"
            style={{ backgroundColor: room.color }}
          />
          <span className="text-white font-semibold text-sm">{room.name}</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Type */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Type</span>
          <span className="text-xs text-white font-medium capitalize">{room.type}</span>
        </div>

        {/* Access */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Access</span>
          <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: access.color }}>
            <Shield size={10} />
            {access.text}
          </span>
        </div>

        {/* Agents */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Agents Inside</span>
          <span className="flex items-center gap-1 text-xs text-white">
            <Users size={10} />
            {agentCount}
          </span>
        </div>

        {/* Dimensions */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Size</span>
          <span className="text-xs text-gray-300">{room.width}m × {room.depth}m</span>
        </div>

        {/* Location */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Position</span>
          <span className="flex items-center gap-1 text-xs text-gray-300 font-mono">
            <MapPin size={10} />
            ({room.x}, {room.z})
          </span>
        </div>

        {/* Doors */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Doors</span>
          <span className="text-xs text-gray-300 capitalize">{room.doors.join(', ')}</span>
        </div>
      </div>
    </div>
  );
}
