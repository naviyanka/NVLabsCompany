import { useState } from 'react';
import {
  Route,
  Sparkles,
  X,
  Compass,
  AlertCircle,
  Eye,
  CheckCircle2,
} from 'lucide-react';
import { MemoryGraphNode } from '@/types/memoryGraph';
import { ShortestPathResult } from '@/lib/graphPathFinder';
import { NODE_TYPE_COLORS, EDGE_TYPE_COLORS } from '@/lib/memoryGraphAdapter';

interface ShortestPathPanelProps {
  allNodes: MemoryGraphNode[];
  sourceNodeId: string;
  targetNodeId: string;
  onSelectSourceNodeId: (id: string) => void;
  onSelectTargetNodeId: (id: string) => void;
  isDirected: boolean;
  onToggleDirected: () => void;
  pathResult: ShortestPathResult | null;
  onClear: () => void;
  onClose: () => void;
  onSelectNode: (node: MemoryGraphNode) => void;
}

export function ShortestPathPanel({
  allNodes,
  sourceNodeId,
  targetNodeId,
  onSelectSourceNodeId,
  onSelectTargetNodeId,
  isDirected,
  onToggleDirected,
  pathResult,
  onClear,
  onClose,
  onSelectNode,
}: ShortestPathPanelProps) {
  const [sourceSearch, setSourceSearch] = useState('');
  const [targetSearch, setTargetSearch] = useState('');

  const pathSourceNode = allNodes.find((n) => n.id === sourceNodeId) || null;
  const pathTargetNode = allNodes.find((n) => n.id === targetNodeId) || null;

  const [isSelectingSource, setIsSelectingSource] = useState(false);
  const [isSelectingTarget, setIsSelectingTarget] = useState(false);

  const filteredSourceList = allNodes
    .filter(
      (n) =>
        !sourceSearch.trim() ||
        n.label.toLowerCase().includes(sourceSearch.toLowerCase()) ||
        n.type.toLowerCase().includes(sourceSearch.toLowerCase())
    )
    .slice(0, 8);

  const filteredTargetList = allNodes
    .filter(
      (n) =>
        !targetSearch.trim() ||
        n.label.toLowerCase().includes(targetSearch.toLowerCase()) ||
        n.type.toLowerCase().includes(targetSearch.toLowerCase())
    )
    .slice(0, 8);

  const hasBothNodes = Boolean(pathSourceNode && pathTargetNode);

  return (
    <div
      id="shortest-path-panel"
      className="w-80 sm:w-96 max-h-[80vh] flex flex-col bg-[#101012]/95 backdrop-blur-xl border border-white/[0.14] rounded-[10px] shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150 text-xs font-mono select-none"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 bg-[#141416]/90 border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded bg-[#FFB020]/15 text-[#FFB020] border border-[#FFB020]/30">
            <Route className="w-3.5 h-3.5" />
          </div>
          <div>
            <h2 className="font-semibold text-[#F2F1EE] text-xs">
              Dependency Path Finder
            </h2>
            <p className="text-[10px] text-[#6B6B6E]">
              Shortest connection & indirect causal chains
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {hasBothNodes && (
            <button
              onClick={onClear}
              className="px-2 py-0.5 text-[10px] text-[#A8A8AB] hover:text-[#F2F1EE] bg-white/[0.04] hover:bg-white/[0.08] rounded border border-white/[0.06] cursor-pointer"
              title="Reset selected path endpoints"
            >
              Reset
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded transition-colors cursor-pointer"
            title="Close Path Finder"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Selectors Area */}
      <div className="p-3 space-y-2.5 border-b border-white/[0.06] bg-[#0E0E10]/80">
        {/* Traversal Direction Toggle */}
        <div className="flex items-center justify-between pb-1 text-[10px] border-b border-white/[0.04]">
          <span className="text-[#6B6B6E]">TRAVERSAL MODE:</span>
          <button
            onClick={onToggleDirected}
            className={`px-2 py-0.5 rounded border text-[10px] transition-colors cursor-pointer ${
              isDirected
                ? 'bg-[#38BDF8]/15 border-[#38BDF8]/40 text-[#38BDF8]'
                : 'bg-[#FFB020]/15 border-[#FFB020]/40 text-[#FFB020]'
            }`}
            title="Toggle Directed (Causal flow only) vs Bidirectional traversal"
          >
            {isDirected ? 'Directed (Strict Flow →)' : 'Bidirectional (Any Link ↔)'}
          </button>
        </div>

        {/* Node A (Source) */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold text-[#38BDF8] flex items-center gap-1">
              <span>●</span> ORIGIN NODE (A)
            </span>
            {pathSourceNode && (
              <button
                onClick={() => onSelectSourceNodeId('')}
                className="text-[10px] text-[#6B6B6E] hover:text-red-400 cursor-pointer"
              >
                Clear
              </button>
            )}
          </div>

          {pathSourceNode ? (
            <div className="flex items-center justify-between p-2 rounded-[6px] bg-[#141416] border border-[#38BDF8]/40">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    backgroundColor: NODE_TYPE_COLORS[pathSourceNode.type]?.bg || '#38BDF8',
                  }}
                />
                <span className="text-[#F2F1EE] font-medium truncate">
                  {pathSourceNode.label}
                </span>
                <span className="text-[9px] px-1 py-0.2 rounded bg-white/[0.06] text-[#A8A8AB] uppercase">
                  {pathSourceNode.type}
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <button
                onClick={() => {
                  setIsSelectingSource(true);
                  setIsSelectingTarget(false);
                }}
                className={`w-full py-2 px-2.5 rounded-[6px] text-left border transition-all flex items-center justify-between cursor-pointer ${
                  isSelectingSource
                    ? 'bg-[#38BDF8]/15 border-[#38BDF8] text-[#38BDF8] shadow-sm animate-pulse'
                    : 'bg-[#141416] border-dashed border-white/[0.15] text-[#A8A8AB] hover:border-[#38BDF8]/60 hover:text-[#F2F1EE]'
                }`}
              >
                <span>
                  {isSelectingSource ? 'Click any node on canvas or pick below...' : 'Choose or click Origin Node'}
                </span>
                <Compass className="w-3.5 h-3.5" />
              </button>

              {/* Quick source search dropdown if choosing */}
              {isSelectingSource && (
                <div className="mt-1 p-2 bg-[#101012] border border-white/[0.1] rounded-[6px] space-y-1">
                  <input
                    type="text"
                    placeholder="Search node..."
                    value={sourceSearch}
                    onChange={(e) => setSourceSearch(e.target.value)}
                    className="w-full bg-[#141416] border border-white/[0.08] px-2 py-1 rounded text-[11px] text-[#F2F1EE] focus:outline-none focus:border-[#38BDF8]"
                    autoFocus
                  />
                  <div className="max-h-28 overflow-y-auto space-y-0.5 pt-1">
                    {filteredSourceList.map((n) => (
                      <button
                        key={n.id}
                        onClick={() => {
                          onSelectSourceNodeId(n.id);
                          setIsSelectingSource(false);
                        }}
                        className="w-full text-left px-1.5 py-1 rounded hover:bg-white/[0.06] flex items-center justify-between text-[10px] text-[#F2F1EE] cursor-pointer"
                      >
                        <span className="truncate">{n.label}</span>
                        <span className="text-[#6B6B6E]">{n.type}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Node B (Target) */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold text-[#FFB020] flex items-center gap-1">
              <span>●</span> DESTINATION NODE (B)
            </span>
            {pathTargetNode && (
              <button
                onClick={() => onSelectTargetNodeId('')}
                className="text-[10px] text-[#6B6B6E] hover:text-red-400 cursor-pointer"
              >
                Clear
              </button>
            )}
          </div>

          {pathTargetNode ? (
            <div className="flex items-center justify-between p-2 rounded-[6px] bg-[#141416] border border-[#FFB020]/40">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{
                    backgroundColor: NODE_TYPE_COLORS[pathTargetNode.type]?.bg || '#FFB020',
                  }}
                />
                <span className="text-[#F2F1EE] font-medium truncate">
                  {pathTargetNode.label}
                </span>
                <span className="text-[9px] px-1 py-0.2 rounded bg-white/[0.06] text-[#A8A8AB] uppercase">
                  {pathTargetNode.type}
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <button
                onClick={() => {
                  setIsSelectingTarget(true);
                  setIsSelectingSource(false);
                }}
                className={`w-full py-2 px-2.5 rounded-[6px] text-left border transition-all flex items-center justify-between cursor-pointer ${
                  isSelectingTarget
                    ? 'bg-[#FFB020]/15 border-[#FFB020] text-[#FFB020] shadow-sm animate-pulse'
                    : 'bg-[#141416] border-dashed border-white/[0.15] text-[#A8A8AB] hover:border-[#FFB020]/60 hover:text-[#F2F1EE]'
                }`}
              >
                <span>
                  {isSelectingTarget ? 'Click any node on canvas or pick below...' : 'Choose or click Destination Node'}
                </span>
                <Compass className="w-3.5 h-3.5" />
              </button>

              {/* Quick target search dropdown */}
              {isSelectingTarget && (
                <div className="mt-1 p-2 bg-[#101012] border border-white/[0.1] rounded-[6px] space-y-1">
                  <input
                    type="text"
                    placeholder="Search node..."
                    value={targetSearch}
                    onChange={(e) => setTargetSearch(e.target.value)}
                    className="w-full bg-[#141416] border border-white/[0.08] px-2 py-1 rounded text-[11px] text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                    autoFocus
                  />
                  <div className="max-h-28 overflow-y-auto space-y-0.5 pt-1">
                    {filteredTargetList.map((n) => (
                      <button
                        key={n.id}
                        onClick={() => {
                          onSelectTargetNodeId(n.id);
                          setIsSelectingTarget(false);
                        }}
                        className="w-full text-left px-1.5 py-1 rounded hover:bg-white/[0.06] flex items-center justify-between text-[10px] text-[#F2F1EE] cursor-pointer"
                      >
                        <span className="truncate">{n.label}</span>
                        <span className="text-[#6B6B6E]">{n.type}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Path Results Breakdown */}
      <div className="p-3 flex-1 overflow-y-auto max-h-[calc(80vh-14rem)] space-y-3">
        {!hasBothNodes ? (
          <div className="p-4 bg-[#141416]/50 border border-white/[0.06] rounded-[6px] text-center space-y-2">
            <Sparkles className="w-6 h-6 text-[#FFB020]/60 mx-auto" />
            <p className="text-[#A8A8AB] text-[11px] leading-relaxed">
              Select any two nodes to compute the shortest dependency bridge. Highlighted links and glowing pulse paths reveal hidden multi-hop interactions.
            </p>
          </div>
        ) : pathResult?.found ? (
          <div className="space-y-2.5">
            {/* Metric Summary */}
            <div className="flex items-center justify-between p-2 bg-[#141416] border border-[#FFB020]/30 rounded-[6px]">
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-[#34D399]" />
                <span className="font-semibold text-[#F2F1EE]">Path Discovered</span>
              </div>
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-[#FFB020] font-bold">
                  {pathResult.totalHops} {pathResult.totalHops === 1 ? 'Hop' : 'Hops'}
                </span>
                <span className="text-[#6B6B6E]">|</span>
                <span className="text-[#38BDF8] font-bold">
                  {pathResult.nodes.length} Nodes
                </span>
              </div>
            </div>

            {/* Stepped Sequence Lineage */}
            <div className="space-y-1.5 pt-1">
              <div className="text-[10px] text-[#6B6B6E] font-medium flex items-center justify-between px-1">
                <span>CHAIN SEQUENCE</span>
                <span>RELATION TYPE</span>
              </div>

              <div className="relative pl-3 border-l-2 border-[#FFB020]/40 space-y-2">
                {pathResult.steps.map((step, idx) => {
                  const nodeColor =
                    NODE_TYPE_COLORS[step.node.type]?.bg || '#FFB020';
                  const isOrigin = idx === 0;
                  const isDestination = idx === pathResult.steps.length - 1;

                  return (
                    <div key={`${step.node.id}-${idx}`} className="relative group">
                      {/* Step Indicator Dot */}
                      <span
                        className={`absolute -left-[19px] top-1.5 w-3 h-3 rounded-full border-2 border-[#101012] ${
                          isOrigin
                            ? 'bg-[#38BDF8]'
                            : isDestination
                            ? 'bg-[#FFB020]'
                            : 'bg-white/60'
                        }`}
                      />

                      {/* Link Badge if connected to previous */}
                      {step.viaLink && (
                        <div className="mb-1 -mt-1 flex items-center gap-1 text-[9px] text-[#6B6B6E]">
                          <span
                            className="px-1.5 py-0.2 rounded border font-mono"
                            style={{
                              borderColor: `${
                                EDGE_TYPE_COLORS[step.viaLink.type]?.stroke ||
                                '#FFB020'
                              }60`,
                              color:
                                EDGE_TYPE_COLORS[step.viaLink.type]?.stroke ||
                                '#FFB020',
                              backgroundColor: `${
                                EDGE_TYPE_COLORS[step.viaLink.type]?.stroke ||
                                '#FFB020'
                              }15`,
                            }}
                          >
                            {step.viaLink.type.replace('_', ' ')}
                          </span>
                          <span>
                            {step.direction === 'outgoing' ? '→' : '←'}
                          </span>
                        </div>
                      )}

                      {/* Node Card */}
                      <div
                        onClick={() => onSelectNode(step.node)}
                        className="p-2 rounded-[6px] bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/50 hover:bg-[#18181B] transition-all cursor-pointer"
                      >
                        <div className="flex items-center justify-between gap-1">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span
                              className="w-1.5 h-1.5 rounded-full shrink-0"
                              style={{ backgroundColor: nodeColor }}
                            />
                            <span className="font-semibold text-[#F2F1EE] text-[11px] truncate">
                              {step.node.label}
                            </span>
                          </div>
                          <span className="text-[9px] text-[#6B6B6E] uppercase shrink-0">
                            {step.node.type}
                          </span>
                        </div>

                        {step.node.summary && (
                          <p className="text-[10px] text-[#A8A8AB] line-clamp-1 mt-0.5">
                            {step.node.summary}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          /* Disconnected / No Path */
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-[6px] space-y-1.5 text-center">
            <AlertCircle className="w-5 h-5 text-red-400 mx-auto" />
            <div className="font-semibold text-red-300 text-[11px]">
              No Direct or Indirect Path
            </div>
            <p className="text-[10px] text-red-200/70 leading-relaxed">
              These two nodes belong to disconnected topological subgraphs with 0 traversable relationships under active filters.
            </p>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="p-2 bg-[#0E0E10] border-t border-white/[0.06] flex items-center justify-between text-[10px] text-[#6B6B6E]">
        <span>Dijkstra Shortest Chain</span>
        {hasBothNodes && (
          <button
            onClick={() => {
              const el = document.getElementById('memory-graph-canvas-container');
              el?.dispatchEvent(new CustomEvent('fit-view'));
            }}
            className="text-[#FFB020] hover:underline cursor-pointer flex items-center gap-1"
          >
            <Eye className="w-3 h-3" />
            <span>Focus Canvas</span>
          </button>
        )}
      </div>
    </div>
  );
}
