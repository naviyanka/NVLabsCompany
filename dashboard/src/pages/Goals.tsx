import { Card } from '@/components/common/Card';
import { EmptyState } from '@/components/common/EmptyState';
import { Badge } from '@/components/common/Badge';
import { Target } from 'lucide-react';

interface Goal {
  id: string;
  title: string;
  description: string;
  status: 'active' | 'completed' | 'paused';
  progress: number;
}

const sampleGoals: Goal[] = [
  {
    id: '1',
    title: 'Increase Code Quality',
    description: 'Achieve 90% test coverage across all services',
    status: 'active',
    progress: 65,
  },
  {
    id: '2',
    title: 'Reduce Deployment Time',
    description: 'Bring average deployment time under 5 minutes',
    status: 'active',
    progress: 40,
  },
  {
    id: '3',
    title: 'Improve Agent Efficiency',
    description: 'Reduce average task completion time by 20%',
    status: 'paused',
    progress: 25,
  },
];

export function Goals() {
  const goals = sampleGoals;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Goals</h1>
        <p className="text-sm text-gray-500 mt-1">Strategic objectives and progress tracking</p>
      </div>

      {goals.length === 0 ? (
        <EmptyState
          icon={<Target size={48} />}
          title="No goals defined"
          description="Define strategic goals to track organizational progress."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {goals.map((goal) => (
            <Card key={goal.id}>
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-semibold text-gray-900">{goal.title}</h3>
                <Badge
                  variant={goal.status === 'active' ? 'success' : goal.status === 'completed' ? 'primary' : 'default'}
                  size="sm"
                >
                  {goal.status}
                </Badge>
              </div>
              <p className="text-xs text-gray-500 mb-3">{goal.description}</p>
              <div className="flex items-center gap-3">
                <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary-500 rounded-full"
                    style={{ width: `${goal.progress}%` }}
                  />
                </div>
                <span className="text-xs text-gray-600 font-medium">{goal.progress}%</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
