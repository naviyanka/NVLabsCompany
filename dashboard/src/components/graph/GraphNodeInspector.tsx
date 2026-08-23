import {
  X,
  Sparkles,
  Link as LinkIcon,
  AlertTriangle,
  Flame,
  ExternalLink,
  Compass,
} from 'lucide-react';
import {
  MemoryGraphNode,
  MemoryGraphLink,
} from '@/types/memoryGraph';
import { NODE_TYPE_COLORS, MEMORY_CLUSTERS } from '@/lib/memoryGraphAdapter';

interface GraphNodeInspectorProps {
  node: MemoryGraphNode | null;
  links: MemoryGraphLink[];
  allNodes: MemoryGraphNode[];
  onClose: () => void;
  onSelectNode: (node: MemoryGraphNode) => void;
  onReinforce: (nodeId: string) => void;
  onResolveContradiction: (
    nodeId: string,
    action: 'prune' | 'override' | 'archive'
  ) => void;
  onFocusNodeNeighborhood: (nodeId: string) => void;
}

export function GraphNodeInspector({
  node,
  links,
  allNodes,
  onClose,
  onSelectNode,
  onReinforce,
  onResolveContradiction,
  onFocusNodeNeighborhood,
}: GraphNodeInspectorProps) {
  if (!node) return null;

  const colors = NODE_TYPE_COLORS[node.type] || {
    bg: '#FFB020',
    border: '#F59E0B',
    text: '#0A0A0B',
  };
  const cluster = MEMORY_CLUSTERS.find((c) => c.id === node.community);

  // Find incoming and outgoing links
  const connectedLinks = links.filter((l) => {
    const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
    const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
    return sId === node.id || tId === node.id;
  });

  const neighborNodes = connectedLinks.map((l) => {
    const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
    const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
    const isSource = sId === node.id;
    const otherId = isSource ? tId : sId;
    const otherNode = allNodes.find((n) => n.id === otherId);
    return {
      link: l,
      isSource,
      node: otherNode,
      edgeType: l.type,
      label: l.label,
    };
  });

  return (
    <div className="w-full lg:w-96 bg-[#101012] border-l border-white/[0.08] flex flex-col h-full overflow-hidden shadow-2xl">
      {/* Header */}
      <div className="p-4 border-b border-white/[0.08] bg-[#0E0E10] flex items-start justify-between gap-3 shrink-0">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="px-2 py-0.5 rounded text-[10px] font-mono font-medium uppercase"
              style={{
                backgroundColor: `${colors.bg}22`,
                color: colors.bg,
                border: `1px solid ${colors.border}`,
              }}
            >
              {node.type}
            </span>
            {cluster && (
              <span
                className="px-2 py-0.5 rounded text-[10px] font-mono"
                style={{
                  backgroundColor: `${cluster.color}15`,
                  color: cluster.color,
                }}
              >
                {(cluster.name || 'Cluster').split(' ')[0]}
              </span>
            )}
          </div>
          <h2 className="text-sm font-semibold font-display text-[#F2F1EE] mt-1.5 leading-snug">
            {node.label}
          </h2>
        </div>

        <button
          onClick={onClose}
          className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body / Scrollable Info */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs font-sans">
        {/* Contradiction Alert Box */}
        {node.type === 'contradiction' && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-[6px] space-y-2">
            <div className="flex items-center gap-2 text-red-400 font-mono font-medium text-[11px]">
              <AlertTriangle className="w-4 h-4" />
              <span>CONFLICTING BELIEF DETECTED</span>
            </div>
            <p className="text-red-200/90 text-xs leading-relaxed">
              {node.contradiction_reason || node.summary}
            </p>
            <div className="flex items-center gap-2 pt-2 border-t border-red-500/20">
              <button
                onClick={() => onResolveContradiction(node.id, 'override')}
                className="flex-1 px-2.5 py-1 bg-red-500/20 hover:bg-red-500/30 text-red-300 font-mono text-[11px] rounded transition-colors cursor-pointer"
              >
                Synthesize
              </button>
              <button
                onClick={() => onResolveContradiction(node.id, 'prune')}
                className="flex-1 px-2.5 py-1 bg-red-600 hover:bg-red-700 text-white font-mono text-[11px] rounded transition-colors cursor-pointer"
              >
                Prune Branch
              </button>
            </div>
          </div>
        )}

        {/* Summary */}
        <div>
          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">
            Core Synopsis
          </div>
          <p className="text-[#A8A8AB] leading-relaxed bg-[#141416] p-3 border border-white/[0.04] rounded-[6px]">
            {node.summary}
          </p>
        </div>

        {/* Quantitative Metrics Row */}
        <div className="grid grid-cols-2 gap-2">
          <div className="p-2.5 bg-[#141416] border border-white/[0.04] rounded-[6px]">
            <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] mb-1">
              <span>CONFIDENCE</span>
              <Sparkles className="w-3 h-3 text-[#22C55E]" />
            </div>
            <div className="text-base font-mono font-semibold text-[#F2F1EE]">
              {Math.round(node.confidence * 100)}%
            </div>
            <div className="w-full bg-white/[0.06] h-1 rounded-full overflow-hidden mt-1.5">
              <div
                className="bg-[#22C55E] h-full"
                style={{ width: `${node.confidence * 100}%` }}
              />
            </div>
          </div>

          <div className="p-2.5 bg-[#141416] border border-white/[0.04] rounded-[6px]">
            <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] mb-1">
              <span>IMPORTANCE</span>
              <Flame className="w-3 h-3 text-[#FFB020]" />
            </div>
            <div className="text-base font-mono font-semibold text-[#F2F1EE]">
              {(node.importance * 100).toFixed(0)}%
            </div>
            <div className="w-full bg-white/[0.06] h-1 rounded-full overflow-hidden mt-1.5">
              <div
                className="bg-[#FFB020] h-full"
                style={{ width: `${node.importance * 100}%` }}
              />
            </div>
          </div>
        </div>

        {/* Vector Embedding Preview */}
        <div>
          <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
            <span>HNSW Embedding (1536-D)</span>
            <span>{node.access_count ?? 1} Hits</span>
          </div>
          <div className="p-2.5 bg-[#141416] border border-white/[0.04] rounded-[6px] space-y-1.5 font-mono text-[11px]">
            <div className="grid grid-cols-4 gap-1 text-[#6B6B6E]">
              {node.embedding_preview?.map((val, i) => (
                <div
                  key={i}
                  className="bg-[#0E0E10] px-1.5 py-0.5 rounded text-center text-[10px]"
                  style={{
                    color: val > 0 ? '#34D399' : '#F472B6',
                  }}
                >
                  {val.toFixed(3)}
                </div>
              ))}
            </div>
            <div className="text-[10px] text-[#6B6B6E] pt-1 border-t border-white/[0.04] flex items-center justify-between">
              <span>Cosine Index: Optimal</span>
              <span>Decay: {Math.round((node.decay_score ?? 1) * 100)}%</span>
            </div>
          </div>
        </div>

        {/* Tags */}
        {node.tags && node.tags.length > 0 && (
          <div>
            <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
              Semantic Tags
            </div>
            <div className="flex flex-wrap gap-1">
              {node.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 bg-[#141416] text-[#A8A8AB] border border-white/[0.06] rounded text-[10px] font-mono"
                >
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Connected Associations */}
        <div>
          <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
            <span>Connected Associations ({connectedLinks.length})</span>
            <LinkIcon className="w-3 h-3" />
          </div>

          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {neighborNodes.map(({ link, node: neighbor, edgeType, label }) => {
              if (!neighbor) return null;
              const nColors = NODE_TYPE_COLORS[neighbor.type];

              return (
                <button
                  key={link.id}
                  onClick={() => onSelectNode(neighbor)}
                  className="w-full text-left p-2 bg-[#141416] hover:bg-white/[0.04] border border-white/[0.04] rounded-[6px] transition-colors cursor-pointer flex items-center justify-between gap-2"
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: nColors.bg }}
                    />
                    <div className="overflow-hidden">
                      <div className="text-xs font-medium text-[#F2F1EE] truncate">
                        {neighbor.label}
                      </div>
                      <div className="text-[10px] font-mono text-[#6B6B6E] truncate">
                        {label || edgeType.replace('_', ' ')}
                      </div>
                    </div>
                  </div>
                  <ExternalLink className="w-3 h-3 text-[#6B6B6E] shrink-0" />
                </button>
              );
            })}
          </div>
        </div>

        {/* Metadata */}
        <div className="pt-2 border-t border-white/[0.04] space-y-1 text-[10px] font-mono text-[#6B6B6E]">
          <div className="flex justify-between">
            <span>Node ID:</span>
            <span className="text-[#A8A8AB]">{node.id}</span>
          </div>
          <div className="flex justify-between">
            <span>Owner Agent:</span>
            <span className="text-[#FFB020]">{node.agent_id || 'System'}</span>
          </div>
          <div className="flex justify-between">
            <span>Created:</span>
            <span className="text-[#A8A8AB]">
              {new Date(node.created_at).toLocaleDateString()}
            </span>
          </div>
        </div>
      </div>

      {/* Action Footer */}
      <div className="p-3 border-t border-white/[0.08] bg-[#0E0E10] flex items-center gap-2 shrink-0">
        <button
          onClick={() => onReinforce(node.id)}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-[#FFB020] hover:bg-[#FFB020]/90 text-[#0A0A0B] font-mono font-medium text-xs rounded-[6px] transition-colors cursor-pointer"
        >
          <Flame className="w-3.5 h-3.5" />
          <span>Reinforce Memory</span>
        </button>

        <button
          onClick={() => onFocusNodeNeighborhood(node.id)}
          className="flex items-center justify-center p-2 bg-[#141416] hover:bg-white/[0.06] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded-[6px] transition-colors cursor-pointer"
          title="Isolate 1-Hop Neighborhood"
        >
          <Compass className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
