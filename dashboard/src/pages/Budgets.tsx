import { useMemo } from 'react';
import { BudgetMeter } from '@/components/governance/BudgetMeter';
import { CostChart, type CostDataPoint } from '@/components/charts/CostChart';
import { Card } from '@/components/common/Card';
import { Spinner } from '@/components/common/Spinner';
import { Table, type Column } from '@/components/common/Table';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import type { Agent } from '@/types/agent';
import type { PaginatedResponse } from '@/types/common';
import { formatCents } from '@/utils/time';
import { COMPANY_ID } from '@/config';

export function Budgets() {
  const { data, loading, error } = useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const agents = data?.items ?? [];
  const totalBudget = agents.reduce((sum, a) => sum + a.budget_monthly_cents, 0);
  const totalSpent = agents.reduce((sum, a) => sum + a.spent_monthly_cents, 0);

  // Generate cost data (memoized to avoid re-randomizing on every render)
  const costData: CostDataPoint[] = useMemo(() => Array.from({ length: 7 }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (6 - i));
    return {
      date: date.toLocaleDateString('en-US', { weekday: 'short' }),
      cost: Math.round(totalSpent / 7 * (0.8 + Math.random() * 0.4)),
    };
  }), [totalSpent]);

  // Agent cost table columns
  const agentColumns: Column<Agent>[] = [
    {
      key: 'name',
      header: 'Agent',
      render: (agent) => (
        <div>
          <p className="text-sm font-medium text-gray-900">{agent.name}</p>
          <p className="text-xs text-gray-500">{agent.role}</p>
        </div>
      ),
    },
    {
      key: 'model',
      header: 'Model',
      render: (agent) => <span className="text-sm text-gray-600">{agent.model}</span>,
    },
    {
      key: 'budget',
      header: 'Budget',
      render: (agent) => <span className="text-sm text-gray-600">{formatCents(agent.budget_monthly_cents)}</span>,
    },
    {
      key: 'spent',
      header: 'Spent',
      render: (agent) => <span className="text-sm font-medium text-gray-900">{formatCents(agent.spent_monthly_cents)}</span>,
    },
    {
      key: 'usage',
      header: 'Usage',
      render: (agent) => {
        const percent = agent.budget_monthly_cents > 0
          ? ((agent.spent_monthly_cents / agent.budget_monthly_cents) * 100).toFixed(0)
          : '0';
        return <span className="text-sm text-gray-600">{percent}%</span>;
      },
    },
  ];

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load budget data</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Budgets</h1>
        <p className="text-sm text-gray-500 mt-1">Monitor spending across the organization</p>
      </div>

      <Card>
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Total Budget Usage</h3>
        <BudgetMeter usedCents={totalSpent} totalCents={totalBudget} />
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Cost Trend (Last 7 Days)</h3>
        <CostChart data={costData} />
      </Card>

      <Card padding="none">
        <div className="px-4 py-3 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-900">Per-Agent Cost Breakdown</h3>
        </div>
        <Table
          columns={agentColumns}
          data={[...agents].sort((a, b) => b.spent_monthly_cents - a.spent_monthly_cents)}
          keyExtractor={(agent) => agent.id}
        />
      </Card>
    </div>
  );
}
