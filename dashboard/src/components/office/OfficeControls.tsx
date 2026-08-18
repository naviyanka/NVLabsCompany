import { ZoomIn, ZoomOut, Maximize, Tag, GitBranch, Filter, Moon, Sun } from 'lucide-react';
import type { OfficeControls as OfficeControlsState } from '@/types/office';

interface OfficeControlsProps {
  controls: OfficeControlsState;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetView: () => void;
  onToggleLabels: () => void;
  onToggleDelegations: () => void;
  onToggleNightMode: () => void;
  onDepartmentFilter: (dept: string | null) => void;
  departments: string[];
}

export function OfficeControls({
  controls,
  onZoomIn,
  onZoomOut,
  onResetView,
  onToggleLabels,
  onToggleDelegations,
  onToggleNightMode,
  onDepartmentFilter,
  departments,
}: OfficeControlsProps) {
  return (
    <div className="absolute top-3 left-3 z-20 flex flex-col gap-1.5">
      {/* Zoom controls */}
      <div className="bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-gray-200 p-1 flex flex-col gap-0.5">
        <button
          onClick={onZoomIn}
          className="w-8 h-8 flex items-center justify-center rounded hover:bg-gray-100 transition-colors"
          title="Zoom in"
          aria-label="Zoom in"
        >
          <ZoomIn size={16} className="text-gray-700" />
        </button>
        <div className="text-[9px] text-center text-gray-500 font-mono">
          {Math.round(controls.zoom * 100)}%
        </div>
        <button
          onClick={onZoomOut}
          className="w-8 h-8 flex items-center justify-center rounded hover:bg-gray-100 transition-colors"
          title="Zoom out"
          aria-label="Zoom out"
        >
          <ZoomOut size={16} className="text-gray-700" />
        </button>
        <div className="w-full border-t border-gray-200 my-0.5" />
        <button
          onClick={onResetView}
          className="w-8 h-8 flex items-center justify-center rounded hover:bg-gray-100 transition-colors"
          title="Reset view"
          aria-label="Reset view"
        >
          <Maximize size={16} className="text-gray-700" />
        </button>
      </div>

      {/* Toggle controls */}
      <div className="bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-gray-200 p-1 flex flex-col gap-0.5">
        <button
          onClick={onToggleLabels}
          className={`w-8 h-8 flex items-center justify-center rounded transition-colors ${controls.showLabels ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100 text-gray-700'}`}
          title="Toggle labels"
          aria-label="Toggle labels"
        >
          <Tag size={14} />
        </button>
        <button
          onClick={onToggleDelegations}
          className={`w-8 h-8 flex items-center justify-center rounded transition-colors ${controls.showDelegations ? 'bg-blue-100 text-blue-600' : 'hover:bg-gray-100 text-gray-700'}`}
          title="Toggle delegation arrows"
          aria-label="Toggle delegation arrows"
        >
          <GitBranch size={14} />
        </button>
        <button
          onClick={onToggleNightMode}
          className={`w-8 h-8 flex items-center justify-center rounded transition-colors ${controls.nightMode ? 'bg-indigo-100 text-indigo-600' : 'hover:bg-gray-100 text-gray-700'}`}
          title="Toggle night mode"
          aria-label="Toggle night mode"
        >
          {controls.nightMode ? <Sun size={14} /> : <Moon size={14} />}
        </button>
      </div>

      {/* Department filter */}
      {departments.length > 0 && (
        <div className="bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-gray-200 p-1.5">
          <div className="flex items-center gap-1 mb-1">
            <Filter size={10} className="text-gray-500" />
            <span className="text-[9px] text-gray-500 font-medium">Filter</span>
          </div>
          <select
            value={controls.departmentFilter || ''}
            onChange={(e) => onDepartmentFilter(e.target.value || null)}
            className="w-full text-[10px] bg-gray-50 border border-gray-200 rounded px-1 py-0.5 text-gray-700"
            aria-label="Filter by department"
          >
            <option value="">All Depts</option>
            {departments.map((dept) => (
              <option key={dept} value={dept}>
                {dept}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
