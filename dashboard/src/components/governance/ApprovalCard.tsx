import type { Approval } from '@/types/company';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import type { BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Shield, Clock } from 'lucide-react';
import { formatRelativeTime } from '@/utils/time';

export interface ApprovalCardProps {
  approval: Approval;
  onApprove?: (approval: Approval) => void;
  onReject?: (approval: Approval) => void;
}

function riskLevel(payload: Record<string, unknown>): string {
  const risk = payload.risk_level as string | undefined;
  return risk || 'medium';
}

function riskVariant(risk: string): BadgeVariant {
  switch (risk) {
    case 'high': return 'danger';
    case 'medium': return 'warning';
    case 'low': return 'success';
    default: return 'default';
  }
}

export function ApprovalCard({ approval, onApprove, onReject }: ApprovalCardProps) {
  const risk = riskLevel(approval.payload);
  const isPending = approval.status === 'pending';

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 bg-amber-100 text-amber-600 rounded-lg flex items-center justify-center flex-shrink-0">
            <Shield size={16} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900">{approval.type}</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Requested by agent {approval.requested_by_agent_id.slice(0, 8)}...
            </p>
            <div className="flex items-center gap-2 mt-2">
              <Badge variant={riskVariant(risk)} size="sm">
                {risk} risk
              </Badge>
              <span className="flex items-center gap-1 text-xs text-gray-500">
                <Clock size={12} />
                {formatRelativeTime(approval.created_at)}
              </span>
            </div>
          </div>
        </div>
        {isPending && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => onReject?.(approval)}>
              Reject
            </Button>
            <Button variant="primary" size="sm" onClick={() => onApprove?.(approval)}>
              Approve
            </Button>
          </div>
        )}
        {!isPending && (
          <Badge variant={approval.status === 'approved' ? 'success' : 'danger'}>
            {approval.status}
          </Badge>
        )}
      </div>
    </Card>
  );
}
