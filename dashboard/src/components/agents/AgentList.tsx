import { useState } from 'react';
import type { Agent } from '@/types/agent';
import type { AgentStatus } from '@/types/common';
import { AgentCard } from './AgentCard';
import { Table } from '@/components/common/Table';
import { Badge } from '@/components/common/Badge';
import { Skeleton } from '@/components/common/Skeleton';
import { EmptyState } from '@/components/common/EmptyState';
import { Grid3X3, List, Search, Users } from 'lucide-react';

export interface AgentListProps {
  agents: Agent[];
  loading: boolean;
  error: string | null;
  onAgentClick?: (agent: Agent) => void;
  onAgentChat?: (agent: Agent) => void;
  onAgentFire?: (agent: Agent) => void;
  onHireAgent?: () => void;
}

type ViewMode = 'grid' | 'list';

export function AgentList({ agents, loading, error, onAgentClick, onAgentChat, onAgentFire, onHireAgent }: AgentListProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [statusFilter, setStatusFilter] = useState<AgentStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  if (loading) {
    return <Skeleton variant="table" count={6} />;
  }

  if (error && agents.length === 0) {
    return (
      <div className="p-8 text-center bg-[#141416] border border-[#EF4444]/30 rounded-[10px] text-[#EF4444] font-mono text-xs">
        <p className="font-medium">Workforce telemetry failed to load</p>
        <p className="text-[#9C9C9F] mt-1">{error}</p>
      </div>
    );
  }

  const filteredAgents = agents.filter((agent) => {
    if (statusFilter !== 'all' && agent.status !== statusFilter) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        agent.name.toLowerCase().includes(q) ||
        agent.title.toLowerCase().includes(q) ||
        agent.role.toLowerCase().includes(q) ||
        agent.model.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="space-y-4">
      {/* Filters & View Switcher Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        <div className="flex items-center gap-2.5 flex-1 min-w-0">
          <div className="relative flex-1 max-w-sm">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter by name, model, role..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as AgentStatus | 'all')}
            className="px-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs font-mono text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="idle">Idle</option>
            <option value="busy">Working</option>
            <option value="offline">Offline</option>
          </select>
        </div>

        {/* View mode toggle */}
        <div className="flex items-center gap-1 bg-[#141416] border border-white/[0.08] p-0.5 rounded-[6px] shrink-0 self-end sm:self-auto">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-1.5 rounded-[4px] transition-colors cursor-pointer ${
              viewMode === 'grid' ? 'bg-white/[0.08] text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
            aria-label="Grid view"
          >
            <Grid3X3 size={15} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded-[4px] transition-colors cursor-pointer ${
              viewMode === 'list' ? 'bg-white/[0.08] text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
            aria-label="List view"
          >
            <List size={15} />
          </button>
        </div>
      </div>

      {/* Render Grid or Table */}
      {filteredAgents.length === 0 ? (
        <EmptyState
          title="No agents matched criteria."
          description="Adjust your search filters or deploy a new specialist to the workforce."
          actionLabel="Hire Agent"
          onAction={onHireAgent}
          icon={<Users size={20} />}
        />
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} onClick={onAgentClick} onChat={onAgentChat} onFire={onAgentFire} />
          ))}
        </div>
      ) : (
        <Table
          data={filteredAgents}
          keyExtractor={(a) => a.id}
          onRowClick={onAgentClick}
          columns={[
            {
              key: 'name',
              header: 'Agent Call Sign',
              sortable: true,
              render: (a) => (
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-[4px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-mono font-bold text-xs text-[#FFB020]">
                    {a.name.substring(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-medium text-[#F2F1EE]">{a.name}</div>
                    <div className="text-[11px] font-mono text-[#6B6B6E]">{a.title}</div>
                  </div>
                </div>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              sortable: true,
              render: (a) => <Badge variant={a.status as any}>{a.status}</Badge>,
            },
            {
              key: 'role',
              header: 'Role',
              render: (a) => (
                <span className="font-mono text-xs uppercase text-[#A8A8AB]">{a.role}</span>
              ),
            },
            {
              key: 'model',
              header: 'LLM Engine',
              render: (a) => <span className="font-mono text-xs text-[#6B6B6E]">{a.model}</span>,
            },
            {
              key: 'performance_score',
              header: 'Score',
              sortable: true,
              render: (a) => (
                <span className="font-mono text-xs text-[#22C55E]">
                  {a.performance_score ?? 94}%
                </span>
              ),
            },
            {
              key: 'spent_monthly_cents',
              header: 'MTD Spend',
              align: 'right',
              render: (a) => (
                <span className="font-mono text-xs text-[#F2F1EE]">
                  ${((a.spent_monthly_cents ?? 0) / 100).toFixed(2)}
                </span>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
