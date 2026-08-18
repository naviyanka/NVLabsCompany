import { useState } from 'react';
import type { Agent } from '@/types/agent';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { StatusIndicator } from '@/components/common/StatusIndicator';
import { Spinner } from '@/components/common/Spinner';
import { PerformanceChart } from '@/components/charts/PerformanceChart';
import { Bot, Briefcase, Brain, Settings, BarChart3 } from 'lucide-react';

export interface AgentDetailProps {
  agent: Agent | null;
  loading: boolean;
  error: string | null;
}

type TabId = 'overview' | 'tasks' | 'memory' | 'performance' | 'configuration';

interface TabDef {
  id: TabId;
  label: string;
  icon: React.ReactNode;
}

const tabs: TabDef[] = [
  { id: 'overview', label: 'Overview', icon: <Bot size={16} /> },
  { id: 'tasks', label: 'Tasks', icon: <Briefcase size={16} /> },
  { id: 'memory', label: 'Memory', icon: <Brain size={16} /> },
  { id: 'performance', label: 'Performance', icon: <BarChart3 size={16} /> },
  { id: 'configuration', label: 'Configuration', icon: <Settings size={16} /> },
];

function agentStatusToIndicator(status: Agent['status']): 'online' | 'offline' | 'busy' | 'idle' | 'error' {
  switch (status) {
    case 'active': return 'online';
    case 'idle': return 'idle';
    case 'busy': return 'busy';
    case 'offline': return 'offline';
    case 'error': return 'error';
    default: return 'offline';
  }
}

export function AgentDetail({ agent, loading, error }: AgentDetailProps) {
  const [activeTab, setActiveTab] = useState<TabId>('overview');

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load agent</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="text-center py-12 text-gray-500">
        Agent not found
      </div>
    );
  }

  const initials = agent.name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  return (
    <div>
      {/* Header */}
      <Card className="mb-6">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-primary-100 text-primary-700 rounded-xl flex items-center justify-center text-lg font-bold">
            {initials}
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-gray-900">{agent.name}</h1>
              <StatusIndicator status={agentStatusToIndicator(agent.status)} size="md" />
            </div>
            <p className="text-sm text-gray-500">{agent.title}</p>
            <div className="flex items-center gap-2 mt-2">
              <Badge variant="primary">{agent.role}</Badge>
              <Badge variant="info">{agent.adapter_type}</Badge>
              <Badge variant="default">{agent.model}</Badge>
            </div>
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 pb-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Responsibilities</h3>
            <p className="text-sm text-gray-600">{agent.responsibilities || 'No responsibilities defined'}</p>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Objectives</h3>
            <p className="text-sm text-gray-600">{agent.objectives || 'No objectives defined'}</p>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Capabilities</h3>
            <div className="flex flex-wrap gap-2">
              {agent.capabilities.length > 0 ? (
                agent.capabilities.map((cap) => (
                  <Badge key={cap} variant="default" size="sm">{cap}</Badge>
                ))
              ) : (
                <p className="text-sm text-gray-500">No capabilities listed</p>
              )}
            </div>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Soul Description</h3>
            <p className="text-sm text-gray-600">{agent.soul_description || 'No soul description'}</p>
          </Card>
        </div>
      )}

      {activeTab === 'tasks' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Assigned Tasks</h3>
          <p className="text-sm text-gray-500">Task history for this agent will appear here.</p>
        </Card>
      )}

      {activeTab === 'memory' && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Agent Memory</h3>
          <p className="text-sm text-gray-500">Memory entries for this agent will appear here.</p>
        </Card>
      )}

      {activeTab === 'performance' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Budget Used</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">
                ${(agent.spent_monthly_cents / 100).toFixed(2)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                of ${(agent.budget_monthly_cents / 100).toFixed(2)} monthly
              </p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Status</p>
              <p className="text-2xl font-bold text-gray-900 mt-1 capitalize">{agent.status}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Model</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{agent.model}</p>
            </Card>
          </div>
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Performance Trend</h3>
            <PerformanceChart
              data={[
                { name: 'Week 1', completionRate: 72 },
                { name: 'Week 2', completionRate: 85 },
                { name: 'Week 3', completionRate: 78 },
                { name: 'Week 4', completionRate: 91 },
              ]}
            />
          </Card>
        </div>
      )}

      {activeTab === 'configuration' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Adapter Configuration</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Adapter Type</dt>
                <dd className="text-gray-900 font-medium">{agent.adapter_type}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Model</dt>
                <dd className="text-gray-900 font-medium">{agent.model}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Monthly Budget</dt>
                <dd className="text-gray-900 font-medium">${(agent.budget_monthly_cents / 100).toFixed(2)}</dd>
              </div>
            </dl>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Identifiers</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Agent ID</dt>
                <dd className="text-gray-900 font-mono text-xs">{agent.id}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Company ID</dt>
                <dd className="text-gray-900 font-mono text-xs">{agent.company_id}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Department ID</dt>
                <dd className="text-gray-900 font-mono text-xs">{agent.department_id || 'None'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Manager ID</dt>
                <dd className="text-gray-900 font-mono text-xs">{agent.manager_id || 'None'}</dd>
              </div>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
