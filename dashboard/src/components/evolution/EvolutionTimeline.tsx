import type { Evaluation } from '@/types/evolution';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { formatRelativeTime } from '@/utils/time';

export interface EvolutionTimelineProps {
  evaluations: Evaluation[];
  className?: string;
}

export function EvolutionTimeline({ evaluations, className = '' }: EvolutionTimelineProps) {
  if (evaluations.length === 0) {
    return (
      <Card className={className}>
        <p className="text-sm text-gray-500 text-center py-6">No evolution history yet.</p>
      </Card>
    );
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {evaluations.map((evaluation) => {
        const improved = evaluation.improvement_percent > 0;
        return (
          <Card key={evaluation.id}>
            <div className="flex items-center gap-3">
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                improved ? 'bg-emerald-100 text-emerald-600' : 'bg-rose-100 text-rose-600'
              }`}>
                {improved ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900">
                    {improved ? '+' : ''}{evaluation.improvement_percent.toFixed(1)}% improvement
                  </span>
                  <Badge variant={evaluation.passed ? 'success' : 'danger'} size="sm">
                    {evaluation.passed ? 'Passed' : 'Failed'}
                  </Badge>
                </div>
                <div className="flex items-center gap-4 mt-1 text-xs text-gray-500">
                  <span>Baseline: {evaluation.baseline_score.toFixed(2)}</span>
                  <span>Candidate: {evaluation.candidate_score.toFixed(2)}</span>
                  <span>Significance: {(evaluation.statistical_significance * 100).toFixed(0)}%</span>
                  <span>{formatRelativeTime(evaluation.evaluated_at)}</span>
                </div>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
