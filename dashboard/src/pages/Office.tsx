import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { OfficeScene } from '@/components/office3d/OfficeScene';
import { StatsBar } from '@/components/office3d/StatsBar';
import { AgentDetailSidebar } from '@/components/office3d/AgentDetailSidebar';
import { AgentsAtGlance } from '@/components/office3d/AgentsAtGlance';
import { OfficeMobileFallback } from '@/components/office3d/OfficeMobileFallback';
import { usePageVisibility } from '@/hooks/usePageVisibility';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import type { MockAgent3D } from '@/config/office3dLayout';

/**
 * Office page - 3D isometric office floor plan view using Three.js / React Three Fiber.
 * Shows AI agents in named zones with animations, delegation flows, and interactive panels.
 *
 * Features:
 * - Lazy loaded at the route level (see App.tsx) to avoid bundle cost for non-visitors
 * - Pauses GPU rendering when the browser tab is hidden
 * - Falls back to a simplified list view on small screens (< 768px)
 * - Quick action buttons navigate to agent detail pages
 */
export function Office() {
  const [selectedAgent, setSelectedAgent] = useState<MockAgent3D | null>(null);
  const navigate = useNavigate();
  const isVisible = usePageVisibility();
  const isSmallScreen = useMediaQuery('(max-width: 767px)');

  const handleAgentClick = useCallback((agent: MockAgent3D) => {
    setSelectedAgent((prev) => (prev?.id === agent.id ? null : agent));
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  const handleCloseSidebar = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  const handleViewProfile = useCallback((agent: MockAgent3D) => {
    navigate(`/agents/${agent.id}`);
  }, [navigate]);

  // On small screens, render a simplified mobile-friendly view instead of the 3D canvas
  if (isSmallScreen) {
    return (
      <OfficeMobileFallback
        selectedAgent={selectedAgent}
        onAgentClick={handleAgentClick}
        onCloseSidebar={handleCloseSidebar}
        onViewProfile={handleViewProfile}
      />
    );
  }

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
          paused={!isVisible}
        />
      </div>

      {/* Agent detail sidebar (conditionally shown) */}
      {selectedAgent && (
        <AgentDetailSidebar
          agent={selectedAgent}
          onClose={handleCloseSidebar}
          onViewProfile={handleViewProfile}
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
