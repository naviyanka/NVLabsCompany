import {
  Share2,
  CircleDot,
  GitCommit,
  Download,
  Activity,
  Sliders,
  MapPin,
  RefreshCw,
  Maximize2,
  Minimize2,
  Filter,
  Layers,
  GitFork,
  Route,
} from 'lucide-react';
import { LayoutMode } from '@/types/memoryGraph';

interface GraphControlsProps {
  layoutMode: LayoutMode;
  onLayoutModeChange: (mode: LayoutMode) => void;
  showClusters: boolean;
  onToggleClusters: () => void;
  showMinimap: boolean;
  onToggleMinimap: () => void;
  animateParticles: boolean;
  onToggleParticles: () => void;
  physicsStrength: number;
  onPhysicsStrengthChange: (val: number) => void;
  onFitView: () => void;
  onExportJSON: () => void;
  isFullscreen?: boolean;
  onToggleFullscreen?: () => void;
  showFilterDrawer?: boolean;
  onToggleFilterDrawer?: () => void;
  activeFilterCount?: number;
  sidebarDocked?: boolean;
  onToggleSidebarDocked?: () => void;
  hasSelectedNode?: boolean;
  showLegend?: boolean;
  onToggleLegend?: () => void;
  showPathFinder?: boolean;
  onTogglePathFinder?: () => void;
  hasActivePath?: boolean;
}

