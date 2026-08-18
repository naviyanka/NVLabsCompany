import type { Task } from '@/types/task';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import type { BadgeVariant } from '@/components/common/Badge';
import { Spinner } from '@/components/common/Spinner';
import { formatRelativeTime } from '@/utils/time';

export interface TaskDetailProps {
  task: Task | null;
  loading: boolean;
  error: string | null;
}

function statusVariant(status: Task['status']): BadgeVariant {
  switch (status) {
    case 'completed': return 'success';
    case 'in_progress': return 'primary';
    case 'assigned': return 'info';
    case 'pending': return 'warning';
    case 'failed': return 'danger';
    case 'cancelled': return 'default';
    default: return 'default';
  }
}

export function TaskDetail({ task, loading, error }: TaskDetailProps) {
  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load task</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="text-center py-12 text-gray-500">
        Task not found
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{task.title}</h1>
            <p className="text-sm text-gray-500 mt-1">{task.description}</p>
          </div>
          <Badge variant={statusVariant(task.status)}>
            {task.status.replace('_', ' ')}
          </Badge>
        </div>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Priority</dt>
            <dd className="text-gray-900 font-medium">{task.priority}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Created</dt>
            <dd className="text-gray-900">{formatRelativeTime(task.created_at)}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Started</dt>
            <dd className="text-gray-900">{task.started_at ? formatRelativeTime(task.started_at) : 'Not started'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Completed</dt>
            <dd className="text-gray-900">{task.completed_at ? formatRelativeTime(task.completed_at) : 'In progress'}</dd>
          </div>
        </dl>
      </Card>

      {task.result && (
        <Card>
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Result</h3>
          <pre className="text-sm text-gray-700 bg-gray-50 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
            {task.result}
          </pre>
        </Card>
      )}

      {task.error && (
        <Card>
          <h3 className="text-sm font-semibold text-rose-700 mb-2">Error</h3>
          <pre className="text-sm text-rose-700 bg-rose-50 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
            {task.error}
          </pre>
        </Card>
      )}
    </div>
  );
}
