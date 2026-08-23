import { useNavigate } from 'react-router-dom';
import { X, User, ClipboardList, MessageSquare, Cpu, MemoryStick, ChevronRight } from 'lucide-react';
import { status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';
import { Button } from '@/components/common/Button';

interface AgentDetailSidebarProps {
  agent: MockAgent3D;
  onClose: () => void;
  onViewProfile?: (agent: MockAgent3D) => void;
}

export function AgentDetailSidebar({ agent, onClose, onViewProfile }: AgentDetailSidebarProps) {
  const navigate = useNavigate();
  const statusColor = status3DColors[agent.status] ?? '#9ca3af';
  const statusLabel = statusLabels[agent.status] ?? 'Unknown';

  const handleOpenTasks = () => {
    navigate('/tasks');
  };

  const handleOpenChat = () => {
    navigate(`/agents/${agent.id}`);
  };

  return (
    <div className="absolute top-10 right-0 bottom-0 w-80 z-20 bg-[#141416] border-l border-white/[0.08] flex flex-col overflow-hidden shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.08] bg-[#101012]">
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-[4px] flex items-center justify-center text-xs font-bold font-mono"
            style={{
              backgroundColor: `${statusColor}20`,
              color: statusColor,
              border: `1px solid ${statusColor}`,
            }}
          >
            {agent.name.substring(0, 2)}
          </div>
          <div>
            <div className="text-sm font-display font-medium text-[#F2F1EE]">{agent.name}</div>
            <div className="text-[10px] font-mono text-[#6B6B6E]">{agent.role}</div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-[4px] text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] transition-colors cursor-pointer"
          aria-label="Close sidebar"
        >
          <X size={16} />
        </button>
      </div>

      {/* Status */}
      <div className="px-4 py-3 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor }} />
          <span className="text-xs font-mono font-medium" style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </div>
        <span className="text-xs font-mono text-[#6B6B6E]">{agent.model}</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Current Task */}
        <div>
          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider mb-1.5">
            Active Assignment
          </div>
          <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE] font-sans">
            {agent.currentTask ?? 'No active task assigned.'}
          </div>
        </div>

        {/* Telemetry Stats */}
        <div className="grid grid-cols-2 gap-2">
          <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] mb-1">
              <Cpu size={12} />
              Model Provider
            </div>
            <div className="text-xs font-mono font-medium text-[#F2F1EE] truncate">{agent.model}</div>
          </div>
          <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] mb-1">
              <MemoryStick size={12} />
              Tokens Processed
            </div>
            <div className="text-xs font-mono font-medium text-[#FFB020]">
              {(agent.tokensUsed ?? 0).toLocaleString()}
            </div>
          </div>
        </div>

        {/* Quick actions */}
        <div>
          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider mb-2">
            Operations & Actions
          </div>
          <div className="space-y-1.5">
            <button
              onClick={() => onViewProfile?.(agent)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-[#F2F1EE] bg-[#101012] hover:bg-white/[0.04] border border-white/[0.06] rounded-[6px] transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <User size={14} className="text-[#FFB020]" />
                <span>View Full Agent Dossier</span>
              </div>
              <ChevronRight size={14} className="text-[#6B6B6E]" />
            </button>

            <button
              onClick={handleOpenChat}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-[#F2F1EE] bg-[#101012] hover:bg-white/[0.04] border border-white/[0.06] rounded-[6px] transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <MessageSquare size={14} className="text-[#38BDF8]" />
                <span>Live Chat & Commands</span>
              </div>
              <ChevronRight size={14} className="text-[#6B6B6E]" />
            </button>

            <button
              onClick={handleOpenTasks}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-[#F2F1EE] bg-[#101012] hover:bg-white/[0.04] border border-white/[0.06] rounded-[6px] transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <ClipboardList size={14} className="text-[#22C55E]" />
                <span>Assign New Task</span>
              </div>
              <ChevronRight size={14} className="text-[#6B6B6E]" />
            </button>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-white/[0.08] bg-[#101012]">
        <Button
          variant="primary"
          size="sm"
          className="w-full"
          onClick={() => onViewProfile?.(agent)}
        >
          Open Dossier
        </Button>
      </div>
    </div>
  );
}
