import { Cpu, MemoryStick } from 'lucide-react';
import { mockAgents3D, managerAgent, status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';

interface AgentsAtGlanceProps {
  onAgentClick: (agent: MockAgent3D) => void;
  selectedAgentId: string | null;
}

/**
 * Bottom section showing agent summary cards with sparklines and stats.
 */
export function AgentsAtGlance({ onAgentClick, selectedAgentId }: AgentsAtGlanceProps) {
  const allAgents = [...mockAgents3D, managerAgent];

  return (
    <div className="absolute bottom-0 left-0 right-0 z-10">
      <div className="bg-dark-bg/90 backdrop-blur-sm border-t border-white/[0.08] px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-300">Agents at a Glance</span>
          <span className="text-[10px] text-gray-500">{allAgents.length} agents total</span>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin scrollbar-track-dark-bg scrollbar-thumb-dark-surface">
          {allAgents.map((agent) => (
            <AgentGlanceCard
              key={agent.id}
              agent={agent}
              isSelected={selectedAgentId === agent.id}
              onClick={() => onAgentClick(agent)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface AgentGlanceCardProps {
  agent: MockAgent3D;
  isSelected: boolean;
  onClick: () => void;
}

function AgentGlanceCard({ agent, isSelected, onClick }: AgentGlanceCardProps) {
  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const statusLabel = statusLabels[agent.status] ?? 'Unknown';

  return (
    <button
      onClick={onClick}
      className={`flex-shrink-0 w-44 p-2.5 rounded-lg border transition-all duration-200 text-left ${
        isSelected
          ? 'bg-dark-card border-indigo-500/50 ring-1 ring-indigo-500/30'
          : 'bg-dark-surface/80 border-white/[0.08] hover:border-white/[0.15] hover:bg-dark-card/60'
      }`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-1.5">
        <div
          className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold"
          style={{
            backgroundColor: `${statusColor}20`,
            color: statusColor,
            border: `1.5px solid ${statusColor}`,
          }}
        >
          {agent.name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-white truncate">{agent.name}</div>
          <div className="text-[9px] text-gray-500 truncate">{agent.role}</div>
        </div>
      </div>

      {/* Status & Model */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1">
          <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor }} />
          <span className="text-[9px]" style={{ color: statusColor }}>{statusLabel}</span>
        </div>
        <span className="text-[9px] text-gray-600">{agent.model}</span>
      </div>

      {/* Mini sparkline */}
      <div className="flex items-end gap-px h-4 mb-1.5">
        {agent.sparklineData.map((value, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm"
            style={{
              height: `${(value / 100) * 100}%`,
              backgroundColor: `${statusColor}60`,
              minHeight: 1,
            }}
          />
        ))}
      </div>

      {/* CPU / MEM */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <Cpu size={8} className="text-blue-400" />
          <span className="text-[9px] text-gray-400">{agent.cpu}%</span>
        </div>
        <div className="flex items-center gap-1">
          <MemoryStick size={8} className="text-purple-400" />
          <span className="text-[9px] text-gray-400">{agent.memory}%</span>
        </div>
      </div>
    </button>
  );
}
