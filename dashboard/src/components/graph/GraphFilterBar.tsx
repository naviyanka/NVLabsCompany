import {
  Search,
  AlertTriangle,
  Layers,
  Users,
  RotateCcw,
} from 'lucide-react';
import {
  GraphFilterState,
  MemoryNodeType,
  MemoryClusterId,
} from '@/types/memoryGraph';
import { NODE_TYPE_COLORS, MEMORY_CLUSTERS } from '@/lib/memoryGraphAdapter';

interface GraphFilterBarProps {
  filterState: GraphFilterState;
  onFilterChange: (updater: (prev: GraphFilterState) => GraphFilterState) => void;
  onResetFilters: () => void;
}

const ALL_NODE_TYPES: Array<{ type: MemoryNodeType; label: string }> = [
  { type: 'agent', label: 'Agents' },
  { type: 'goal', label: 'Goals' },
  { type: 'task', label: 'Tasks' },
  { type: 'knowledge', label: 'Knowledge' },
  { type: 'decision', label: 'Decisions' },
  { type: 'derived', label: 'Derived' },
  { type: 'fact', label: 'Facts' },
  { type: 'observation', label: 'Observations' },
  { type: 'experience', label: 'Experiences' },
  { type: 'tool_result', label: 'Tool Results' },
  { type: 'contradiction', label: 'Contradictions' },
];

export function GraphFilterBar({
  filterState,
  onFilterChange,
  onResetFilters,
}: GraphFilterBarProps) {
  const toggleNodeType = (type: MemoryNodeType) => {
    onFilterChange((prev) => {
      const nextTypes = new Set(prev.selectedTypes);
      if (nextTypes.has(type)) {
        nextTypes.delete(type);
      } else {
        nextTypes.add(type);
      }
      return { ...prev, selectedTypes: nextTypes };
    });
  };

  const toggleCluster = (clusterId: MemoryClusterId) => {
    onFilterChange((prev) => {
      const nextClusters = new Set(prev.selectedClusters);
      if (nextClusters.has(clusterId)) {
        nextClusters.delete(clusterId);
      } else {
        nextClusters.add(clusterId);
      }
      return { ...prev, selectedClusters: nextClusters };
    });
  };

  return (
    <div className="bg-[#101012] border border-white/[0.08] rounded-[8px] p-3 space-y-3">
      {/* Top Search & High-Level Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Search Input */}
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={filterState.searchQuery}
            onChange={(e) =>
              onFilterChange((prev) => ({ ...prev, searchQuery: e.target.value }))
            }
            placeholder="Search memory graph, concepts, tags..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Agent Selector */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-xs font-mono text-[#6B6B6E]">
            <Users className="w-3.5 h-3.5 text-[#FFB020]" />
            <span>Agent:</span>
          </div>
          <select
            value={filterState.selectedAgent}
            onChange={(e) =>
              onFilterChange((prev) => ({ ...prev, selectedAgent: e.target.value }))
            }
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] font-mono focus:outline-none focus:border-[#FFB020]"
          >
            <option value="all">All Agents (Collective)</option>
            <option value="agent-atlas">Atlas-01 (CEO)</option>
            <option value="agent-nova">Nova-02 (CTO)</option>
            <option value="agent-bolt">Bolt-03 (Backend)</option>
            <option value="agent-pixel">Pixel-04 (Frontend)</option>
            <option value="agent-sage">Sage-05 (AI Research)</option>
            <option value="agent-shield">Shield-07 (Security)</option>
            <option value="agent-forge">Forge-08 (DevOps)</option>
          </select>
        </div>

        {/* Contradictions Flagged Toggle */}
        <button
          onClick={() =>
            onFilterChange((prev) => ({
              ...prev,
              showOnlyContradictions: !prev.showOnlyContradictions,
            }))
          }
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] text-xs font-mono transition-colors cursor-pointer border ${
            filterState.showOnlyContradictions
              ? 'bg-[#EF4444] text-[#FFFFFF] border-[#DC2626] font-medium animate-pulse'
              : 'bg-[#141416] text-[#EF4444] border-red-500/30 hover:bg-red-500/10'
          }`}
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>Contradictions Only</span>
        </button>

        {/* Reset Filter Button */}
        <button
          onClick={onResetFilters}
          className="flex items-center gap-1 px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.04] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded-[6px] text-xs font-mono transition-colors cursor-pointer"
          title="Reset all filters"
        >
          <RotateCcw className="w-3 h-3" />
          <span>Reset</span>
        </button>
      </div>

      {/* Node Type Pills */}
      <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-white/[0.04]">
        <span className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider mr-1">
          Node Types:
        </span>
        {ALL_NODE_TYPES.map(({ type, label }) => {
          const isSelected =
            filterState.selectedTypes.size === 0 || filterState.selectedTypes.has(type);
          const colors = NODE_TYPE_COLORS[type];

          return (
            <button
              key={type}
              onClick={() => toggleNodeType(type)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] text-[11px] font-mono transition-all cursor-pointer border ${
                isSelected
                  ? 'border-transparent text-[#F2F1EE]'
                  : 'opacity-40 border-white/[0.06] text-[#6B6B6E]'
              }`}
              style={{
                backgroundColor: isSelected ? `${colors.bg}22` : '#141416',
                borderColor: isSelected ? colors.border : undefined,
              }}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: colors.bg }}
              />
              <span>{label}</span>
            </button>
          );
        })}
      </div>

      {/* Cluster Pills & Sliders */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-white/[0.04]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider mr-1 flex items-center gap-1">
            <Layers className="w-3 h-3" />
            Clusters:
          </span>
          {MEMORY_CLUSTERS.map((c) => {
            const isSelected =
              filterState.selectedClusters.size === 0 ||
              filterState.selectedClusters.has(c.id);

            return (
              <button
                key={c.id}
                onClick={() => toggleCluster(c.id)}
                className={`px-2 py-0.5 rounded-[4px] text-[10px] font-mono transition-all cursor-pointer border ${
                  isSelected
                    ? 'text-[#F2F1EE] border-transparent'
                    : 'opacity-40 text-[#6B6B6E] border-white/[0.06]'
                }`}
                style={{
                  backgroundColor: isSelected ? `${c.color}22` : '#141416',
                  borderColor: isSelected ? c.color : undefined,
                }}
              >
                {(c.name || 'Cluster').split(' ')[0]}
              </button>
            );
          })}
        </div>

        {/* Confidence & Memory Retention Slider */}
        <div className="flex items-center gap-4 text-xs font-mono text-[#6B6B6E]">
          <div className="flex items-center gap-1.5">
            <span>Min Conf:</span>
            <input
              type="range"
              min="0.5"
              max="0.99"
              step="0.05"
              value={filterState.minConfidence}
              onChange={(e) =>
                onFilterChange((prev) => ({
                  ...prev,
                  minConfidence: parseFloat(e.target.value),
                }))
              }
              className="w-16 accent-[#FFB020]"
            />
            <span className="text-[#F2F1EE] font-medium">
              {Math.round(filterState.minConfidence * 100)}%
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span>Memory Freshness:</span>
            <input
              type="range"
              min="0"
              max="90"
              step="10"
              value={filterState.timeDecayThreshold}
              onChange={(e) =>
                onFilterChange((prev) => ({
                  ...prev,
                  timeDecayThreshold: parseInt(e.target.value, 10),
                }))
              }
              className="w-16 accent-[#FFB020]"
            />
            <span className="text-[#F2F1EE] font-medium">
              {filterState.timeDecayThreshold}%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
