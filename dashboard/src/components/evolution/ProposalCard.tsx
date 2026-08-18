import type { Proposal } from '@/types/evolution';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import type { BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Sparkles } from 'lucide-react';
import { formatRelativeTime } from '@/utils/time';

export interface ProposalCardProps {
  proposal: Proposal;
  onApprove?: (proposal: Proposal) => void;
  onReject?: (proposal: Proposal) => void;
}

function riskVariant(risk: string): BadgeVariant {
  switch (risk) {
    case 'high': return 'danger';
    case 'medium': return 'warning';
    case 'low': return 'success';
    default: return 'default';
  }
}

function statusVariant(status: Proposal['status']): BadgeVariant {
  switch (status) {
    case 'approved':
    case 'deployed': return 'success';
    case 'proposed':
    case 'evaluating': return 'info';
    case 'rejected': return 'danger';
    case 'draft': return 'default';
    default: return 'default';
  }
}

export function ProposalCard({ proposal, onApprove, onReject }: ProposalCardProps) {
  const isPending = proposal.status === 'proposed' || proposal.status === 'evaluating';

  return (
    <Card>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 bg-primary-100 text-primary-600 rounded-lg flex items-center justify-center flex-shrink-0">
          <Sparkles size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">{proposal.title}</h3>
              <p className="text-xs text-gray-500 mt-0.5">{proposal.description}</p>
            </div>
            <Badge variant={statusVariant(proposal.status)} size="sm">
              {proposal.status}
            </Badge>
          </div>
          <div className="flex items-center gap-3 mt-3">
            <Badge variant="default" size="sm">{proposal.proposal_type}</Badge>
            <Badge variant={riskVariant(proposal.risk_level)} size="sm">
              {proposal.risk_level} risk
            </Badge>
            <span className="text-xs text-gray-500">
              Confidence: {(proposal.confidence * 100).toFixed(0)}%
            </span>
            <span className="text-xs text-gray-500">
              {formatRelativeTime(proposal.created_at)}
            </span>
          </div>
          <p className="text-xs text-gray-600 mt-2">
            Impact: {proposal.expected_impact}
          </p>
          {isPending && (
            <div className="flex items-center gap-2 mt-3">
              <Button variant="secondary" size="sm" onClick={() => onReject?.(proposal)}>
                Reject
              </Button>
              <Button variant="primary" size="sm" onClick={() => onApprove?.(proposal)}>
                Approve
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
