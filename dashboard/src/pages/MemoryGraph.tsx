import { useState, useEffect, useMemo } from 'react';
import {
  memoryGraphStore,
  MEMORY_CLUSTERS,
} from '@/lib/memoryGraphAdapter';
import {
  MemoryGraphData,
  MemoryGraphNode,
  LayoutMode,
  GraphFilterState,
} from '@/types/memoryGraph';
import { MemoryGraphCanvas } from '@/components/graph/MemoryGraphCanvas';
import { GraphFilterBar } from '@/components/graph/GraphFilterBar';
import { GraphControls } from '@/components/graph/GraphControls';
import { MemoryNodeSidebarPanel } from '@/components/graph/MemoryNodeSidebarPanel';
import { RelationshipLegend } from '@/components/graph/RelationshipLegend';
import { ShortestPathPanel } from '@/components/graph/ShortestPathPanel';
import { AddMemoryNodeModal } from '@/components/graph/AddMemoryNodeModal';
import { ContradictionsModal } from '@/components/graph/ContradictionsModal';
import { findShortestPath, ShortestPathResult } from '@/lib/graphPathFinder';
import {
  Brain,
  AlertTriangle,
  Plus,
  Trash2,
  Sparkles,
  BarChart3,
  X,
  Search,
  Route,
} from 'lucide-react';

