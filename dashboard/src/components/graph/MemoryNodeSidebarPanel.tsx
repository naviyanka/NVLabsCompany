import { useState, useMemo } from 'react';
import {
  X,
  Sparkles,
  Flame,
  AlertTriangle,
  ArrowRight,
  ArrowLeft,
  ArrowDownLeft,
  ArrowUpRight,
  ExternalLink,
  Compass,
  Copy,
  Check,
  Maximize2,
  Minimize2,
  GitBranch,
  Layers,
  Clock,
  User,
  Hash,
  Database,
  Search,
  Info,
  PanelRightClose,
  PanelRight,
  Route,
} from 'lucide-react';
import {
  MemoryGraphNode,
  MemoryGraphLink,
} from '@/types/memoryGraph';
import { NODE_TYPE_COLORS, MEMORY_CLUSTERS, EDGE_TYPE_COLORS } from '@/lib/memoryGraphAdapter';

interface MemoryNodeSidebarPanelProps {
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
  onFilterByTag?: (tag: string) => void;
  onStartPathFromNode?: (node: MemoryGraphNode) => void;
  displayMode?: 'overlay' | 'docked';
  onToggleDisplayMode?: () => void;
}

type TabType = 'overview' | 'lineage' | 'relationships' | 'raw';

export function MemoryNodeSidebarPanel({
  node,
  links,
  allNodes,
  onClose,
  onSelectNode,
  onReinforce,
  onResolveContradiction,
  onFocusNodeNeighborhood,
  onFilterByTag,
  onStartPathFromNode,
  displayMode = 'overlay',
  onToggleDisplayMode,
}: MemoryNodeSidebarPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [isExpandedWidth, setIsExpandedWidth] = useState(false);
  const [copiedId, setCopiedId] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [relationSearch, setRelationSearch] = useState('');
  const [relationTypeFilter, setRelationTypeFilter] = useState<'all' | 'incoming' | 'outgoing'>('all');

  if (!node) return null;

  const colors = NODE_TYPE_COLORS[node.type] || {
    bg: '#FFB020',
    border: '#F59E0B',
    text: '#0A0A0B',
    glow: 'rgba(255,176,32,0.4)',
  };
  const cluster = MEMORY_CLUSTERS.find((c) => c.id === node.community);

  // Incoming Links (Source -> node)
  const incomingLinks = useMemo(() => {
    return links
      .filter((l) => {
        const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
        return tId === node.id;
      })
      .map((l) => {
        const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
        const sourceNode = allNodes.find((n) => n.id === sId);
        return {
          link: l,
          otherNode: sourceNode,
          direction: 'incoming' as const,
        };
      });
  }, [links, node.id, allNodes]);

  // Outgoing Links (node -> Target)
  const outgoingLinks = useMemo(() => {
    return links
      .filter((l) => {
        const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
        return sId === node.id;
      })
      .map((l) => {
        const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
        const targetNode = allNodes.find((n) => n.id === tId);
        return {
          link: l,
          otherNode: targetNode,
          direction: 'outgoing' as const,
        };
      });
  }, [links, node.id, allNodes]);

  // Provenance Lineage: Upstream ancestors and Downstream descendants
  const provenanceLineage = useMemo(() => {
    // 1. Explicit provenance sources in node definition
    const directSourceIds = new Set(node.provenance_sources || []);
    
    // 2. Incoming derivation edges (derived_from, produced_by, supports, informs)
    incomingLinks.forEach((item) => {
      if (['derived_from', 'produced_by', 'supports', 'informs'].includes(item.link.type)) {
        if (item.otherNode) directSourceIds.add(item.otherNode.id);
      }
    });

    const upstreamNodes = Array.from(directSourceIds)
      .map((id) => allNodes.find((n) => n.id === id))
      .filter((n): n is MemoryGraphNode => Boolean(n));

    // Downstream derived nodes
    const downstreamIds = new Set<string>();
    outgoingLinks.forEach((item) => {
      if (['derived_from', 'produced_by', 'supports', 'informs'].includes(item.link.type)) {
        if (item.otherNode) downstreamIds.add(item.otherNode.id);
      }
    });
    // Also check if other nodes list this node in their provenance_sources
    allNodes.forEach((n) => {
      if (n.provenance_sources?.includes(node.id)) {
        downstreamIds.add(n.id);
      }
    });

    const downstreamNodes = Array.from(downstreamIds)
      .map((id) => allNodes.find((n) => n.id === id))
      .filter((n): n is MemoryGraphNode => Boolean(n));

    return {
      upstreamNodes,
      downstreamNodes,
    };
  }, [node, incomingLinks, outgoingLinks, allNodes]);

  // Filtered Relations
  const filteredRelations = useMemo(() => {
    const q = relationSearch.toLowerCase().trim();
    let list: Array<{ link: MemoryGraphLink; otherNode?: MemoryGraphNode; direction: 'incoming' | 'outgoing' }> = [];

    if (relationTypeFilter === 'all' || relationTypeFilter === 'incoming') {
      list = [...list, ...incomingLinks];
    }
    if (relationTypeFilter === 'all' || relationTypeFilter === 'outgoing') {
      list = [...list, ...outgoingLinks];
    }

    if (!q) return list;

    return list.filter((item) => {
      const labelMatch = item.otherNode?.label.toLowerCase().includes(q) ?? false;
      const typeMatch = item.otherNode?.type.toLowerCase().includes(q) ?? false;
      const edgeMatch = item.link.type.toLowerCase().includes(q) || (item.link.label?.toLowerCase().includes(q) ?? false);
      return labelMatch || typeMatch || edgeMatch;
    });
  }, [incomingLinks, outgoingLinks, relationSearch, relationTypeFilter]);

  const handleCopyId = () => {
    navigator.clipboard.writeText(node.id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(node, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
  };

  const totalConnected = incomingLinks.length + outgoingLinks.length;

  return (
    <aside
      id="memory-node-sidebar-panel"
      className={`bg-[#101012]/95 backdrop-blur-md flex flex-col h-full overflow-hidden shadow-2xl transition-all duration-200 z-30 ${
        displayMode === 'overlay'
          ? 'border border-white/[0.12] rounded-[10px]'
          : 'border-l border-white/[0.08]'
      } ${
        isExpandedWidth ? 'w-full sm:w-[540px]' : 'w-full sm:w-[410px]'
      }`}
    >
      {/* Top Header */}
      <div className="p-3.5 border-b border-white/[0.08] bg-[#0E0E10] flex flex-col gap-2 shrink-0">
        <div className="flex items-center justify-between gap-2">
          {/* Node Type & Domain Badge */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span
              className="px-2 py-0.5 rounded text-[10px] font-mono font-medium uppercase tracking-wider flex items-center gap-1"
              style={{
                backgroundColor: `${colors.bg}22`,
                color: colors.bg,
                border: `1px solid ${colors.border}`,
              }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: colors.bg }}
              />
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

            {node.agent_id && (
              <span className="px-2 py-0.5 bg-[#141416] text-[#A8A8AB] border border-white/[0.06] rounded text-[10px] font-mono flex items-center gap-1">
                <User className="w-2.5 h-2.5 text-[#FFB020]" />
                {node.agent_id.replace('agent-', '')}
              </span>
            )}
          </div>

          {/* Action Header Icons */}
          <div className="flex items-center gap-1">
            {onToggleDisplayMode && (
              <button
                onClick={onToggleDisplayMode}
                className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
                title={displayMode === 'overlay' ? 'Dock to Right Side' : 'Float as Overlay'}
              >
                {displayMode === 'overlay' ? (
                  <PanelRight className="w-3.5 h-3.5 text-[#FFB020]" />
                ) : (
                  <PanelRightClose className="w-3.5 h-3.5" />
                )}
              </button>
            )}
            <button
              onClick={() => setIsExpandedWidth(!isExpandedWidth)}
              className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
              title={isExpandedWidth ? 'Collapse Sidebar Width' : 'Expand Sidebar Width'}
            >
              {isExpandedWidth ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={onClose}
              className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
              title="Close Panel"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Title */}
        <div>
          <h2 className="text-sm font-semibold font-display text-[#F2F1EE] leading-snug break-words">
            {node.label}
          </h2>
          <div className="flex items-center gap-2 mt-1 text-[10px] font-mono text-[#6B6B6E]">
            <span className="flex items-center gap-1">
              <Hash className="w-2.5 h-2.5" />
              {node.id}
            </span>
            <button
              onClick={handleCopyId}
              className="hover:text-[#FFB020] transition-colors cursor-pointer"
              title="Copy Node ID"
            >
              {copiedId ? <Check className="w-2.5 h-2.5 text-[#22C55E]" /> : <Copy className="w-2.5 h-2.5" />}
            </button>
            <span>•</span>
            <span className="flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />
              {new Date(node.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        </div>

        {/* Tabs Bar */}
        <div className="flex items-center border-t border-white/[0.06] pt-2 mt-1 gap-1">
          <button
            onClick={() => setActiveTab('overview')}
            className={`flex-1 py-1 px-2 rounded text-[11px] font-mono transition-colors cursor-pointer flex items-center justify-center gap-1 ${
              activeTab === 'overview'
                ? 'bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30 font-medium'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.03]'
            }`}
          >
            <Info className="w-3 h-3" />
            <span>Properties</span>
          </button>

          <button
            onClick={() => setActiveTab('lineage')}
            className={`flex-1 py-1 px-2 rounded text-[11px] font-mono transition-colors cursor-pointer flex items-center justify-center gap-1 ${
              activeTab === 'lineage'
                ? 'bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30 font-medium'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.03]'
            }`}
          >
            <GitBranch className="w-3 h-3" />
            <span>Lineage ({provenanceLineage.upstreamNodes.length + provenanceLineage.downstreamNodes.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('relationships')}
            className={`flex-1 py-1 px-2 rounded text-[11px] font-mono transition-colors cursor-pointer flex items-center justify-center gap-1 ${
              activeTab === 'relationships'
                ? 'bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30 font-medium'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.03]'
            }`}
          >
            <Layers className="w-3 h-3" />
            <span>Relations ({totalConnected})</span>
          </button>

          <button
            onClick={() => setActiveTab('raw')}
            className={`py-1 px-2 rounded text-[11px] font-mono transition-colors cursor-pointer flex items-center justify-center gap-1 ${
              activeTab === 'raw'
                ? 'bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30 font-medium'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.03]'
            }`}
            title="Raw Vector JSON"
          >
            <Database className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs font-sans">
        {/* Contradiction Warning Alert */}
        {node.type === 'contradiction' && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-[6px] space-y-2">
            <div className="flex items-center gap-2 text-red-400 font-mono font-medium text-[11px]">
              <AlertTriangle className="w-4 h-4" />
              <span>BELIEF CONTRADICTION DETECTED</span>
            </div>
            <p className="text-red-200/90 text-xs leading-relaxed">
              {node.contradiction_reason || node.summary}
            </p>
            <div className="flex items-center gap-2 pt-2 border-t border-red-500/20">
              <button
                onClick={() => onResolveContradiction(node.id, 'override')}
                className="flex-1 px-2.5 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-300 font-mono text-[11px] rounded transition-colors cursor-pointer font-medium"
              >
                Synthesize
              </button>
              <button
                onClick={() => onResolveContradiction(node.id, 'prune')}
                className="flex-1 px-2.5 py-1.5 bg-red-600 hover:bg-red-700 text-white font-mono text-[11px] rounded transition-colors cursor-pointer font-medium"
              >
                Prune Branch
              </button>
            </div>
          </div>
        )}

        {/* ── TAB 1: OVERVIEW & PROPERTIES ── */}
        {activeTab === 'overview' && (
          <div className="space-y-4">
            {/* Core Synopsis */}
            <div>
              <div className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider mb-1.5 flex items-center justify-between">
                <span>Core Synopsis & Summary</span>
                <span>{node.access_count ?? 1} Recall Hits</span>
              </div>
              <p className="text-[#D4D4D8] leading-relaxed bg-[#141416] p-3 border border-white/[0.04] rounded-[6px]">
                {node.summary}
              </p>
            </div>

            {/* Quantitative Gauges */}
            <div className="grid grid-cols-2 gap-2.5">
              <div className="p-3 bg-[#141416] border border-white/[0.04] rounded-[6px]">
                <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] mb-1">
                  <span>CONFIDENCE</span>
                  <Sparkles className="w-3.5 h-3.5 text-[#22C55E]" />
                </div>
                <div className="text-lg font-mono font-semibold text-[#F2F1EE]">
                  {Math.round(node.confidence * 100)}%
                </div>
                <div className="w-full bg-white/[0.06] h-1.5 rounded-full overflow-hidden mt-2">
                  <div
                    className="bg-[#22C55E] h-full transition-all duration-300"
                    style={{ width: `${node.confidence * 100}%` }}
                  />
                </div>
                <div className="text-[9px] font-mono text-[#6B6B6E] mt-1.5">
                  Bayesian prior verification
                </div>
              </div>

              <div className="p-3 bg-[#141416] border border-white/[0.04] rounded-[6px]">
                <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] mb-1">
                  <span>IMPORTANCE</span>
                  <Flame className="w-3.5 h-3.5 text-[#FFB020]" />
                </div>
                <div className="text-lg font-mono font-semibold text-[#F2F1EE]">
                  {Math.round((node.importance || 0.5) * 100)}%
                </div>
                <div className="w-full bg-white/[0.06] h-1.5 rounded-full overflow-hidden mt-2">
                  <div
                    className="bg-[#FFB020] h-full transition-all duration-300"
                    style={{ width: `${(node.importance || 0.5) * 100}%` }}
                  />
                </div>
                <div className="text-[9px] font-mono text-[#6B6B6E] mt-1.5">
                  Long-term retention weight
                </div>
              </div>
            </div>

            {/* Retention & Time Decay Status */}
            <div className="p-3 bg-[#141416] border border-white/[0.04] rounded-[6px] space-y-2">
              <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase">
                <span>Memory Retention Decay</span>
                <span className="text-[#38BDF8]">
                  {Math.round((node.decay_score ?? 0.95) * 100)}% Freshness
                </span>
              </div>
              <div className="w-full bg-white/[0.06] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-[#38BDF8] h-full transition-all duration-300"
                  style={{ width: `${(node.decay_score ?? 0.95) * 100}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E]">
                <span>Status: Active In-Memory</span>
                <span>Last Updated: {new Date(node.updated_at).toLocaleDateString()}</span>
              </div>
            </div>

            {/* HNSW Vector Embedding Sparkline */}
            <div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
                <span>HNSW Dense Embedding (1536-D)</span>
                <span>Cos Sim Metric</span>
              </div>
              <div className="p-3 bg-[#141416] border border-white/[0.04] rounded-[6px] space-y-2">
                <div className="grid grid-cols-4 gap-1.5 text-center font-mono text-[10px]">
                  {(node.embedding_preview || [0.12, -0.45, 0.88, -0.05, 0.62, -0.31, 0.44, -0.19]).map((val, i) => (
                    <div
                      key={i}
                      className="bg-[#0E0E10] px-2 py-1 rounded border border-white/[0.04]"
                      style={{
                        color: val > 0 ? '#34D399' : '#F472B6',
                      }}
                    >
                      {val.toFixed(3)}
                    </div>
                  ))}
                </div>
                <div className="text-[10px] text-[#6B6B6E] pt-1.5 border-t border-white/[0.04] flex items-center justify-between font-mono">
                  <span>Dimension: 1536 (L2 Normed)</span>
                  <span className="text-[#34D399]">Indexed in HNSW</span>
                </div>
              </div>
            </div>

            {/* Semantic Tags */}
            {node.tags && node.tags.length > 0 && (
              <div>
                <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
                  Semantic Tags ({node.tags.length})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {node.tags.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => onFilterByTag?.(tag)}
                      className="px-2 py-0.5 bg-[#141416] hover:bg-white/[0.06] text-[#A8A8AB] hover:text-[#FFB020] border border-white/[0.06] rounded text-[10px] font-mono transition-colors cursor-pointer"
                    >
                      #{tag}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Node Properties Table */}
            <div>
              <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1.5">
                Node Properties Table
              </div>
              <div className="bg-[#141416] border border-white/[0.04] rounded-[6px] divide-y divide-white/[0.04] font-mono text-[11px]">
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Node Identifier:</span>
                  <span className="text-[#F2F1EE]">{node.id}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Memory Archetype:</span>
                  <span className="text-[#FFB020] uppercase">{node.type}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Domain Cluster:</span>
                  <span className="text-[#38BDF8]">{cluster?.name || node.community}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Owning Agent:</span>
                  <span className="text-[#A78BFA]">{node.agent_id || 'System Executive'}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Created Timestamp:</span>
                  <span className="text-[#A8A8AB]">{new Date(node.created_at).toLocaleString()}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Total Incoming Edges:</span>
                  <span className="text-[#22C55E]">{incomingLinks.length}</span>
                </div>
                <div className="p-2 flex justify-between">
                  <span className="text-[#6B6B6E]">Total Outgoing Edges:</span>
                  <span className="text-[#38BDF8]">{outgoingLinks.length}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── TAB 2: PROVENANCE LINEAGE ── */}
        {activeTab === 'lineage' && (
          <div className="space-y-4">
            <div className="bg-[#141416] p-3 border border-white/[0.04] rounded-[6px]">
              <div className="flex items-center gap-2 text-[11px] font-mono text-[#FFB020] font-medium">
                <GitBranch className="w-3.5 h-3.5" />
                <span>Causal Provenance Derivation</span>
              </div>
              <p className="text-[11px] text-[#A8A8AB] mt-1 leading-relaxed">
                Traces the verifiable empirical inputs, predecessor reasoning events, and descendant decisions connected to this node.
              </p>
            </div>

            {/* Upstream Ancestors / Sources */}
            <div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase mb-2">
                <span className="flex items-center gap-1">
                  <ArrowLeft className="w-3 h-3 text-[#38BDF8]" />
                  Upstream Lineage Sources ({provenanceLineage.upstreamNodes.length})
                </span>
                <span className="text-[9px] text-[#38BDF8]">Origin Inputs</span>
              </div>

              {provenanceLineage.upstreamNodes.length === 0 ? (
                <div className="p-3 bg-[#141416]/60 border border-dashed border-white/[0.08] rounded-[6px] text-center text-[#6B6B6E] font-mono text-[11px]">
                  Terminal Origin Node (Empirical Observation or Root Strategic Goal)
                </div>
              ) : (
                <div className="space-y-2">
                  {provenanceLineage.upstreamNodes.map((src) => {
                    const sColors = NODE_TYPE_COLORS[src.type];
                    return (
                      <div
                        key={src.id}
                        onClick={() => onSelectNode(src)}
                        className="p-2.5 bg-[#141416] hover:bg-white/[0.04] border border-white/[0.04] rounded-[6px] transition-colors cursor-pointer space-y-1.5 group"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 overflow-hidden">
                            <span
                              className="px-1.5 py-0.2 rounded text-[9px] font-mono font-medium uppercase"
                              style={{ backgroundColor: `${sColors.bg}22`, color: sColors.bg }}
                            >
                              {src.type}
                            </span>
                            <span className="text-xs font-medium text-[#F2F1EE] truncate group-hover:text-[#FFB020] transition-colors">
                              {src.label}
                            </span>
                          </div>
                          <ExternalLink className="w-3 h-3 text-[#6B6B6E] group-hover:text-[#F2F1EE] shrink-0" />
                        </div>
                        <p className="text-[11px] text-[#A8A8AB] line-clamp-2">
                          {src.summary}
                        </p>
                        <div className="flex items-center justify-between text-[9px] font-mono text-[#6B6B6E]">
                          <span>Agent: {src.agent_id || 'System'}</span>
                          <span className="text-[#22C55E]">{Math.round(src.confidence * 100)}% Conf</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Current Active Node in Sequence */}
            <div className="p-3 bg-[#FFB020]/10 border border-[#FFB020]/30 rounded-[6px] space-y-1">
              <div className="flex items-center justify-between text-[10px] font-mono text-[#FFB020]">
                <span>● CURRENT FOCUSED MEMORY</span>
                <span>Active Anchor</span>
              </div>
              <div className="text-xs font-semibold text-[#F2F1EE]">{node.label}</div>
              <div className="text-[10px] font-mono text-[#A8A8AB]">
                {node.type.toUpperCase()} • {node.agent_id || 'System'} • Conf: {Math.round(node.confidence * 100)}%
              </div>
            </div>

            {/* Downstream Descendants / Derivations */}
            <div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] uppercase mb-2">
                <span className="flex items-center gap-1">
                  <ArrowRight className="w-3 h-3 text-[#22C55E]" />
                  Downstream Lineage Dependents ({provenanceLineage.downstreamNodes.length})
                </span>
                <span className="text-[9px] text-[#22C55E]">Derived Outputs</span>
              </div>

              {provenanceLineage.downstreamNodes.length === 0 ? (
                <div className="p-3 bg-[#141416]/60 border border-dashed border-white/[0.08] rounded-[6px] text-center text-[#6B6B6E] font-mono text-[11px]">
                  No active downstream child memories yet derived from this node.
                </div>
              ) : (
                <div className="space-y-2">
                  {provenanceLineage.downstreamNodes.map((dst) => {
                    const dColors = NODE_TYPE_COLORS[dst.type];
                    return (
                      <div
                        key={dst.id}
                        onClick={() => onSelectNode(dst)}
                        className="p-2.5 bg-[#141416] hover:bg-white/[0.04] border border-white/[0.04] rounded-[6px] transition-colors cursor-pointer space-y-1.5 group"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 overflow-hidden">
                            <span
                              className="px-1.5 py-0.2 rounded text-[9px] font-mono font-medium uppercase"
                              style={{ backgroundColor: `${dColors.bg}22`, color: dColors.bg }}
                            >
                              {dst.type}
                            </span>
                            <span className="text-xs font-medium text-[#F2F1EE] truncate group-hover:text-[#FFB020] transition-colors">
                              {dst.label}
                            </span>
                          </div>
                          <ExternalLink className="w-3 h-3 text-[#6B6B6E] group-hover:text-[#F2F1EE] shrink-0" />
                        </div>
                        <p className="text-[11px] text-[#A8A8AB] line-clamp-2">
                          {dst.summary}
                        </p>
                        <div className="flex items-center justify-between text-[9px] font-mono text-[#6B6B6E]">
                          <span>Agent: {dst.agent_id || 'System'}</span>
                          <span className="text-[#22C55E]">{Math.round(dst.confidence * 100)}% Conf</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── TAB 3: RELATIONSHIPS (INCOMING & OUTGOING) ── */}
        {activeTab === 'relationships' && (
          <div className="space-y-3">
            {/* Filter / Search within Relations */}
            <div className="space-y-2">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={relationSearch}
                  onChange={(e) => setRelationSearch(e.target.value)}
                  placeholder="Filter relationships or node labels..."
                  className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              {/* Direction Filter Pills */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setRelationTypeFilter('all')}
                  className={`px-2 py-1 rounded text-[10px] font-mono transition-colors cursor-pointer ${
                    relationTypeFilter === 'all'
                      ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold'
                      : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE]'
                  }`}
                >
                  All ({totalConnected})
                </button>
                <button
                  onClick={() => setRelationTypeFilter('incoming')}
                  className={`px-2 py-1 rounded text-[10px] font-mono transition-colors cursor-pointer flex items-center gap-1 ${
                    relationTypeFilter === 'incoming'
                      ? 'bg-[#38BDF8] text-[#0A0A0B] font-semibold'
                      : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE]'
                  }`}
                >
                  <ArrowDownLeft className="w-3 h-3" />
                  <span>Incoming ({incomingLinks.length})</span>
                </button>
                <button
                  onClick={() => setRelationTypeFilter('outgoing')}
                  className={`px-2 py-1 rounded text-[10px] font-mono transition-colors cursor-pointer flex items-center gap-1 ${
                    relationTypeFilter === 'outgoing'
                      ? 'bg-[#34D399] text-[#0A0A0B] font-semibold'
                      : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE]'
                  }`}
                >
                  <ArrowUpRight className="w-3 h-3" />
                  <span>Outgoing ({outgoingLinks.length})</span>
                </button>
              </div>
            </div>

            {/* List of Relationships */}
            <div className="space-y-2">
              {filteredRelations.length === 0 ? (
                <div className="p-4 bg-[#141416] border border-white/[0.04] rounded-[6px] text-center text-[#6B6B6E] font-mono text-[11px]">
                  No matching relationships found.
                </div>
              ) : (
                filteredRelations.map((item) => {
                  const isInc = item.direction === 'incoming';
                  const edgeStyle = EDGE_TYPE_COLORS[item.link.type] || { stroke: '#6B6B6E', label: item.link.type };
                  const other = item.otherNode;
                  if (!other) return null;

                  const otherColors = NODE_TYPE_COLORS[other.type];

                  return (
                    <div
                      key={item.link.id}
                      className="p-3 bg-[#141416] hover:bg-white/[0.04] border border-white/[0.04] rounded-[6px] transition-colors space-y-2"
                    >
                      {/* Edge Verb Header */}
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5">
                          {isInc ? (
                            <span className="flex items-center gap-1 text-[10px] font-mono text-[#38BDF8] bg-[#38BDF8]/10 px-1.5 py-0.5 rounded">
                              <ArrowDownLeft className="w-3 h-3" />
                              INCOMING
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[10px] font-mono text-[#34D399] bg-[#34D399]/10 px-1.5 py-0.5 rounded">
                              <ArrowUpRight className="w-3 h-3" />
                              OUTGOING
                            </span>
                          )}

                          <span
                            className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: `${edgeStyle.stroke}20`,
                              color: edgeStyle.stroke,
                            }}
                          >
                            {item.link.label || edgeStyle.label}
                          </span>
                        </div>

                        <span className="text-[10px] font-mono text-[#6B6B6E]">
                          Weight: {Math.round(item.link.weight * 100)}%
                        </span>
                      </div>

                      {/* Linked Node Target/Source Card */}
                      <button
                        onClick={() => onSelectNode(other)}
                        className="w-full text-left p-2 bg-[#0E0E10] hover:bg-white/[0.04] border border-white/[0.04] rounded-[4px] flex items-center justify-between gap-2 transition-colors cursor-pointer group"
                      >
                        <div className="flex items-center gap-2 overflow-hidden">
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: otherColors.bg }}
                          />
                          <div className="overflow-hidden">
                            <div className="text-xs font-medium text-[#F2F1EE] truncate group-hover:text-[#FFB020] transition-colors">
                              {other.label}
                            </div>
                            <div className="text-[10px] font-mono text-[#6B6B6E] truncate">
                              {other.type.toUpperCase()} • {other.agent_id || 'System'}
                            </div>
                          </div>
                        </div>

                        <ExternalLink className="w-3 h-3 text-[#6B6B6E] group-hover:text-[#F2F1EE] shrink-0" />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* ── TAB 4: RAW DATA & VECTOR EMBEDDING ── */}
        {activeTab === 'raw' && (
          <div className="space-y-3 font-mono">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[#6B6B6E] uppercase">Raw Memory Node Structure</span>
              <button
                onClick={handleCopyJson}
                className="flex items-center gap-1 px-2 py-1 bg-[#141416] hover:bg-white/[0.06] border border-white/[0.08] rounded text-[10px] text-[#FFB020] transition-colors cursor-pointer"
              >
                {copiedJson ? <Check className="w-3 h-3 text-[#22C55E]" /> : <Copy className="w-3 h-3" />}
                <span>{copiedJson ? 'Copied' : 'Copy JSON'}</span>
              </button>
            </div>

            <pre className="p-3 bg-[#0E0E10] border border-white/[0.06] rounded-[6px] text-[10px] text-[#34D399] overflow-x-auto max-h-96 leading-tight">
              {JSON.stringify(node, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Action Footer */}
      <div className="p-3 border-t border-white/[0.08] bg-[#0E0E10] flex items-center gap-2 shrink-0">
        <button
          onClick={() => onReinforce(node.id)}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-[#FFB020] hover:bg-[#FFB020]/90 text-[#0A0A0B] font-mono font-medium text-xs rounded-[6px] transition-colors cursor-pointer"
        >
          <Flame className="w-3.5 h-3.5" />
          <span>Reinforce Memory (+Weight)</span>
        </button>

        {onStartPathFromNode && (
          <button
            onClick={() => onStartPathFromNode(node)}
            className="flex items-center justify-center p-2 bg-[#141416] hover:bg-[#38BDF8]/15 text-[#6B6B6E] hover:text-[#38BDF8] border border-white/[0.08] hover:border-[#38BDF8]/40 rounded-[6px] transition-colors cursor-pointer"
            title="Find Shortest Path From This Node"
          >
            <Route className="w-4 h-4 text-[#38BDF8]" />
          </button>
        )}

        <button
          onClick={() => onFocusNodeNeighborhood(node.id)}
          className="flex items-center justify-center p-2 bg-[#141416] hover:bg-white/[0.06] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded-[6px] transition-colors cursor-pointer"
          title="Isolate 1-Hop Neighborhood"
        >
          <Compass className="w-4 h-4 text-[#FFB020]" />
        </button>
      </div>
    </aside>
  );
}
