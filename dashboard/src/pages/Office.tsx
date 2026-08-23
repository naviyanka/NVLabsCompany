import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { OfficeScene } from '@/components/office3d/OfficeScene';
import { StatsBar } from '@/components/office3d/StatsBar';
import { AgentDetailSidebar } from '@/components/office3d/AgentDetailSidebar';
import { AgentsAtGlance } from '@/components/office3d/AgentsAtGlance';
import { OfficeMobileFallback } from '@/components/office3d/OfficeMobileFallback';
import { OpenOffice2DView } from '@/components/office2d/OpenOffice2DView';
import { usePageVisibility } from '@/hooks/usePageVisibility';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import type { MockAgent3D } from '@/config/office3dLayout';

/**
 * Office page - Supports both 2D OpenOffice Pixel floor (with autonomous roaming agents)
 * and 3D isometric office floor plan view using Three.js / React Three Fiber.
 */
export function Office() {
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d');
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

  // If in 2D OpenOffice mode, render the full 2D pixel simulation floor
  if (viewMode === '2d') {
    return (
      <div className="h-[calc(100vh-2rem)] flex flex-col relative -m-6 bg-dark-bg overflow-hidden">
        <OpenOffice2DView
          viewMode={viewMode}
          onViewModeChange={setViewMode}
        />
      </div>
    );
  }

  // On small screens in 3D mode, render a simplified mobile-friendly view
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
      <div className="relative">
        <StatsBar />
        {/* Toggle back to 2D view */}
        <button
          onClick={() => setViewMode('2d')}
          className="absolute right-4 top-1/2 -translate-y-1/2 px-3 py-1 rounded-md bg-[#FFB020] text-black text-xs font-mono font-bold hover:bg-[#FFC043] transition-colors shadow-sm"
        >
          Switch to 2D OpenOffice (Pixel)
        </button>
      </div>

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
