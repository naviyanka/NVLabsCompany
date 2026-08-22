import { X, Cpu, Activity, MapPin, Zap } from 'lucide-react';
import type { AgentData } from '../agents/AgentModel';

interface AgentPanelProps {
  agent: AgentData;
  onClose: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  working: '#22C55E',
  idle: '#3B82F6',
  review: '#F97316',
  offline: '#64748B',
  error: '#EF4444',
  paused: '#EAB308',
};

export function AgentPanel({ agent, onClose }: AgentPanelProps) {
  const statusColor = STATUS_COLORS[agent.status] || '#64748B';

  return (
    <div className="absolute top-4 right-4 w-72 bg-[#0B1626] border border-white/10 rounded-xl shadow-2xl z-20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: statusColor, boxShadow: `0 0 8px ${statusColor}` }}
          />
          <span className="text-white font-semibold text-sm">{agent.name}</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">
        {/* Role & Model */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Role</span>
          <span className="text-xs text-white font-medium">{agent.role}</span>
        </div>
        {agent.model && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">Model</span>
            <span className="text-xs text-gray-300">{agent.model}</span>
          </div>
        )}

        {/* Status */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Status</span>
          <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: statusColor }}>
            <Activity size={10} />
            {agent.status.charAt(0).toUpperCase() + agent.status.slice(1)}
          </span>
        </div>

        {/* Room */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Location</span>
          <span className="flex items-center gap-1 text-xs text-gray-300">
            <MapPin size={10} />
            {agent.roomId.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
        </div>

        {/* Current Task */}
        {agent.currentTask && (
          <div className="mt-2 p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center gap-1.5 mb-1">
              <Zap size={10} className="text-green-400" />
              <span className="text-[10px] text-gray-400 uppercase font-medium">Current Task</span>
            </div>
            <p className="text-xs text-gray-200">{agent.currentTask}</p>
          </div>
        )}

        {/* Agent color accent */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Team Color</span>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded" style={{ backgroundColor: agent.color }} />
            <span className="text-xs text-gray-300 font-mono">{agent.color}</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-white/[0.06] bg-white/[0.02]">
        <button className="w-full text-center text-xs text-primary-400 hover:text-primary-300 transition-colors">
          View Full Profile →
        </button>
      </div>
    </div>
  );
}
