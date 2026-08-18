import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Play, Clock } from 'lucide-react';
import type { WorkflowStatusResponse } from '@/types/evolution';
import { formatRelativeTime } from '@/utils/time';

export function Workflows() {
  // In a full implementation this would fetch from the workflows API
  const workflows: WorkflowStatusResponse[] = [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Workflows</h1>
        <p className="text-sm text-gray-500 mt-1">Active workflow executions and delegation chains</p>
      </div>

      {workflows.length === 0 ? (
        <EmptyState
          icon={<Play size={48} />}
          title="No active workflows"
          description="Workflow executions will appear here when running."
        />
      ) : (
        <div className="space-y-4">
          {workflows.map((wf) => (
            <Card key={wf.workflow_id}>
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">{wf.objective}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Current step: {wf.current_step}
                  </p>
                </div>
                <Badge variant={wf.status === 'running' ? 'info' : wf.status === 'completed' ? 'success' : 'danger'}>
                  {wf.status}
                </Badge>
              </div>
              <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden mb-2">
                <div className="h-full bg-primary-500 rounded-full" style={{ width: '50%' }} />
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                  <Clock size={12} />
                  Started {formatRelativeTime(wf.started_at)}
                </span>
                <span>Cost: ${(wf.total_cost_cents / 100).toFixed(2)}</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