export function GraphControls({
  layoutMode,
  onLayoutModeChange,
  showClusters,
  onToggleClusters,
  showMinimap,
  onToggleMinimap,
  animateParticles,
  onToggleParticles,
  physicsStrength,
  onPhysicsStrengthChange,
  onFitView,
  onExportJSON,
  isFullscreen = false,
  onToggleFullscreen,
  showFilterDrawer,
  onToggleFilterDrawer,
  activeFilterCount = 0,
  showLegend,
  onToggleLegend,
  showPathFinder,
  onTogglePathFinder,
  hasActivePath,
}: GraphControlsProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 p-1.5 bg-[#101012]/95 backdrop-blur-md border border-white/[0.08] rounded-[8px]">
      {/* Layout Mode Switcher & Filter Trigger */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {onToggleFilterDrawer && (
          <button
            onClick={onToggleFilterDrawer}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] text-xs font-mono border transition-all cursor-pointer ${
              showFilterDrawer
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold border-[#FFB020] shadow-sm'
                : 'bg-[#141416] text-[#F2F1EE] border-white/[0.1] hover:border-[#FFB020]/40'
            }`}
            title="Toggle Search, Filters & Types Drawer"
          >
            <Filter className="w-3.5 h-3.5" />
            <span className="font-medium">Filters & Search</span>
            {activeFilterCount > 0 && (
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                  showFilterDrawer ? 'bg-[#0A0A0B] text-[#FFB020]' : 'bg-[#FFB020] text-[#0A0A0B]'
                }`}
              >
                {activeFilterCount}
              </span>
            )}
          </button>
        )}

        <div className="flex items-center gap-1 bg-[#141416] p-1 border border-white/[0.06] rounded-[6px]">
          <button
            onClick={() => onLayoutModeChange('force')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
              layoutMode === 'force'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold shadow-sm'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE]'
            }`}
            title="Force-Directed Multi-Cluster Physics"
          >
            <Share2 className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Force Graph</span>
          </button>

          <button
            onClick={() => onLayoutModeChange('radial')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
              layoutMode === 'radial'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold shadow-sm'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE]'
            }`}
            title="Radial Concentric Hierarchy"
          >
            <CircleDot className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Radial View</span>
          </button>

          <button
            onClick={() => onLayoutModeChange('sequential')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
              layoutMode === 'sequential'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold shadow-sm'
                : 'text-[#6B6B6E] hover:text-[#F2F1EE]'
            }`}
            title="Sequential Provenance Flow"
          >
            <GitCommit className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Sequential Flow</span>
          </button>
        </div>
      </div>

      {/* Physics / Visual Controls */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {layoutMode === 'force' && (
          <div className="hidden lg:flex items-center gap-1.5 px-2 py-1 bg-[#141416] border border-white/[0.06] rounded-[6px] text-[11px] font-mono text-[#6B6B6E]">
            <Sliders className="w-3 h-3 text-[#FFB020]" />
            <span>Physics:</span>
            <input
              type="range"
              min="0.2"
              max="2.0"
              step="0.1"
              value={physicsStrength}
              onChange={(e) => onPhysicsStrengthChange(parseFloat(e.target.value))}
              className="w-14 accent-[#FFB020]"
            />
          </div>
        )}

        {/* Toggle Cluster Halos */}
        <button
          onClick={onToggleClusters}
          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-colors cursor-pointer ${
            showClusters
              ? 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/30'
              : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
          }`}
          title="Toggle Semantic Cluster Halos"
        >
          <Layers className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Clusters</span>
        </button>

        {/* Toggle Particles */}
        <button
          onClick={onToggleParticles}
          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-colors cursor-pointer ${
            animateParticles
              ? 'bg-[#34D399]/15 text-[#34D399] border-[#34D399]/30'
              : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
          }`}
          title="Toggle Animated Pulse Flow"
        >
          <Activity className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Pulses</span>
        </button>

        {/* Toggle Radar / Minimap */}
        <button
          onClick={onToggleMinimap}
          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-colors cursor-pointer ${
            showMinimap
              ? 'bg-[#38BDF8]/15 text-[#38BDF8] border-[#38BDF8]/30'
              : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
          }`}
          title="Toggle Radar Minimap"
        >
          <MapPin className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Radar</span>
        </button>

        {/* Toggle Relationship Legend */}
        {onToggleLegend && (
          <button
            onClick={onToggleLegend}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-colors cursor-pointer ${
              showLegend
                ? 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/30'
                : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
            }`}
            title="Toggle Edge Visual Syntax & Relationship Legend"
          >
            <GitFork className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Legend</span>
          </button>
        )}

        {/* Shortest Path Finder Toggle */}
        {onTogglePathFinder && (
          <button
            onClick={onTogglePathFinder}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-all cursor-pointer ${
              showPathFinder
                ? 'bg-[#38BDF8]/20 text-[#38BDF8] border-[#38BDF8]/40 shadow-sm'
                : hasActivePath
                ? 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/30'
                : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
            }`}
            title="Shortest Path & Dependency Chain Tool"
          >
            <Route className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Path Finder</span>
            {hasActivePath && (
              <span className="w-1.5 h-1.5 rounded-full bg-[#38BDF8] animate-ping" />
            )}
          </button>
        )}

        {/* Fit View */}
        <button
          onClick={onFitView}
          className="flex items-center gap-1 px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.04] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded-[6px] text-xs font-mono transition-colors cursor-pointer"
          title="Fit view to all nodes"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Recenter</span>
        </button>

        {/* Export JSON */}
        <button
          onClick={onExportJSON}
          className="flex items-center gap-1 px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.04] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08] rounded-[6px] text-xs font-mono transition-colors cursor-pointer"
          title="Export Memory Graph JSON"
        >
          <Download className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Export</span>
        </button>

        {/* Fullscreen Toggle */}
        {onToggleFullscreen && (
          <button
            onClick={onToggleFullscreen}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-[6px] text-xs font-mono border transition-colors cursor-pointer ${
              isFullscreen
                ? 'bg-[#FFB020] text-[#0A0A0B] font-semibold border-[#FFB020]'
                : 'bg-[#141416] text-[#6B6B6E] border-white/[0.08] hover:text-[#F2F1EE]'
            }`}
            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Graph Canvas'}
          >
            {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            <span className="hidden xl:inline">{isFullscreen ? 'Exit Full' : 'Fullscreen'}</span>
          </button>
        )}
      </div>
    </div>
  );
}
