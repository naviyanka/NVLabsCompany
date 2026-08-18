import { useState, useCallback, useMemo } from 'react';
import { Loader2, List, Grid } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useOffice } from '@/hooks/useOffice';
import { OfficeCanvas } from '@/components/office/OfficeCanvas';
import { FloorPlan } from '@/components/office/FloorPlan';
import { StatusPanel } from '@/components/office/StatusPanel';
import { ActivityTicker } from '@/components/office/ActivityTicker';
import { OfficeControls } from '@/components/office/OfficeControls';
import { DelegationFlow } from '@/components/office/DelegationFlow';
import type { OfficeControls as OfficeControlsState } from '@/types/office';
import type { Task } from '@/types/task';
import { statusColors } from '@/config/officeLayout';

export function Office() {
  const { officeState, events, agents, tasks, loading, error, stats } = useOffice();

  // Controls state
  const [controls, setControls] = useState<OfficeControlsState>({
    zoom: 0.85,
    panX: 40,
    panY: 20,
    showLabels: true,
    showDelegations: true,
    departmentFilter: null,
    nightMode: false,
  });

  // Mobile view detection
  const [mobileView, setMobileView] = useState<'spatial' | 'list'>('spatial');

  // Get unique departments for filter
  const departments = useMemo(() => {
    const depts = new Set<string>();
    officeState.rooms.forEach((room) => {
      if (room.departmentId) depts.add(room.departmentId);
    });
    return Array.from(depts);
  }, [officeState.rooms]);

  // Control handlers
  const handleZoomIn = useCallback(() => {
    setControls((prev) => ({ ...prev, zoom: Math.min(2.5, prev.zoom + 0.15) }));
  }, []);

  const handleZoomOut = useCallback(() => {
    setControls((prev) => ({ ...prev, zoom: Math.max(0.3, prev.zoom - 0.15) }));
  }, []);

  const handleResetView = useCallback(() => {
    setControls((prev) => ({ ...prev, zoom: 0.85, panX: 40, panY: 20 }));
  }, []);

  const handleToggleLabels = useCallback(() => {
    setControls((prev) => ({ ...prev, showLabels: !prev.showLabels }));
  }, []);

  const handleToggleDelegations = useCallback(() => {
    setControls((prev) => ({ ...prev, showDelegations: !prev.showDelegations }));
  }, []);

  const handleToggleNightMode = useCallback(() => {
    setControls((prev) => ({ ...prev, nightMode: !prev.nightMode }));
  }, []);

  const handleDepartmentFilter = useCallback((dept: string | null) => {
    setControls((prev) => ({ ...prev, departmentFilter: dept }));
  }, []);

  const handlePanChange = useCallback((x: number, y: number) => {
    setControls((prev) => ({ ...prev, panX: x, panY: y }));
  }, []);

  const handleZoomChange = useCallback((zoom: number) => {
    setControls((prev) => ({ ...prev, zoom }));
  }, []);

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-red-500 text-sm mb-2">Failed to load office data</p>
          <p className="text-gray-500 text-xs">{error}</p>
        </div>
      </div>
    );
  }

  // Loading state
  if (loading && agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          <span className="text-sm text-gray-500">Loading office...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col relative -m-6">
      {/* Mobile toggle */}
      <div className="md:hidden absolute top-2 right-2 z-30 flex gap-1 bg-white/95 rounded-lg shadow border border-gray-200 p-1">
        <button
          onClick={() => setMobileView('spatial')}
          className={`p-1.5 rounded ${mobileView === 'spatial' ? 'bg-blue-100 text-blue-600' : 'text-gray-600'}`}
          aria-label="Spatial view"
        >
          <Grid size={16} />
        </button>
        <button
          onClick={() => setMobileView('list')}
          className={`p-1.5 rounded ${mobileView === 'list' ? 'bg-blue-100 text-blue-600' : 'text-gray-600'}`}
          aria-label="List view"
        >
          <List size={16} />
        </button>
      </div>

      {/* Mobile list view */}
      <div className={`md:hidden flex-1 overflow-auto ${mobileView === 'list' ? 'block' : 'hidden'}`}>
        <MobileListView agents={agents} tasks={tasks} stats={stats} />
      </div>

      {/* Spatial office view */}
      <div className={`flex-1 relative ${mobileView === 'list' ? 'hidden md:block' : 'block'}`}>
        <OfficeCanvas
          zoom={controls.zoom}
          panX={controls.panX}
          panY={controls.panY}
          onPanChange={handlePanChange}
          onZoomChange={handleZoomChange}
          nightMode={controls.nightMode}
        >
          <FloorPlan
            officeState={officeState}
            agents={agents}
            tasks={tasks}
            showLabels={controls.showLabels}
            departmentFilter={controls.departmentFilter}
          />
          <DelegationFlow
            delegations={officeState.delegations}
            agentPositions={officeState.agents}
            visible={controls.showDelegations}
          />
        </OfficeCanvas>

        {/* Overlay panels */}
        <StatusPanel
          agentsOnline={stats.agentsOnline}
          tasksRunning={stats.tasksRunning}
          meetingsActive={stats.meetingsActive}
          loading={loading}
        />

        <OfficeControls
          controls={controls}
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onResetView={handleResetView}
          onToggleLabels={handleToggleLabels}
          onToggleDelegations={handleToggleDelegations}
          onToggleNightMode={handleToggleNightMode}
          onDepartmentFilter={handleDepartmentFilter}
          departments={departments}
        />

        <ActivityTicker events={events} />
      </div>
    </div>
  );
}

/** Mobile-friendly list view showing agents grouped by status */
interface MobileListViewProps {
  agents: import('@/types/agent').Agent[];
  tasks: Task[];
  stats: { agentsOnline: number; tasksRunning: number; meetingsActive: number };
}

function MobileListView({ agents, tasks, stats }: MobileListViewProps) {
  const navigate = useNavigate();

  const taskMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const task of tasks) {
      if (task.assigned_agent_id && (task.status === 'in_progress' || task.status === 'assigned')) {
        map.set(task.assigned_agent_id, task.title);
      }
    }
    return map;
  }, [tasks]);

  return (
    <div className="p-4 space-y-4">
      {/* Stats cards */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-emerald-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-emerald-700">{stats.agentsOnline}</div>
          <div className="text-xs text-emerald-600">Online</div>
        </div>
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-blue-700">{stats.tasksRunning}</div>
          <div className="text-xs text-blue-600">Running</div>
        </div>
        <div className="bg-purple-50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-purple-700">{stats.meetingsActive}</div>
          <div className="text-xs text-purple-600">Meetings</div>
        </div>
      </div>

      {/* Agent list */}
      <div className="space-y-2">
        {agents.map((agent) => {
          const color = statusColors[agent.status] || statusColors.idle;
          const currentTask = taskMap.get(agent.id);
          return (
            <button
              key={agent.id}
              className="w-full flex items-center gap-3 p-3 bg-white rounded-lg border border-gray-200 shadow-sm text-left hover:border-gray-300 transition-colors"
              onClick={() => navigate(`/agents/${agent.id}`)}
            >
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-gray-700 bg-gray-50 border-2 flex-shrink-0"
                style={{ borderColor: color }}
              >
                {agent.name.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-900 truncate">{agent.name}</div>
                <div className="text-xs text-gray-500 truncate">{agent.role}</div>
                {currentTask && (
                  <div className="text-[11px] text-blue-600 truncate mt-0.5">
                    {currentTask}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="text-xs text-gray-500 capitalize">{agent.status}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
