import { useState } from 'react';
import type { Agent } from '@/types/agent';
import type { AgentStatus } from '@/types/common';
import { AgentCard } from './AgentCard';
import { Spinner } from '@/components/common/Spinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Grid3X3, List, Bot } from 'lucide-react';

export interface AgentListProps {
  agents: Agent[];
  loading: boolean;
  error: string | null;
  onAgentClick?: (agent: Agent) => void;
}

type ViewMode = 'grid' | 'list';

export function AgentList({ agents, loading, error, onAgentClick }: AgentListProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [statusFilter, setStatusFilter] = useState<AgentStatus | 'all'>('all');
  const [adapterFilter, setAdapterFilter] = useState<string>('all');

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load agents</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  const adapters = Array.from(new Set(agents.map((a) => a.adapter_type)));

  const filteredAgents = agents.filter((agent) => {
    if (statusFilter !== 'all' && agent.status !== statusFilter) return false;
    if (adapterFilter !== 'all' && agent.adapter_type !== adapterFilter) return false;
    return true;
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as AgentStatus | 'all')}
            className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="idle">Idle</option>
            <option value="busy">Busy</option>
            <option value="offline">Offline</option>
            <option value="error">Error</option>
          </select>
          <select
            value={adapterFilter}
            onChange={(e) => setAdapterFilter(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            <option value="all">All Adapters</option>
            {adapters.map((adapter) => (
              <option key={adapter} value={adapter}>{adapter}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-1.5 rounded ${viewMode === 'grid' ? 'bg-white shadow-sm' : 'text-gray-500'}`}
            aria-label="Grid view"
          >
            <Grid3X3 size={16} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded ${viewMode === 'list' ? 'bg-white shadow-sm' : 'text-gray-500'}`}
            aria-label="List view"
          >
            <List size={16} />
          </button>
        </div>
      </div>

      {filteredAgents.length === 0 ? (
        <EmptyState
          icon={<Bot size={48} />}
          title="No agents found"
          description="No agents match the current filters."
        />
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} onClick={onAgentClick} />
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} onClick={onAgentClick} />
          ))}
        </div>
      )}
    </div>
  );
}
