import { ActivityItem, type ActivityEntry } from './ActivityItem';
import { Spinner } from '@/components/common/Spinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Activity } from 'lucide-react';

export interface ActivityFeedProps {
  entries: ActivityEntry[];
  loading?: boolean;
  maxItems?: number;
  className?: string;
}

export function ActivityFeed({ entries, loading = false, maxItems, className = '' }: ActivityFeedProps) {
  if (loading) {
    return <Spinner size="md" className="py-6" />;
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={<Activity size={36} />}
        title="No activity"
        description="No recent activity to display."
      />
    );
  }

  const displayed = maxItems ? entries.slice(0, maxItems) : entries;

  return (
    <div className={`divide-y divide-gray-100 ${className}`}>
      {displayed.map((entry) => (
        <ActivityItem key={entry.id} entry={entry} />
      ))}
    </div>
  );
}
