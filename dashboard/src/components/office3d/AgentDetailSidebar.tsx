import { useNavigate } from 'react-router-dom';
import { X, Cpu, MemoryStick, ChevronRight, User, ClipboardList, ScrollText } from 'lucide-react';
import { status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';

interface AgentDetailSidebarProps {
  agent: MockAgent3D;
  onClose: () => void;
  onViewProfile?: (agent: MockAgent3D) => void;
  onShowToast?: (message: string) => void;
}

/**
 * Right sidebar that shows detailed agent information when an agent is clicked.
 * Quick action buttons are wired up to navigation callbacks.
 */
export function AgentDetailSidebar({ agent, onClose, onViewProfile, onShowToast }: AgentDetailSidebarProps) {
  const navigate = useNavigate();
  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const statusLabel = statusLabels[agent.status] ?? 'Unknown';

  const quickActions = [
    {
      label: 'View Full Profile',
      icon: User,
      action: () => {
        if (onViewProfile) {
          onViewProfile(agent);
        } else {
          navigate(`/agents/${agent.id}`);
        }
      },
    },
    {
      label: 'Assign New Task',
      icon: ClipboardList,
      action: () => {
        navigate('/tasks');
        onShowToast?.(`Assigning new task to ${agent.name}...`);
      },
    },
    {
      label: 'View Activity Logs',
      icon: ScrollText,
      action: () => {
        navigate('/activity');
        onShowToast?.(`Viewing telemetry logs for ${agent.name}...`);
      },
    },
  ];

  return (
    <div className="absolute top-14 right-0 bottom-0 w-80 z-20 bg-dark-surface/95 backdrop-blur-sm border-l border-white/[0.08] flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.08]">
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
            <div className="text-[10px] text-gray-400">{agent.role}</div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-white/10 transition-colors"
        >
          <X size={16} className="text-gray-400" />
        </button>
      </div>

      {/* Status */}
      <div className="px-4 py-3 border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor }} />
          <span className="text-xs font-medium" style={{ color: statusColor }}>
            {statusLabel}
          </span>
          <span className="text-xs text-gray-500 ml-auto">{agent.model}</span>
        </div>
      </div>

      {/* Current Task */}
      <div className="px-4 py-3 border-b border-white/[0.08]">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Current Task</div>
        <div className="text-xs text-gray-300 mb-2">{agent.currentTask}</div>
        {agent.taskProgress > 0 && (
          <div className="relative">
            <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${agent.taskProgress}%`,
                  backgroundColor: statusColor,
                }}
              />
            </div>
            <div className="text-[10px] text-gray-500 mt-1 text-right">
              {agent.taskProgress}%
            </div>
          </div>
        )}
      </div>

      {/* Performance */}
      <div className="px-4 py-3 border-b border-white/[0.08]">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Performance</div>
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

      {/* Sparkline - simple bars */}
      <div className="px-4 py-3 border-b border-white/[0.08]">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Activity (8h)</div>
        <div className="flex items-end gap-0.5 h-8">
          {agent.sparklineData.map((value, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm"
              style={{
                height: `${(value / 100) * 100}%`,
                backgroundColor: `${statusColor}80`,
                minHeight: 2,
              }}
            />
          ))}
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

      {/* Quick Actions */}
      <div className="px-4 py-3 mt-auto">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Quick Actions</div>
        <div className="space-y-1.5">
          {quickActions.map(({ label, icon: Icon, action }) => (
            <button
              key={label}
              onClick={action}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-300 bg-dark-bg/60 rounded-lg hover:bg-white/5 transition-colors border border-white/[0.05]"
            >
              <span className="flex items-center gap-2">
                <Icon size={10} className="text-indigo-400" />
                {label}
              </span>
              <ChevronRight size={10} className="text-gray-500" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
