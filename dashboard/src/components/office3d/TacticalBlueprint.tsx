import { useState } from 'react';
import { zones3D, mockAgents3D, managerAgent, managerCabin, status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';
import { ShieldCheck } from 'lucide-react';

interface TacticalBlueprintProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onBackgroundClick: () => void;
}

/**
 * 2D Tactical Blueprint Engine component.
 * Provides a high-contrast vector blueprint visualization with interactive rooms,
 * clickable agent workstations, and real-time activity indicators.
 */
export function TacticalBlueprint({ selectedAgent, onAgentClick, onBackgroundClick }: TacticalBlueprintProps) {
  const [hoveredAgent, setHoveredAgent] = useState<MockAgent3D | null>(null);

  const allAgents = [...mockAgents3D, managerAgent];

  return (
    <div
      onClick={onBackgroundClick}
      className="w-full h-full bg-[#050914] relative overflow-hidden flex items-center justify-center p-6 select-none"
    >
      {/* Blueprint Background Grid Patterns */}
      <div
        className="absolute inset-0 opacity-15 pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(6, 182, 212, 0.2) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(6, 182, 212, 0.2) 1px, transparent 1px)
          `,
          backgroundSize: '32px 32px',
        }}
      />
      <div
        className="absolute inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 255, 255, 0.3) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 255, 255, 0.3) 1px, transparent 1px)
          `,
          backgroundSize: '160px 160px',
        }}
      />

      {/* Main Blueprint Canvas Area */}
      <div className="relative w-full max-w-5xl aspect-[16/10] border border-cyan-500/30 rounded-2xl bg-[#091024]/90 backdrop-blur-md shadow-2xl p-6 flex flex-col justify-between">
        {/* Top Header Badge */}
        <div className="flex items-center justify-between pb-3 border-b border-cyan-500/20">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-cyan-400" />
            <span className="text-xs font-bold text-cyan-400 uppercase tracking-widest">
              TACTICAL FLOOR PLAN BLUEPRINT // HQ 01
            </span>
          </div>
          <div className="flex items-center gap-4 text-[11px] font-mono text-gray-400">
            <span>GRID SCALE: 1:50</span>
            <span>ACTIVE UNITS: {allAgents.filter((a) => a.status === 'working').length}/{allAgents.length}</span>
          </div>
        </div>

        {/* Tactical Layout Grid */}
        <div className="relative flex-1 my-4 grid grid-cols-3 grid-rows-3 gap-4">
          {/* Executive Suite / Manager Cabin */}
          <div
            onClick={(e) => {
              e.stopPropagation();
              onAgentClick(managerAgent);
            }}
            className={`col-span-3 border rounded-xl p-3 relative cursor-pointer transition-all duration-200 ${
              selectedAgent?.id === managerAgent.id
                ? 'bg-indigo-950/60 border-indigo-400 shadow-[0_0_20px_rgba(99,102,241,0.3)]'
                : 'bg-indigo-950/20 border-indigo-500/30 hover:border-indigo-400/60 hover:bg-indigo-950/40'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider font-mono">
                EXECUTIVE SUITE &bull; MANAGER CABIN
              </span>
              <span className="text-[10px] font-mono text-indigo-400 border border-indigo-500/30 rounded px-1.5 py-0.5">
                ZONE ID: CABIN-01
              </span>
            </div>

            <div className="mt-2 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="w-9 h-9 rounded-full bg-indigo-500/20 border border-indigo-400 flex items-center justify-center font-bold text-indigo-300">
                    A
                  </div>
                  <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-dark-bg animate-pulse" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-white">{managerAgent.name}</p>
                  <p className="text-[10px] text-indigo-300/80">{managerAgent.role} &bull; {managerAgent.model}</p>
                </div>
              </div>
              <div className="text-right">
                <p className="text-[11px] font-mono text-gray-300">{managerAgent.currentTask}</p>
                <p className="text-[10px] font-mono text-emerald-400">STATUS: {statusLabels[managerAgent.status]}</p>
              </div>
            </div>
          </div>

          {/* Department Zones */}
          {zones3D.map((zone) => {
            const zoneAgents = allAgents.filter((a) => a.zoneId === zone.id);

            return (
              <div
                key={zone.id}
                className="border rounded-xl p-3 relative flex flex-col justify-between transition-all duration-200"
                style={{
                  backgroundColor: `${zone.borderColor}10`,
                  borderColor: `${zone.borderColor}40`,
                }}
              >
                {/* Zone Header */}
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider font-mono" style={{ color: zone.borderColor }}>
                    {zone.name}
                  </span>
                  <span className="text-[9px] font-mono text-gray-400">
                    {zoneAgents.length} UNITS
                  </span>
                </div>

                {/* Desks Grid */}
                <div className="grid grid-cols-2 gap-2 my-auto">
                  {zone.desks.map((desk) => {
                    const agent = zoneAgents.find((a) => a.deskId === desk.id);
                    const isSelected = selectedAgent?.id === agent?.id;
                    const statusColor = agent ? status3DColors[agent.status] : '#4b5563';

                    return (
                      <div
                        key={desk.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (agent) onAgentClick(agent);
                        }}
                        onMouseEnter={() => agent && setHoveredAgent(agent)}
                        onMouseLeave={() => setHoveredAgent(null)}
                        className={`p-2 rounded-lg border transition-all duration-150 relative ${
                          agent
                            ? isSelected
                              ? 'bg-primary-500/20 border-primary-400 ring-2 ring-primary-500/40 shadow-lg cursor-pointer scale-105'
                              : 'bg-dark-surface/80 border-white/10 hover:border-white/30 hover:bg-dark-surface cursor-pointer'
                            : 'bg-black/20 border-white/[0.04] opacity-50 cursor-not-allowed'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            style={{
                              backgroundColor: statusColor,
                              boxShadow: agent?.status === 'working' ? `0 0 8px ${statusColor}` : 'none',
                            }}
                          />
                          <div className="min-w-0 flex-1">
                            <p className="text-xs font-semibold text-white truncate">
                              {agent ? agent.name : 'Vacant Desk'}
                            </p>
                            <p className="text-[9px] text-gray-400 truncate">
                              {agent ? agent.role : desk.id}
                            </p>
                          </div>
                        </div>

                        {/* Task Progress Bar */}
                        {agent && agent.taskProgress > 0 && (
                          <div className="w-full h-1 bg-black/40 rounded-full mt-1.5 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-300"
                              style={{
                                width: `${agent.taskProgress}%`,
                                backgroundColor: statusColor,
                              }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Bottom Status Telemetry Footer */}
        <div className="pt-3 border-t border-cyan-500/20 flex items-center justify-between text-[11px] font-mono">
          <div className="flex items-center gap-4 text-gray-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400" /> Working ({allAgents.filter((a) => a.status === 'working').length})
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-400" /> Idle ({allAgents.filter((a) => a.status === 'idle').length})
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-purple-400" /> Review ({allAgents.filter((a) => a.status === 'review').length})
            </span>
          </div>

          <div className="text-cyan-400/80">
            {hoveredAgent ? (
              <span>HOVER: {hoveredAgent.name} &bull; TASK: {hoveredAgent.currentTask}</span>
            ) : selectedAgent ? (
              <span>SELECTED: {selectedAgent.name} &bull; ROLE: {selectedAgent.role}</span>
            ) : (
              <span>CLICK ANY DESK OR AGENT WORKSTATION TO INSPECT</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
