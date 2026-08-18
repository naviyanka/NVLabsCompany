import { useState } from 'react';
import type { Task } from '@/types/task';
import type { TaskStatus } from '@/types/common';
import { TaskCard } from './TaskCard';
import { Spinner } from '@/components/common/Spinner';
import { EmptyState } from '@/components/common/EmptyState';
import { ClipboardList } from 'lucide-react';

export interface TaskListProps {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  onTaskClick?: (task: Task) => void;
}

export function TaskList({ tasks, loading, error, onTaskClick }: TaskListProps) {
  const [statusFilter, setStatusFilter] = useState<TaskStatus | 'all'>('all');
  const [priorityFilter, setPriorityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load tasks</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  const filteredTasks = tasks.filter((task) => {
    if (statusFilter !== 'all' && task.status !== statusFilter) return false;
    if (priorityFilter !== 'all') {
      if (priorityFilter === 'high' && task.priority < 8) return false;
      if (priorityFilter === 'medium' && (task.priority < 5 || task.priority >= 8)) return false;
      if (priorityFilter === 'low' && task.priority >= 5) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as TaskStatus | 'all')}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        >
          <option value="all">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="assigned">Assigned</option>
          <option value="in_progress">In Progress</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value as 'all' | 'high' | 'medium' | 'low')}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        >
          <option value="all">All Priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {filteredTasks.length === 0 ? (
        <EmptyState
          icon={<ClipboardList size={48} />}
          title="No tasks found"
          description="No tasks match the current filters."
        />
      ) : (
        <div className="space-y-3">
          {filteredTasks.map((task) => (
            <TaskCard key={task.id} task={task} onClick={onTaskClick} />
          ))}
        </div>
      )}
    </div>
  );
}
