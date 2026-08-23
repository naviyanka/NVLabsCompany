import { useState, useCallback } from 'react';
import type { Agent2D, InteractivePOI, LightingMode, SimSpeed } from './types';
import { INITIAL_AGENTS_2D } from './agentCharacters';
import { DESKS_2D } from './office2DMap';
import { OpenOfficeToolbar } from './OpenOfficeToolbar';
import { OpenOfficeCanvas } from './OpenOfficeCanvas';
import { AgentsBottomBar } from './AgentsBottomBar';
import { POIModal } from './POIModal';
import { AgentInspectDrawer } from './AgentInspectDrawer';
import {
  triggerAllHandsMeeting,
  triggerCoffeeBreak,
  triggerSprintRush,
  triggerFreeRoam,
  navigateToPoint,
  navigateAgentBetweenDesks,
} from './movementEngine';

interface OpenOffice2DViewProps {
  viewMode: '2d' | '3d';
  onViewModeChange: (mode: '2d' | '3d') => void;
}

export function OpenOffice2DView({ viewMode, onViewModeChange }: OpenOffice2DViewProps) {
  const [agents, setAgents] = useState<Agent2D[]>(INITIAL_AGENTS_2D);
  const [selectedAgent, setSelectedAgent] = useState<Agent2D | null>(null);
  const [selectedPoi, setSelectedPoi] = useState<InteractivePOI | null>(null);

  const [simSpeed, setSimSpeed] = useState<SimSpeed>(1);
  const [lighting, setLighting] = useState<LightingMode>('day');
  const [zoom, setZoom] = useState<number>(1.0);
  const [searchFilter, setSearchFilter] = useState('');
  const [departmentFilter, setDepartmentFilter] = useState<string | null>(null);

  // Global Orchestrations
  const handleAllHands = useCallback(() => {
    setAgents((prev) => triggerAllHandsMeeting(prev));
  }, []);

  const handleCoffeeBreak = useCallback(() => {
    setAgents((prev) => triggerCoffeeBreak(prev));
  }, []);

  const handleSprintRush = useCallback(() => {
    setAgents((prev) => triggerSprintRush(prev));
  }, []);

  const handleFreeRoam = useCallback(() => {
    setAgents((prev) => triggerFreeRoam(prev));
  }, []);

  const handleResetZoom = useCallback(() => {
    setZoom(1.0);
  }, []);

  // Agent Specific Actions from Drawer
  const handleSendToDesk = useCallback((agentId: string) => {
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === agentId) {
          const desk = DESKS_2D.find((d) => d.id === a.deskId) || DESKS_2D[0] || { seatX: 200, seatY: 100 };
          const routed = navigateToPoint(a, desk.seatX, desk.seatY);
          return {
            ...routed,
            status: 'working',
            state2D: 'walking_to_desk',
            bubble: {
              text: 'Returning to my workstation 💻',
              emoji: '💻',
              expiresAt: Date.now() + 5000,
              type: 'action',
            },
          };
        }
        return a;
      })
    );
  }, []);

  const handleSendToBreakroom = useCallback((agentId: string) => {
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === agentId) {
          const routed = navigateToPoint(a, 1260, 140);
          return {
            ...routed,
            status: 'idle',
            state2D: 'walking_to_breakroom',
            bubble: {
              text: 'Grabbing coffee & chillin at lounge ☕',
              emoji: '☕',
              expiresAt: Date.now() + 6000,
              type: 'action',
            },
          };
        }
        return a;
      })
    );
  }, []);

  const handleSendToMeeting = useCallback((agentId: string) => {
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === agentId) {
          const routed = navigateToPoint(a, 600, 150);
          return {
            ...routed,
            status: 'review',
            state2D: 'in_meeting',
            bubble: {
              text: 'Heading to the War Room sync 📢',
              emoji: '📢',
              expiresAt: Date.now() + 6000,
              type: 'speech',
            },
          };
        }
        return a;
      })
    );
  }, []);

  const handleSendToRoam = useCallback((agentId: string) => {
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === agentId) {
          return {
            ...a,
            status: 'idle',
            state2D: 'idle_roaming',
            nextRoamDecisionTime: Date.now(),
            bubble: {
              text: 'Roaming the floor...',
              emoji: '🚶',
              expiresAt: Date.now() + 4000,
              type: 'thought',
            },
          };
        }
        return a;
      })
    );
  }, []);

  const handleVisitColleague = useCallback((agentId: string, colleagueId: string) => {
    setAgents((prev) => {
      const colleague = prev.find((a) => a.id === colleagueId);
      if (!colleague) return prev;
      return prev.map((a) => {
        if (a.id === agentId) {
          return navigateAgentBetweenDesks(a, colleague);
        }
        return a;
      });
    });
  }, []);

  const handleAssignTask = useCallback((agentId: string, taskTitle: string) => {
    setAgents((prev) =>
      prev.map((a) => {
        if (a.id === agentId) {
          const desk = DESKS_2D.find((d) => d.id === a.deskId) || DESKS_2D[0] || { seatX: 200, seatY: 100 };
          const routed = navigateToPoint(a, desk.seatX, desk.seatY);
          return {
            ...routed,
            status: 'working',
            state2D: 'walking_to_desk',
            currentTask: taskTitle,
            taskProgress: 5,
            bubble: {
              text: `On it! Starting: "${taskTitle}"`,
              emoji: '⚡',
              expiresAt: Date.now() + 6000,
              type: 'speech',
            },
          };
        }
        return a;
      })
    );
  }, []);

  const handlePOIAction = useCallback((actionType: string) => {
    if (actionType === 'coffee_boost') {
      setAgents((prev) =>
        prev.map((a) => ({
          ...a,
          energy: 100,
          speed: Math.min(a.speed * 1.3, 2.5),
          bubble: {
            text: 'Double espresso boost active! ☕⚡',
            emoji: '⚡',
            expiresAt: Date.now() + 5000,
            type: 'action',
          },
        }))
      );
    }
  }, []);

  return (
    <div className="h-full flex flex-col relative bg-[#070709] overflow-hidden">
      {/* Top Toolbar */}
      <OpenOfficeToolbar
        viewMode={viewMode}
        onViewModeChange={onViewModeChange}
        simSpeed={simSpeed}
        onSimSpeedChange={setSimSpeed}
        lighting={lighting}
        onLightingChange={setLighting}
        zoom={zoom}
        onZoomChange={setZoom}
        onResetZoom={handleResetZoom}
        onAllHands={handleAllHands}
        onCoffeeBreak={handleCoffeeBreak}
        onSprintRush={handleSprintRush}
        onFreeRoam={handleFreeRoam}
        searchFilter={searchFilter}
        onSearchFilterChange={setSearchFilter}
        departmentFilter={departmentFilter}
        onDepartmentFilterChange={setDepartmentFilter}
      />

      {/* Main Interactive HTML5 2D Pixel Canvas */}
      <main className="flex-1 relative overflow-hidden">
        <OpenOfficeCanvas
          agents={agents}
          onAgentsChange={setAgents}
          selectedAgentId={selectedAgent?.id ?? null}
          onSelectAgent={setSelectedAgent}
          onSelectPoi={setSelectedPoi}
          simSpeed={simSpeed}
          lighting={lighting}
          zoom={zoom}
          onZoomChange={setZoom}
          searchFilter={searchFilter}
          departmentFilter={departmentFilter}
        />
      </main>

      {/* Bottom Agents Quick Bar */}
      <AgentsBottomBar
        agents={agents}
        selectedAgentId={selectedAgent?.id ?? null}
        onSelectAgent={setSelectedAgent}
      />

      {/* Interactive POI Modal */}
      <POIModal
        poi={selectedPoi}
        onClose={() => setSelectedPoi(null)}
        onActionTrigger={handlePOIAction}
      />

      {/* Agent Detail Inspect Drawer */}
      <AgentInspectDrawer
        agent={selectedAgent}
        allAgents={agents}
        onClose={() => setSelectedAgent(null)}
        onSendToDesk={handleSendToDesk}
        onSendToBreakroom={handleSendToBreakroom}
        onSendToMeeting={handleSendToMeeting}
        onSendToRoam={handleSendToRoam}
        onVisitColleague={handleVisitColleague}
        onAssignTask={handleAssignTask}
      />
    </div>
  );
}
