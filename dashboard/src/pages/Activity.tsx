import { useCallback } from 'react';
import { ActivityFeed, type ActivityEntry } from '@/components/activity';
import { useApi } from '@/hooks/useApi';
import { usePolling } from '@/hooks/usePolling';
import { tasksApi } from '@/api/tasks';
import type { Task } from '@/types/task';
import type { PaginatedResponse } from '@/types/common';
import { Spinner } from '@/components/common/Spinner';

const COMPANY_ID = 'default';

export function Activity() {
  const { data, loading, refetch } = useApi<PaginatedResponse<Task>>(
    () => tasksApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const handlePoll = useCallback(() => {
    void refetch();
  }, [refetch]);

  usePolling(handlePoll, { interval: 30000 });

  const tasks = data?.items ?? [];

  const activityEntries: ActivityEntry[] = tasks
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .map((t) => ({
      id: t.id,
      type: t.status === 'completed'
        ? 'task_completed' as const
        : t.status === 'failed'
          ? 'task_failed' as const
          : 'agent_action' as const,
      message: `Task "${t.title}" is ${t.status.replace('_', ' ')}`,
      timestamp: t.updated_at,
    }));

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Activity</h1>
        <p className="text-sm text-gray-500 mt-1">Full activity log across all agents and tasks</p>
      </div>

      <ActivityFeed entries={activityEntries} />
    </div>
  );
}
