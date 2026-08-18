import type { Approval } from '@/types/company';
import { ApprovalCard } from './ApprovalCard';
import { Spinner } from '@/components/common/Spinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Shield } from 'lucide-react';

export interface ApprovalListProps {
  approvals: Approval[];
  loading: boolean;
  error: string | null;
  onApprove?: (approval: Approval) => void;
  onReject?: (approval: Approval) => void;
}

export function ApprovalList({ approvals, loading, error, onApprove, onReject }: ApprovalListProps) {
  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load approvals</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (approvals.length === 0) {
    return (
      <EmptyState
        icon={<Shield size={48} />}
        title="No pending approvals"
        description="All approval requests have been resolved."
      />
    );
  }

  return (
    <div className="space-y-3">
      {approvals.map((approval) => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          onApprove={onApprove}
          onReject={onReject}
        />
      ))}
    </div>
  );
}
