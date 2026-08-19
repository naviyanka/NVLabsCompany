import { useState, useCallback } from 'react';
import { OfficeScene } from '@/components/office3d/OfficeScene';
import { StatsBar } from '@/components/office3d/StatsBar';
import { AgentDetailSidebar } from '@/components/office3d/AgentDetailSidebar';
import { AgentsAtGlance } from '@/components/office3d/AgentsAtGlance';
import type { MockAgent3D } from '@/config/office3dLayout';

/**
 * Office page - 3D isometric office floor plan view using Three.js / React Three Fiber.
 * Shows AI agents in named zones with animations, delegation flows, and interactive panels.
 */
export function Office() {
  const [selectedAgent, setSelectedAgent] = useState<MockAgent3D | null>(null);

  const handleAgentClick = useCallback((agent: MockAgent3D) => {
    setSelectedAgent((prev) => (prev?.id === agent.id ? null : agent));
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  const handleCloseSidebar = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col relative -m-6 bg-dark-bg overflow-hidden">
      {/* Top stats bar */}
      <StatsBar />

      {/* 3D Canvas - fills the main area */}
      <div className="flex-1 relative">
        <OfficeScene
          selectedAgent={selectedAgent}
          onAgentClick={handleAgentClick}
          onBackgroundClick={handleBackgroundClick}
        />
      </div>

      {/* Agent detail sidebar (conditionally shown) */}
      {selectedAgent && (
        <AgentDetailSidebar
          agent={selectedAgent}
          onClose={handleCloseSidebar}
        />
      )}

      {/* Bottom agents at a glance */}
      <AgentsAtGlance
        onAgentClick={handleAgentClick}
        selectedAgentId={selectedAgent?.id ?? null}
      />
    </div>
  );
}
