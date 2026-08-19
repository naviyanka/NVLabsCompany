import { Users, Activity, Coffee, AlertCircle, WifiOff, Cpu, MemoryStick, X, User, ChevronRight } from 'lucide-react';
import { mockAgents3D, managerAgent, status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';

interface OfficeMobileFallbackProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onCloseSidebar: () => void;
  onViewProfile: (agent: MockAgent3D) => void;
}

/**
 * Mobile-friendly fallback for the Office page.
 * Renders a scrollable list of agents with status indicators and stats,
 * since the 3D canvas is not practical on small touch screens.
 */
export function OfficeMobileFallback({ selectedAgent, onAgentClick, onCloseSidebar, onViewProfile }: OfficeMobileFallbackProps) {
  const allAgents = [...mockAgents3D, managerAgent];
  const active = allAgents.filter((a) => a.status === 'working').length;
  const idle = allAgents.filter((a) => a.status === 'idle').length;
  const review = allAgents.filter((a) => a.status === 'review').length;
  const offline = allAgents.filter((a) => a.status === 'offline').length;

  return (
    <div className="min-h-[calc(100vh-2rem)] flex flex-col -m-6 bg-dark-bg">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/[0.08] bg-dark-bg/90 backdrop-blur-sm sticky top-0 z-10">
        <h1 className="text-sm font-semibold text-white mb-2">Office Floor Plan</h1>
        <div className="grid grid-cols-4 gap-2">
          <StatBadge icon={Activity} label="Active" value={active} color={status3DColors.working ?? '#10b981'} />
          <StatBadge icon={Coffee} label="Idle" value={idle} color={status3DColors.idle ?? '#f59e0b'} />
          <StatBadge icon={AlertCircle} label="Review" value={review} color={status3DColors.review ?? '#a855f7'} />
          <StatBadge icon={WifiOff} label="Offline" value={offline} color={status3DColors.offline ?? '#9ca3af'} />
        </div>
      </div>

      {/* Agent list */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
          <Users size={10} />
          <span>{allAgents.length} Agents</span>
        </div>
        {allAgents.map((agent) => (
          <MobileAgentCard
            key={agent.id}
            agent={agent}
            isSelected={selectedAgent?.id === agent.id}
            onClick={() => onAgentClick(agent)}
          />
        ))}
      </div>

      {/* Mobile detail sheet (slides up from bottom when agent selected) */}
      {selectedAgent && (
        <MobileAgentDetail
          agent={selectedAgent}
          onClose={onCloseSidebar}
          onViewProfile={onViewProfile}
        />
      )}
    </div>
  );
}

function StatBadge({ icon: Icon, label, value, color }: { icon: typeof Activity; label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 p-1.5 rounded-lg bg-dark-surface/60 border border-white/[0.05]">
      <Icon size={12} style={{ color }} />
      <span className="text-xs font-semibold" style={{ color }}>{value}</span>
      <span className="text-[8px] text-gray-500">{label}</span>
    </div>
  );
}

function MobileAgentCard({ agent, isSelected, onClick }: { agent: MockAgent3D; isSelected: boolean; onClick: () => void }) {
  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const statusLabel = statusLabels[agent.status] ?? 'Unknown';

  return (
    <button
      onClick={onClick}
      className={`w-full p-3 rounded-lg border transition-all text-left ${
        isSelected
          ? 'bg-dark-card border-indigo-500/50 ring-1 ring-indigo-500/30'
          : 'bg-dark-surface/80 border-white/[0.08] active:bg-dark-card/60'
      }`}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
          style={{
            backgroundColor: `${statusColor}20`,
            color: statusColor,
            border: `2px solid ${statusColor}`,
          }}
        >
          {agent.name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-white truncate">{agent.name}</span>
            <span className="text-[10px] text-gray-500 ml-2 flex-shrink-0">{agent.model}</span>
          </div>
          <div className="flex items-center justify-between mt-0.5">
            <span className="text-[11px] text-gray-400">{agent.role}</span>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor }} />
              <span className="text-[10px]" style={{ color: statusColor }}>{statusLabel}</span>
            </div>
          </div>
          {agent.taskProgress > 0 && (
            <div className="mt-1.5">
              <div className="w-full h-1 bg-dark-bg rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${agent.taskProgress}%`,
                    backgroundColor: statusColor,
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

function MobileAgentDetail({ agent, onClose, onViewProfile }: { agent: MockAgent3D; onClose: () => void; onViewProfile: (agent: MockAgent3D) => void }) {
  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const statusLabel = statusLabels[agent.status] ?? 'Unknown';

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Sheet */}
      <div className="relative bg-dark-surface rounded-t-xl border-t border-white/[0.08] max-h-[80vh] overflow-y-auto">
        {/* Handle */}
        <div className="flex justify-center pt-2 pb-1">
          <div className="w-8 h-1 bg-gray-600 rounded-full" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/[0.08]">
          <div className="flex items-center gap-2">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
              style={{
                backgroundColor: `${statusColor}20`,
                color: statusColor,
                border: `2px solid ${statusColor}`,
              }}
            >
              {agent.name[0]}
            </div>
            <div>
              <div className="text-sm font-semibold text-white">{agent.name}</div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-gray-400">{agent.role}</span>
                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: statusColor }} />
                <span className="text-[10px]" style={{ color: statusColor }}>{statusLabel}</span>
              </div>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/10">
            <X size={16} className="text-gray-400" />
          </button>
        </div>

        {/* Task */}
        <div className="px-4 py-3 border-b border-white/[0.08]">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Current Task</div>
          <div className="text-xs text-gray-300">{agent.currentTask}</div>
          {agent.taskProgress > 0 && (
            <div className="mt-2">
              <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${agent.taskProgress}%`, backgroundColor: statusColor }}
                />
              </div>
              <div className="text-[10px] text-gray-500 mt-0.5 text-right">{agent.taskProgress}%</div>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="px-4 py-3 border-b border-white/[0.08]">
          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center gap-2 p-2 bg-dark-bg/60 rounded-lg">
              <Cpu size={12} className="text-blue-400" />
              <div>
                <div className="text-[10px] text-gray-500">CPU</div>
                <div className="text-xs font-semibold text-white">{agent.cpu}%</div>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 bg-dark-bg/60 rounded-lg">
              <MemoryStick size={12} className="text-purple-400" />
              <div>
                <div className="text-[10px] text-gray-500">Memory</div>
                <div className="text-xs font-semibold text-white">{agent.memory}%</div>
              </div>
            </div>
          </div>
        </div>

        {/* Capabilities */}
        <div className="px-4 py-3 border-b border-white/[0.08]">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Capabilities</div>
          <div className="flex flex-wrap gap-1.5">
            {agent.capabilities.map((cap) => (
              <span
                key={cap}
                className="px-2 py-0.5 rounded-full text-[10px] bg-dark-bg border border-white/[0.08] text-gray-300"
              >
                {cap}
              </span>
            ))}
          </div>
        </div>

        {/* View Profile action */}
        <div className="px-4 py-3">
          <button
            onClick={() => onViewProfile(agent)}
            className="w-full flex items-center justify-between px-3 py-2.5 text-xs text-gray-300 bg-dark-bg/60 rounded-lg active:bg-white/5 border border-white/[0.05]"
          >
            <span className="flex items-center gap-2">
              <User size={12} className="text-indigo-400" />
              View Full Profile
            </span>
            <ChevronRight size={12} className="text-gray-500" />
          </button>
        </div>
      </div>
    </div>
  );
}
