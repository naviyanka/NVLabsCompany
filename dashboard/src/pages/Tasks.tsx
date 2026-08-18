import { useState } from 'react';
import { TaskList } from '@/components/tasks/TaskList';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { useApi } from '@/hooks/useApi';
import { tasksApi } from '@/api/tasks';
import type { Task } from '@/types/task';
import type { PaginatedResponse, TaskStatus } from '@/types/common';
import { List, Columns3 } from 'lucide-react';
import { COMPANY_ID } from '@/config';

type ViewMode = 'list' | 'kanban';

const KANBAN_COLUMNS: { status: TaskStatus; label: string; color: string }[] = [
  { status: 'pending', label: 'Pending', color: 'bg-amber-100' },
  { status: 'in_progress', label: 'In Progress', color: 'bg-primary-100' },
  { status: 'completed', label: 'Completed', color: 'bg-emerald-100' },
  { status: 'failed', label: 'Failed', color: 'bg-rose-100' },
];

export function Tasks() {
  const [viewMode, setViewMode] = useState<ViewMode>('list');

  const { data, loading, error } = useApi<PaginatedResponse<Task>>(
    () => tasksApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const tasks = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tasks</h1>
          <p className="text-sm text-gray-500 mt-1">Track and manage all tasks across agents</p>
        </div>
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded ${viewMode === 'list' ? 'bg-white shadow-sm' : 'text-gray-500'}`}
            aria-label="List view"
          >
            <List size={16} />
          </button>
          <button
            onClick={() => setViewMode('kanban')}
            className={`p-1.5 rounded ${viewMode === 'kanban' ? 'bg-white shadow-sm' : 'text-gray-500'}`}
            aria-label="Kanban view"
          >
            <Columns3 size={16} />
          </button>
        </div>
      </div>

      {viewMode === 'list' ? (
        <TaskList tasks={tasks} loading={loading} error={error} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {KANBAN_COLUMNS.map((col) => {
            const columnTasks = tasks.filter((t) => t.status === col.status);
            return (
              <div key={col.status}>
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${col.color} mb-3`}>
                  <span className="text-sm font-medium text-gray-900">{col.label}</span>
                  <Badge variant="default" size="sm">{columnTasks.length}</Badge>
                </div>
                <div className="space-y-2">
                  {columnTasks.map((task) => (
                    <Card key={task.id} padding="sm">
                      <h4 className="text-sm font-medium text-gray-900 truncate">{task.title}</h4>
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{task.description}</p>
                    </Card>
                  ))}
                  {columnTasks.length === 0 && (
                    <p className="text-xs text-gray-400 text-center py-4">No tasks</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
