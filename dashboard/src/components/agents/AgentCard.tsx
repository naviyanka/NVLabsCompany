import type { Agent } from '@/types/agent';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { Cpu, Activity, MessageSquare, Trash2 } from 'lucide-react';

export interface AgentCardProps {
  agent: Agent;
  onClick?: (agent: Agent) => void;
  onChat?: (agent: Agent) => void;
  onFire?: (agent: Agent) => void;
}

export function AgentCard({ agent, onClick, onChat, onFire }: AgentCardProps) {
  const badgeVariant =
    agent.status === 'active'
      ? 'active'
      : agent.status === 'busy'
      ? 'in_progress'
      : agent.status === 'error'
      ? 'failed'
      : 'idle';

  return (
    <Card
      className="hover:border-white/[0.2] transition-all cursor-pointer group"
      onClick={onClick ? () => onClick(agent) : undefined}
      padding="sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-[6px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-mono font-bold text-xs text-[#FFB020] shrink-0">
            {agent.name.substring(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-display font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors truncate">
              {agent.name}
            </h3>
            <p className="text-xs font-mono text-[#6B6B6E] truncate">{agent.title}</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {onChat && (
            <button
              onClick={(e) => { e.stopPropagation(); onChat(agent); }}
              className="p-1.5 rounded-[4px] text-[#6B6B6E] hover:text-[#FFB020] hover:bg-[#FFB020]/10 transition-all cursor-pointer opacity-0 group-hover:opacity-100"
              title={`Chat with ${agent.name}`}
            >
              <MessageSquare size={14} />
            </button>
          )}
          {onFire && (
            <button
              onClick={(e) => { e.stopPropagation(); if (confirm(`Fire ${agent.name}? This will permanently remove this agent.`)) onFire(agent); }}
              className="p-1.5 rounded-[4px] text-[#6B6B6E] hover:text-red-400 hover:bg-red-400/10 transition-all cursor-pointer opacity-0 group-hover:opacity-100"
              title={`Fire ${agent.name}`}
            >
              <Trash2 size={14} />
            </button>
          )}
          <Badge variant={badgeVariant as any}>{agent.status}</Badge>
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-white/[0.06] grid grid-cols-2 gap-2 text-[11px] font-mono text-[#6B6B6E]">
        <div className="flex items-center gap-1.5 truncate">
          <Cpu className="w-3.5 h-3.5 text-[#9C9C9F] shrink-0" />
          <span className="truncate text-[#A8A8AB]">{agent.model}</span>
        </div>
        <div className="flex items-center justify-end gap-1 text-[#22C55E]">
          <Activity className="w-3.5 h-3.5 shrink-0" />
          <span>Score {agent.performance_score ?? 94}%</span>
        </div>
      </div>

      {agent.responsibilities && (
        <p className="text-xs text-[#9C9C9F] mt-2.5 line-clamp-2 leading-relaxed font-sans">
          {agent.responsibilities}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between text-[10px] font-mono text-[#6B6B6E]">
        <span>Spend MTD</span>
        <span className="text-[#F2F1EE] font-medium">
          ${((agent.spent_monthly_cents ?? 0) / 100).toFixed(2)}
        </span>
      </div>
    </Card>
  );
}
