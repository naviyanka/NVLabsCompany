import type { Task } from '@/types/task';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import type { BadgeVariant } from '@/components/common/Badge';
import { Calendar, User } from 'lucide-react';
import { formatRelativeTime } from '@/utils/time';

export interface TaskCardProps {
  task: Task;
  onClick?: (task: Task) => void;
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

function priorityVariant(priority: number): BadgeVariant {
  if (priority >= 8) return 'danger';
  if (priority >= 5) return 'warning';
  return 'default';
}

function priorityLabel(priority: number): string {
  if (priority >= 8) return 'High';
  if (priority >= 5) return 'Medium';
  return 'Low';
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  return (
    <Card
      className="hover:border-primary-200"
      onClick={onClick ? () => onClick(task) : undefined}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900 truncate">{task.title}</h3>
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{task.description}</p>
        </div>
        <Badge variant={statusVariant(task.status)} size="sm">
          {task.status.replace('_', ' ')}
        </Badge>
      </div>
      <div className="flex items-center gap-4 mt-3 text-xs text-gray-500">
        <Badge variant={priorityVariant(task.priority)} size="sm">
          {priorityLabel(task.priority)}
        </Badge>
        {task.assigned_agent_id && (
          <span className="flex items-center gap-1">
            <User size={12} />
            Assigned
          </span>
        )}
        <span className="flex items-center gap-1">
          <Calendar size={12} />
          {formatRelativeTime(task.created_at)}
        </span>
      </div>
    </Card>
  );
}
