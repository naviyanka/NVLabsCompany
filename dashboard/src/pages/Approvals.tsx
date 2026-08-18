import { ApprovalList } from '@/components/governance/ApprovalList';
import type { Approval } from '@/types/company';

export function Approvals() {
  // In a full implementation, this would fetch from an approvals API endpoint
  const approvals: Approval[] = [];
  const loading = false;
  const error = null;

  const handleApprove = (approval: Approval) => {
    console.log('Approve', approval.id);
  };

  const handleReject = (approval: Approval) => {
    console.log('Reject', approval.id);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Approvals</h1>
        <p className="text-sm text-gray-500 mt-1">Review and manage pending approval requests</p>
      </div>

      <ApprovalList
        approvals={approvals}
        loading={loading}
        error={error}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    </div>
  );
}
