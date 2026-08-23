import {
  Brain,
  Database,
  Sparkles,
  AlertTriangle,
  Trash2,
  Activity,
  Plus,
} from 'lucide-react';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';

interface GraphMetricsHUDProps {
  totalNodes: number;
  totalLinks: number;
  contradictionsCount: number;
  avgConfidence: number;
  avgImportance: number;
  recallRate: number;
  hnswIndexKb: number;
  onPruneDecayed: () => void;
  onAddMemory: () => void;
  onOpenContradictions: () => void;
}

export function GraphMetricsHUD({
  totalNodes,
  totalLinks,
  contradictionsCount,
  avgConfidence,
  avgImportance,
  recallRate,
  hnswIndexKb,
  onPruneDecayed,
  onAddMemory,
  onOpenContradictions,
}: GraphMetricsHUDProps) {
  return (
    <div className="space-y-3">
      {/* Top Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Agent Memory & Knowledge Graph
            </h1>
            <span className="px-2 py-0.5 rounded bg-[#FFB020]/15 text-[#FFB020] text-[10px] font-mono border border-[#FFB020]/30 font-medium">
              CANONICAL REASONING ENGINE
            </span>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            GitNexus-inspired topological graph engine for episodic memory, provenance traces, facts, decisions, and belief conflicts
          </p>
        </div>

        <div className="flex items-center gap-2">
          {contradictionsCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              icon={<AlertTriangle size={14} className="text-red-400" />}
              onClick={onOpenContradictions}
              className="border-red-500/30 text-red-300 hover:bg-red-500/10"
            >
              {contradictionsCount} Conflicts
            </Button>
          )}

          <Button
            variant="secondary"
            size="sm"
            icon={<Trash2 size={14} />}
            onClick={onPruneDecayed}
          >
            Prune Decayed
          </Button>

          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={onAddMemory}
          >
            Inject Memory Node
          </Button>
        </div>
      </div>

      {/* Metric Cards Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Memory & Knowledge Nodes"
          value={totalNodes}
          subValue={`${totalLinks} Association Edges`}
          change="HNSW Dense Vector Space"
          changeType="positive"
          icon={<Database className="w-4 h-4" />}
        />

        <StatCard
          label="Vector Retrieval Recall"
          value={`${recallRate}%`}
          subValue={`${hnswIndexKb} KB Embedding Index`}
          change="Sub-12ms Cosine Query"
          changeType="positive"
          icon={<Sparkles className="w-4 h-4" />}
        />

        <StatCard
          label="Avg Graph Confidence"
          value={`${Math.round(avgConfidence * 100)}%`}
          subValue={`Importance: ${(avgImportance * 100).toFixed(0)}%`}
          change="Multi-agent verified"
          changeType="neutral"
          icon={<Activity className="w-4 h-4" />}
        />

        <StatCard
          label="Belief Contradictions"
          value={contradictionsCount}
          subValue={contradictionsCount === 0 ? 'Consistent Beliefs' : 'Active Anomaly Gate'}
          change={contradictionsCount === 0 ? 'Zero Regressions' : 'Needs Operator Action'}
          changeType={contradictionsCount === 0 ? 'positive' : 'negative'}
          icon={<AlertTriangle className="w-4 h-4" />}
        />
      </div>
    </div>
  );
}
