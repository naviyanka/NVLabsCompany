import type { Proposal } from '@/types/evolution';
import { ProposalCard } from './ProposalCard';
import { Spinner } from '@/components/common/Spinner';
import { EmptyState } from '@/components/common/EmptyState';
import { Sparkles } from 'lucide-react';

export interface ProposalListProps {
  proposals: Proposal[];
  loading: boolean;
  error: string | null;
  onApprove?: (proposal: Proposal) => void;
  onReject?: (proposal: Proposal) => void;
}

export function ProposalList({ proposals, loading, error, onApprove, onReject }: ProposalListProps) {
  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load proposals</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  if (proposals.length === 0) {
    return (
      <EmptyState
        icon={<Sparkles size={48} />}
        title="No proposals"
        description="No evolution proposals have been submitted yet."
      />
    );
  }

  return (
    <div className="space-y-3">
      {proposals.map((proposal) => (
        <ProposalCard
          key={proposal.id}
          proposal={proposal}
          onApprove={onApprove}
          onReject={onReject}
        />
      ))}
    </div>
  );
}
