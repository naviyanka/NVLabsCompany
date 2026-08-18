import { ProposalList } from '@/components/evolution/ProposalList';
import { EvolutionTimeline } from '@/components/evolution/EvolutionTimeline';
import type { Proposal, Evaluation } from '@/types/evolution';

export function Evolution() {
  // In a full implementation this would fetch from the API
  const proposals: Proposal[] = [];
  const evaluations: Evaluation[] = [];
  const loading = false;
  const error = null;

  const handleApprove = (proposal: Proposal) => {
    console.log('Approve proposal', proposal.id);
  };

  const handleReject = (proposal: Proposal) => {
    console.log('Reject proposal', proposal.id);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Evolution</h1>
        <p className="text-sm text-gray-500 mt-1">Self-improvement proposals and evaluation history</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Active Proposals</h3>
          <ProposalList
            proposals={proposals}
            loading={loading}
            error={error}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Evolution Timeline</h3>
          <EvolutionTimeline evaluations={evaluations} />
        </div>
      </div>
    </div>
  );
}
