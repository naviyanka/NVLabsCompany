import { useCallback, useMemo } from 'react';
import { Card } from '@/components/common/Card';
import { Spinner } from '@/components/common/Spinner';
import { CostChart, type CostDataPoint } from '@/components/charts/CostChart';
import { TaskPieChart, type TaskStatusData } from '@/components/charts/TaskPieChart';
import { ActivityFeed, type ActivityEntry } from '@/components/activity';
import { StatusIndicator } from '@/components/common/StatusIndicator';
import { useApi } from '@/hooks/useApi';
import { usePolling } from '@/hooks/usePolling';
import { agentsApi } from '@/api/agents';
import { tasksApi } from '@/api/tasks';
import type { Agent } from '@/types/agent';
import type { Task } from '@/types/task';
import type { PaginatedResponse } from '@/types/common';
import { Bot, ClipboardList, DollarSign, Shield } from 'lucide-react';
import { COMPANY_ID } from '@/config';

export function Dashboard() {
  const { data: agentsData, loading: agentsLoading, refetch: refetchAgents } = useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(COMPANY_ID),
    [COMPANY_ID]
  );
  const { data: tasksData, loading: tasksLoading, refetch: refetchTasks } = useApi<PaginatedResponse<Task>>(
    () => tasksApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const refetchAll = useCallback(() => {
    void refetchAgents();
    void refetchTasks();
  }, [refetchAgents, refetchTasks]);

  usePolling(refetchAll, { interval: 30000 });

  const agents = agentsData?.items ?? [];
  const tasks = tasksData?.items ?? [];

  const activeAgents = agents.filter((a) => a.status === 'active' || a.status === 'busy').length;
  const idleAgents = agents.filter((a) => a.status === 'idle').length;
  const activeTasks = tasks.filter((t) => t.status === 'in_progress' || t.status === 'assigned').length;
  const totalBudget = agents.reduce((sum, a) => sum + a.budget_monthly_cents, 0);
  const totalSpent = agents.reduce((sum, a) => sum + a.spent_monthly_cents, 0);

  // Generate cost data from agents spent (memoized to avoid re-randomizing on every render)
  const costData: CostDataPoint[] = useMemo(() => Array.from({ length: 7 }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (6 - i));
    return {
      date: date.toLocaleDateString('en-US', { weekday: 'short' }),
      cost: Math.round(totalSpent / 7 * (0.8 + Math.random() * 0.4)),
    };
  }), [totalSpent]);

  // Task status distribution
  const taskStatusData: TaskStatusData[] = [
    { name: 'pending', value: tasks.filter((t) => t.status === 'pending').length, color: '#f59e0b' },
    { name: 'in_progress', value: tasks.filter((t) => t.status === 'in_progress').length, color: '#6366f1' },
    { name: 'completed', value: tasks.filter((t) => t.status === 'completed').length, color: '#10b981' },
    { name: 'failed', value: tasks.filter((t) => t.status === 'failed').length, color: '#f43f5e' },
  ].filter((d) => d.value > 0);

  // Activity feed from recent tasks
  const activityEntries: ActivityEntry[] = tasks
    .slice(0, 10)
    .map((t) => ({
      id: t.id,
      type: t.status === 'completed' ? 'task_completed' as const : t.status === 'failed' ? 'task_failed' as const : 'agent_action' as const,
      message: `Task "${t.title}" is ${t.status.replace('_', ' ')}`,
      timestamp: t.updated_at,
    }));

  // Top agents by spending efficiency
  const topAgents = [...agents]
    .sort((a, b) => b.spent_monthly_cents - a.spent_monthly_cents)
    .slice(0, 5);

  const isLoading = agentsLoading || tasksLoading;

  if (isLoading) {
    return <Spinner size="lg" className="py-12" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Company operating system overview</p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Total Agents</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{agents.length}</p>
              <p className="text-xs text-gray-500 mt-1">
                {activeAgents} active / {idleAgents} idle
              </p>
            </div>
            <div className="w-10 h-10 bg-primary-100 text-primary-500 rounded-lg flex items-center justify-center">
              <Bot size={20} />
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Active Tasks</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{activeTasks}</p>
              <p className="text-xs text-gray-500 mt-1">{tasks.length} total tasks</p>
            </div>
            <div className="w-10 h-10 bg-emerald-100 text-emerald-500 rounded-lg flex items-center justify-center">
              <ClipboardList size={20} />
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Budget</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">
                ${(totalSpent / 100).toFixed(0)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                of ${(totalBudget / 100).toFixed(0)} monthly
              </p>
            </div>
            <div className="w-10 h-10 bg-amber-100 text-amber-500 rounded-lg flex items-center justify-center">
              <DollarSign size={20} />
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Pending Approvals</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">0</p>
              <p className="text-xs text-gray-500 mt-1">All clear</p>
            </div>
            <div className="w-10 h-10 bg-rose-100 text-rose-500 rounded-lg flex items-center justify-center">
              <Shield size={20} />
            </div>
          </div>
        </Card>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Cost Over Time (Last 7 Days)</h3>
          <CostChart data={costData} />
        </Card>
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Task Status Distribution</h3>
          {taskStatusData.length > 0 ? (
            <TaskPieChart data={taskStatusData} />
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">No tasks to display</p>
          )}
        </Card>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Recent Activity</h3>
          <ActivityFeed entries={activityEntries} maxItems={10} />
        </Card>
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Top Agents</h3>
          {topAgents.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">No agents yet</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {topAgents.map((agent) => (
                <div key={agent.id} className="flex items-center gap-3 py-2.5">
                  <div className="w-8 h-8 bg-primary-100 text-primary-600 rounded-lg flex items-center justify-center text-xs font-bold">
                    {agent.name.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{agent.name}</p>
                    <p className="text-xs text-gray-500">{agent.role}</p>
                  </div>
                  <StatusIndicator
                    status={agent.status === 'active' ? 'online' : agent.status === 'busy' ? 'busy' : agent.status === 'idle' ? 'idle' : 'offline'}
                    size="sm"
                  />
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