export function MemoryGraph() {
  const [graphData, setGraphData] = useState<MemoryGraphData>(() =>
    memoryGraphStore.getData()
  );
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force');
  const [selectedNode, setSelectedNode] = useState<MemoryGraphNode | null>(null);

  // Visual options & canvas expansion
  const [showClusters, setShowClusters] = useState(true);
  const [showMinimap, setShowMinimap] = useState(true);
  const [animateParticles, setAnimateParticles] = useState(true);
  const [physicsStrength, setPhysicsStrength] = useState(1.0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Overlay vs Docked Sidebar Mode (overlay by default to preserve 100% canvas footprint)
  const [sidebarMode, setSidebarMode] = useState<'overlay' | 'docked'>('overlay');

  // Floating Filter, Search & Path Drawer state
  const [showFilterDrawer, setShowFilterDrawer] = useState(false);
  const [showMetricsSummary, setShowMetricsSummary] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  const [showPathFinder, setShowPathFinder] = useState(false);

  // Shortest Path Finder state
  const [pathSourceNodeId, setPathSourceNodeId] = useState<string>('');
  const [pathTargetNodeId, setPathTargetNodeId] = useState<string>('');
  const [isPathDirected, setIsPathDirected] = useState<boolean>(false);
  const [shortestPathResult, setShortestPathResult] = useState<ShortestPathResult | null>(null);

  // Modals
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isContradictionsModalOpen, setIsContradictionsModalOpen] = useState(false);

  // Filter state
  const [filterState, setFilterState] = useState<GraphFilterState>({
    searchQuery: '',
    selectedTypes: new Set(),
    selectedClusters: new Set(),
    selectedAgent: 'all',
    minConfidence: 0.5,
    minImportance: 0.1,
    showOnlyContradictions: false,
    timeDecayThreshold: 0,
    focusNodeId: null,
    hopDistance: 1,
  });

  // Subscribe to store updates
  useEffect(() => {
    const unsubscribe = memoryGraphStore.subscribe(() => {
      setGraphData({ ...memoryGraphStore.getData() });
    });
    return unsubscribe;
  }, []);

  // Automatic Shortest Path calculation whenever endpoints or directed mode change
  useEffect(() => {
    if (!pathSourceNodeId || !pathTargetNodeId) {
      setShortestPathResult(null);
      return;
    }

    if (pathSourceNodeId === pathTargetNodeId) {
      setShortestPathResult(null);
      return;
    }

    const result = findShortestPath(
      graphData.nodes,
      graphData.links,
      pathSourceNodeId,
      pathTargetNodeId,
      isPathDirected
    );
    setShortestPathResult(result);
  }, [graphData.nodes, graphData.links, pathSourceNodeId, pathTargetNodeId, isPathDirected]);

  const handleStartPathFromNode = (node: MemoryGraphNode) => {
    setPathSourceNodeId(node.id);
    setShowPathFinder(true);
  };

  const handleClearShortestPath = () => {
    setPathSourceNodeId('');
    setPathTargetNodeId('');
    setShortestPathResult(null);
  };

  const handleResetFilters = () => {
    setFilterState({
      searchQuery: '',
      selectedTypes: new Set(),
      selectedClusters: new Set(),
      selectedAgent: 'all',
      minConfidence: 0.5,
      minImportance: 0.1,
      showOnlyContradictions: false,
      timeDecayThreshold: 0,
      focusNodeId: null,
      hopDistance: 1,
    });
  };

  const handleReinforce = (nodeId: string) => {
    memoryGraphStore.reinforceNode(nodeId);
    if (selectedNode && selectedNode.id === nodeId) {
      const updated = memoryGraphStore
        .getData()
        .nodes.find((n) => n.id === nodeId);
      if (updated) setSelectedNode({ ...updated });
    }
  };

  const handleResolveContradiction = (
    nodeId: string,
    action: 'prune' | 'override' | 'archive'
  ) => {
    memoryGraphStore.resolveContradiction(nodeId, action);
    setSelectedNode(null);
  };

  const handlePruneDecayed = () => {
    const prunedCount = memoryGraphStore.pruneDecayedNodes(0.5);
    alert(`Pruned ${prunedCount} low-retention decayed memories from vector graph.`);
  };

  const handleExportJSON = () => {
    const dataStr =
      'data:text/json;charset=utf-8,' +
      encodeURIComponent(JSON.stringify(graphData, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `nexus-memory-graph-${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const handleFocusNodeNeighborhood = (nodeId: string) => {
    setFilterState((prev) => ({
      ...prev,
      focusNodeId: prev.focusNodeId === nodeId ? null : nodeId,
      hopDistance: 1,
    }));
  };

  const handleFilterByTag = (tag: string) => {
    setFilterState((prev) => ({
      ...prev,
      searchQuery: tag,
    }));
  };

  const contradictionNodes = useMemo(() => {
    return graphData.nodes.filter((n) => n.type === 'contradiction');
  }, [graphData.nodes]);

  // Compute active filter count
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (filterState.searchQuery.trim()) count++;
    if (filterState.selectedTypes.size > 0) count += filterState.selectedTypes.size;
    if (filterState.selectedClusters.size > 0) count += filterState.selectedClusters.size;
    if (filterState.selectedAgent !== 'all') count++;
    if (filterState.showOnlyContradictions) count++;
    if (filterState.minConfidence > 0.5) count++;
    if (filterState.timeDecayThreshold > 0) count++;
    if (filterState.focusNodeId) count++;
    return count;
  }, [filterState]);

  return (
    <div
      className={`flex flex-col w-full h-full min-h-0 relative select-none ${
        isFullscreen
          ? 'fixed inset-0 z-50 bg-[#0A0A0B] p-2'
          : 'flex-1 h-full min-h-[640px]'
      }`}
    >
      {/* Top Streamlined Global Header Strip */}
      <header className="shrink-0 flex items-center justify-between gap-3 px-3 py-1.5 bg-[#101012] border border-white/[0.08] rounded-t-[8px] z-20">
        {/* Left: Branding & Core Stats Summary */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-[#FFB020] shrink-0" />
            <h1 className="text-xs sm:text-sm font-display font-medium text-[#F2F1EE] tracking-tight truncate">
              Agent Memory Graph
            </h1>
            <span className="hidden md:inline px-1.5 py-0.2 rounded bg-[#FFB020]/15 text-[#FFB020] text-[9px] font-mono border border-[#FFB020]/30 font-medium">
              HNSW TOPOLOGY
            </span>
          </div>

          {/* Quick HUD Metrics */}
          <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-white/[0.08] text-[11px] font-mono text-[#6B6B6E]">
            <span className="text-[#38BDF8]">{graphData.metrics.total_nodes} Nodes</span>
            <span>•</span>
            <span className="text-[#34D399]">{graphData.metrics.total_links} Links</span>
            <span>•</span>
            <span className="text-[#FFB020]">{Math.round(graphData.metrics.avg_confidence * 100)}% Conf</span>
            <span>•</span>
            <span className="hidden xl:inline text-[#A8A8AB]">{graphData.metrics.memory_recall_rate}% Recall</span>
          </div>
        </div>

        {/* Right: Quick Action Buttons & Stats Modal Toggle */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Quick Contradiction Warning */}
          {graphData.metrics.contradictions_count > 0 && (
            <button
              onClick={() => setIsContradictionsModalOpen(true)}
              className="px-2 py-1 bg-red-500/20 text-red-300 border border-red-500/30 hover:bg-red-500/30 rounded text-[11px] font-mono flex items-center gap-1.5 cursor-pointer transition-colors"
            >
              <AlertTriangle className="w-3 h-3 text-red-400 animate-pulse" />
              <span>{graphData.metrics.contradictions_count} Conflicts</span>
            </button>
          )}

          {/* Metrics HUD Toggle */}
          <button
            onClick={() => setShowMetricsSummary((prev) => !prev)}
            className={`px-2 py-1 rounded text-[11px] font-mono flex items-center gap-1 border transition-colors cursor-pointer ${
              showMetricsSummary
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold border-[#FFB020]'
                : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
            }`}
            title="Toggle Detailed Metrics Summary"
          >
            <BarChart3 className="w-3 h-3" />
            <span className="hidden md:inline">Telemetry HUD</span>
          </button>

          {/* Prune Decayed */}
          <button
            onClick={handlePruneDecayed}
            className="hidden lg:flex items-center gap-1 px-2 py-1 bg-[#141416] hover:bg-white/[0.04] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded text-[11px] font-mono transition-colors cursor-pointer"
            title="Prune decayed memories with low retention"
          >
            <Trash2 className="w-3 h-3" />
            <span>Prune</span>
          </button>

          {/* Inject Memory Node */}
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="flex items-center gap-1 px-2.5 py-1 bg-[#FFB020] hover:bg-[#FFB020]/90 text-[#0A0A0B] font-semibold rounded text-[11px] font-mono transition-colors cursor-pointer shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Inject Node</span>
          </button>
        </div>
      </header>

      {/* Floating Detailed Metrics HUD (Expandable Popover) */}
      {showMetricsSummary && (
        <div className="absolute top-11 left-3 right-3 sm:left-auto sm:right-3 sm:w-[580px] z-40 bg-[#101012]/95 backdrop-blur-xl border border-white/[0.14] rounded-[10px] p-3.5 shadow-2xl space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-white/[0.08]">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#FFB020]" />
              <span className="text-xs font-mono font-medium text-[#F2F1EE]">
                Knowledge Graph Vector Metrics & Reasoning Telemetry
              </span>
            </div>
            <button
              onClick={() => setShowMetricsSummary(false)}
              className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] rounded cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div className="p-2 bg-[#141416] border border-white/[0.06] rounded-[6px]">
              <div className="text-[#6B6B6E] text-[10px]">TOTAL NODES</div>
              <div className="text-base font-bold text-[#F2F1EE] mt-0.5">
                {graphData.metrics.total_nodes}
              </div>
              <div className="text-[10px] text-[#38BDF8] mt-0.5">
                {graphData.metrics.total_links} Links
              </div>
            </div>

            <div className="p-2 bg-[#141416] border border-white/[0.06] rounded-[6px]">
              <div className="text-[#6B6B6E] text-[10px]">HNSW INDEX</div>
              <div className="text-base font-bold text-[#F2F1EE] mt-0.5">
                {graphData.metrics.hnsw_index_size_kb} KB
              </div>
              <div className="text-[10px] text-[#34D399] mt-0.5">
                {graphData.metrics.memory_recall_rate}% Recall
              </div>
            </div>

            <div className="p-2 bg-[#141416] border border-white/[0.06] rounded-[6px]">
              <div className="text-[#6B6B6E] text-[10px]">AVG CONFIDENCE</div>
              <div className="text-base font-bold text-[#FFB020] mt-0.5">
                {Math.round(graphData.metrics.avg_confidence * 100)}%
              </div>
              <div className="text-[10px] text-[#6B6B6E] mt-0.5">
                Imp: {(graphData.metrics.avg_importance * 100).toFixed(0)}%
              </div>
            </div>

            <div className="p-2 bg-[#141416] border border-white/[0.06] rounded-[6px]">
              <div className="text-[#6B6B6E] text-[10px]">CONTRADICTIONS</div>
              <div
                className={`text-base font-bold mt-0.5 ${
                  graphData.metrics.contradictions_count > 0
                    ? 'text-red-400'
                    : 'text-[#34D399]'
                }`}
              >
                {graphData.metrics.contradictions_count}
              </div>
              <div className="text-[10px] text-[#6B6B6E] mt-0.5">
                {graphData.metrics.contradictions_count > 0 ? 'Active Anomaly' : 'Consistent'}
              </div>
            </div>
          </div>

          <div className="text-[11px] font-mono text-[#6B6B6E] pt-1 flex items-center justify-between border-t border-white/[0.04]">
            <span>Active Communities: {MEMORY_CLUSTERS.length} domains</span>
            <button
              onClick={handlePruneDecayed}
              className="text-[#FFB020] hover:underline cursor-pointer flex items-center gap-1"
            >
              <Trash2 className="w-3 h-3" />
              <span>Prune Inactive Memories</span>
            </button>
          </div>
        </div>
      )}

      {/* Main Full-Footprint Graph Canvas & Layer Container (90%+ Screen Area) */}
      <div className="flex-1 min-h-0 relative flex flex-row overflow-hidden bg-[#0A0A0B] border-x border-b border-white/[0.08] rounded-b-[8px]">
        {/* Full Interactive Canvas Filling 100% of the Container */}
        <div className="flex-1 h-full min-h-0 relative overflow-hidden">
          <MemoryGraphCanvas
            nodes={graphData.nodes}
            links={graphData.links}
            layoutMode={layoutMode}
            filterState={filterState}
            selectedNodeId={selectedNode ? selectedNode.id : null}
            onSelectNode={setSelectedNode}
            showClusters={showClusters}
            showMinimap={showMinimap}
            animateParticles={animateParticles}
            physicsStrength={physicsStrength}
            shortestPath={shortestPathResult}
            pathSourceNodeId={pathSourceNodeId}
            pathTargetNodeId={pathTargetNodeId}
          />

          {/* Top Floating Controls Bar (Overlays Canvas seamlessly) */}
          <div className="absolute top-2.5 left-2.5 right-2.5 z-20 pointer-events-auto">
            <GraphControls
              layoutMode={layoutMode}
              onLayoutModeChange={setLayoutMode}
              showClusters={showClusters}
              onToggleClusters={() => setShowClusters(!showClusters)}
              showMinimap={showMinimap}
              onToggleMinimap={() => setShowMinimap(!showMinimap)}
              animateParticles={animateParticles}
              onToggleParticles={() => setAnimateParticles(!animateParticles)}
              physicsStrength={physicsStrength}
              onPhysicsStrengthChange={setPhysicsStrength}
              onFitView={() => {
                const el = document.getElementById('memory-graph-canvas-container');
                el?.dispatchEvent(new CustomEvent('fit-view'));
              }}
              onExportJSON={handleExportJSON}
              isFullscreen={isFullscreen}
              onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
              showFilterDrawer={showFilterDrawer}
              onToggleFilterDrawer={() => setShowFilterDrawer((prev) => !prev)}
              activeFilterCount={activeFilterCount}
              sidebarDocked={sidebarMode === 'docked'}
              onToggleSidebarDocked={() =>
                setSidebarMode((prev) => (prev === 'docked' ? 'overlay' : 'docked'))
              }
              hasSelectedNode={Boolean(selectedNode)}
              showLegend={showLegend}
              onToggleLegend={() => setShowLegend((prev) => !prev)}
              showPathFinder={showPathFinder}
              onTogglePathFinder={() => setShowPathFinder((prev) => !prev)}
              hasActivePath={Boolean(shortestPathResult?.found)}
            />
          </div>

          {/* Floating Shortest Path Finder Panel Overlay */}
          {showPathFinder && (
            <div className="absolute top-14 left-2.5 max-w-lg w-[calc(100%-1.25rem)] sm:w-[480px] z-30 shadow-2xl rounded-[8px] overflow-hidden border border-white/[0.14] bg-[#101012]/95 backdrop-blur-xl animate-in fade-in zoom-in-95 duration-150 pointer-events-auto">
              <ShortestPathPanel
                allNodes={graphData.nodes}
                sourceNodeId={pathSourceNodeId}
                targetNodeId={pathTargetNodeId}
                onSelectSourceNodeId={setPathSourceNodeId}
                onSelectTargetNodeId={setPathTargetNodeId}
                isDirected={isPathDirected}
                onToggleDirected={() => setIsPathDirected((prev) => !prev)}
                pathResult={shortestPathResult}
                onClear={handleClearShortestPath}
                onClose={() => setShowPathFinder(false)}
                onSelectNode={(node) => setSelectedNode(node)}
              />
            </div>
          )}

          {/* Floating Search & Filter Bar Drawer (Glass Dropdown overlay) */}
          {showFilterDrawer && (
            <div className="absolute top-14 left-2.5 max-w-xl w-[calc(100%-1.25rem)] sm:w-[560px] z-30 shadow-2xl rounded-[8px] overflow-hidden border border-white/[0.14] bg-[#101012]/95 backdrop-blur-xl animate-in fade-in zoom-in-95 duration-150">
              <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.08] bg-[#0E0E10]">
                <div className="flex items-center gap-2 text-xs font-mono text-[#F2F1EE]">
                  <Search className="w-3.5 h-3.5 text-[#FFB020]" />
                  <span>Graph Filters & Query Refinement</span>
                </div>
                <button
                  onClick={() => setShowFilterDrawer(false)}
                  className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] rounded cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="p-3 max-h-[70vh] overflow-y-auto">
                <GraphFilterBar
                  filterState={filterState}
                  onFilterChange={setFilterState}
                  onResetFilters={handleResetFilters}
                />
              </div>
            </div>
          )}

          {/* Active Shortest Path Info Strip when Panel is Closed */}
          {!showPathFinder && shortestPathResult?.found && (
            <div className="absolute top-16 left-3 z-20 px-3 py-1.5 bg-[#101012]/90 border border-[#38BDF8]/40 rounded-[6px] backdrop-blur-md flex items-center gap-2 text-xs font-mono text-[#38BDF8] shadow-xl">
              <Route className="w-3.5 h-3.5 text-[#38BDF8]" />
              <span>
                Path Active: {shortestPathResult.totalHops} hop{shortestPathResult.totalHops !== 1 ? 's' : ''} ({shortestPathResult.nodes.length} nodes)
              </span>
              <button
                onClick={() => setShowPathFinder(true)}
                className="px-1.5 py-0.5 bg-[#38BDF8]/20 hover:bg-[#38BDF8]/30 text-[#38BDF8] rounded text-[10px] cursor-pointer"
              >
                Inspect
              </button>
              <button
                onClick={handleClearShortestPath}
                className="px-1.5 py-0.5 bg-white/[0.06] hover:bg-white/[0.12] text-[#A8A8AB] rounded text-[10px] cursor-pointer"
              >
                Clear
              </button>
            </div>
          )}

          {/* Neighborhood Focus Active Badge */}
          {filterState.focusNodeId && (
            <div className="absolute top-16 right-3 z-20 px-3 py-1.5 bg-[#FFB020]/20 border border-[#FFB020]/40 rounded-[6px] backdrop-blur-md flex items-center gap-2 text-xs font-mono text-[#FFB020] shadow-lg">
              <span>Neighborhood Isolation: Active</span>
              <button
                onClick={() =>
                  setFilterState((prev) => ({ ...prev, focusNodeId: null }))
                }
                className="px-1.5 py-0.5 bg-[#FFB020] text-[#0A0A0B] rounded font-bold hover:bg-[#FFB020]/90 cursor-pointer text-[10px]"
              >
                Clear
              </button>
            </div>
          )}

          {/* Collapsible Relationship Legend (Bottom-Left Canvas Overlay) */}
          <div className="absolute bottom-3 left-3 z-30 flex items-center gap-2">
            <RelationshipLegend
              isOpen={showLegend}
              onToggle={() => setShowLegend((prev) => !prev)}
            />

            {/* Quick Helper Tip Badge when Legend is collapsed and no node selected */}
            {!showLegend && !selectedNode && (
              <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 bg-[#101012]/80 backdrop-blur-md border border-white/[0.08] rounded-[6px] text-[11px] font-mono text-[#6B6B6E] pointer-events-none">
                <span className="w-1.5 h-1.5 rounded-full bg-[#FFB020] animate-pulse" />
                <span>Click node for inspector</span>
              </div>
            )}
          </div>

          {/* Floating Sidebar Overlay Mode */}
          {selectedNode && sidebarMode === 'overlay' && (
            <div className="absolute top-14 bottom-3 right-3 z-30 max-h-[calc(100%-4rem)] flex flex-col pointer-events-auto">
              <MemoryNodeSidebarPanel
                node={selectedNode}
                links={graphData.links}
                allNodes={graphData.nodes}
                onClose={() => setSelectedNode(null)}
                onSelectNode={setSelectedNode}
                onReinforce={handleReinforce}
                onResolveContradiction={handleResolveContradiction}
                onFocusNodeNeighborhood={handleFocusNodeNeighborhood}
                onFilterByTag={handleFilterByTag}
                onStartPathFromNode={handleStartPathFromNode}
                displayMode="overlay"
                onToggleDisplayMode={() => setSidebarMode('docked')}
              />
            </div>
          )}
        </div>

        {/* Docked Sidebar Mode (Side-by-side if user toggles docked mode) */}
        {selectedNode && sidebarMode === 'docked' && (
          <div className="shrink-0 h-full border-l border-white/[0.08] z-30">
            <MemoryNodeSidebarPanel
              node={selectedNode}
              links={graphData.links}
              allNodes={graphData.nodes}
              onClose={() => setSelectedNode(null)}
              onSelectNode={setSelectedNode}
              onReinforce={handleReinforce}
              onResolveContradiction={handleResolveContradiction}
              onFocusNodeNeighborhood={handleFocusNodeNeighborhood}
              onFilterByTag={handleFilterByTag}
              onStartPathFromNode={handleStartPathFromNode}
              displayMode="docked"
              onToggleDisplayMode={() => setSidebarMode('overlay')}
            />
          </div>
        )}
      </div>

      {/* Add Memory Modal */}
      <AddMemoryNodeModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAddNode={(nodeData) => {
          const created = memoryGraphStore.addNode(nodeData);
          setSelectedNode(created);
        }}
        existingNodes={graphData.nodes}
      />

      {/* Contradictions Resolution Modal */}
      <ContradictionsModal
        isOpen={isContradictionsModalOpen}
        onClose={() => setIsContradictionsModalOpen(false)}
        contradictionNodes={contradictionNodes}
        allNodes={graphData.nodes}
        onSelectNode={setSelectedNode}
        onResolve={handleResolveContradiction}
      />
    </div>
  );
}
