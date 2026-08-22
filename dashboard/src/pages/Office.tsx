import { useState, useCallback, Component, ReactNode } from 'react';
import { OfficeScene } from '@/components/office3d/OfficeScene';
import { BabylonCanvas, type SelectionState } from '@/components/office-babylon/BabylonCanvas';
import { TacticalBlueprint } from '@/components/office3d/TacticalBlueprint';
import { RealisticOfficeView } from '@/components/office2d/RealisticOfficeView';
import { PixelOfficeConsole } from '@/components/office-pixel/PixelOfficeConsole';
import { StatsBar, type EngineMode } from '@/components/office3d/StatsBar';
import { AgentDetailSidebar } from '@/components/office3d/AgentDetailSidebar';
import { RoomPanel } from '@/components/office-babylon/panels/RoomPanel';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';
import { CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
  onFallback: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

class OfficeErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: any) {
    console.error('3D Engine Render Error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full flex items-center justify-center bg-[#070b14] p-6">
          <div className="max-w-md bg-dark-card border border-white/10 rounded-2xl p-6 text-center space-y-3 shadow-2xl">
            <div className="w-12 h-12 rounded-full bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 mx-auto">
              <AlertTriangle size={24} />
            </div>
            <h3 className="text-base font-bold text-white">WebGL 3D Context Error</h3>
            <p className="text-xs text-gray-400 leading-relaxed">
              The 3D WebGL engine encountered a rendering limitation or missing hardware acceleration on your GPU device.
            </p>
            <div className="pt-2 flex justify-center gap-3">
              <button
                onClick={() => {
                  this.setState({ hasError: false });
                  this.props.onFallback();
                }}
                className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-xs font-semibold rounded-lg shadow flex items-center gap-2"
              >
                <RefreshCw size={14} />
                Switch to 2D Blueprint Mode
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * Redesigned 3D Office App Console.
 * Features a Dual-Mode / Triple-Mode Engine Switcher:
 * 1. 3D Cyber Isometric (Three.js / React Three Fiber)
 * 2. 3D Full Orbit View (Babylon.js Engine)
 * 3. 2D Tactical Blueprint (High-contrast Interactive Vector Canvas)
 */
export function Office() {
  const [engineMode, setEngineMode] = useState<EngineMode>('openoffice');
  const [selectedAgent, setSelectedAgent] = useState<MockAgent3D | null>(null);
  const [babylonSelection, setBabylonSelection] = useState<SelectionState>({ type: null });
  const [toast, setToast] = useState<{ message: string; type: 'info' | 'success' } | null>(null);

  const showToast = useCallback((message: string, type: 'info' | 'success' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const handleAgentClick = useCallback((agent: MockAgent3D) => {
    setSelectedAgent(agent);
    setBabylonSelection({ type: null });
    showToast(`Inspecting agent ${agent.name} (${agent.role})`, 'info');
  }, [showToast]);

  const handleBackgroundClick = useCallback(() => {
    setSelectedAgent(null);
    setBabylonSelection({ type: null });
  }, []);

  const handleBabylonSelectionChange = useCallback((sel: SelectionState) => {
    setBabylonSelection(sel);
    if (sel.type === 'agent' && sel.agent) {
      const matched = [...mockAgents3D, managerAgent].find(
        (a) => a.name.toLowerCase() === sel.agent?.name.toLowerCase() || a.id === sel.agent?.id
      );
      if (matched) setSelectedAgent(matched);
    } else {
      setSelectedAgent(null);
    }
  }, []);

  const handleEngineModeChange = useCallback((mode: EngineMode) => {
    setEngineMode(mode);
    const modeNames: Record<EngineMode, string> = {
      openoffice: 'OpenOffice 2D Canvas Engine',
      realistic: '2D Realistic (NvLabsOrg)',
      '2d': '2D Tactical Blueprint',
      r3f: '3D Cyber Isometric (R3F)',
      babylon: '3D Orbit View (Babylon)',
    };
    showToast(`Switched workspace mode to ${modeNames[mode]}`, 'success');
  }, [showToast]);

  const handleCameraPreset = useCallback((preset: 'overview' | 'dev' | 'manager') => {
    if (preset === 'manager') {
      setSelectedAgent(managerAgent);
      showToast('Camera focused on Executive Suite Manager Cabin', 'info');
    } else if (preset === 'dev') {
      const devAgent = mockAgents3D.find((a) => a.zoneId === 'development');
      if (devAgent) setSelectedAgent(devAgent);
      showToast('Camera focused on Development Zone', 'info');
    } else {
      setSelectedAgent(null);
      showToast('Reset camera view to Overview', 'info');
    }
  }, [showToast]);

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col relative -m-6 bg-[#030712] overflow-hidden select-none">
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-14 right-5 z-50 px-4 py-2.5 rounded-xl border border-primary-500/40 bg-primary-950/80 backdrop-blur-md text-xs font-semibold text-primary-300 shadow-2xl flex items-center gap-2 animate-fadeIn">
          <CheckCircle2 size={16} className="text-primary-400" />
          {toast.message}
        </div>
      )}

      {/* Top HUD Bar with Engine Switcher */}
      <StatsBar
        engineMode={engineMode}
        onEngineModeChange={handleEngineModeChange}
        onCameraPreset={handleCameraPreset}
      />

      {/* Active Engine Workspace Display with WebGL Error Boundary */}
      <div className="flex-1 relative w-full h-full pt-12">
        <OfficeErrorBoundary onFallback={() => setEngineMode('2d')}>
          {/* Mode 0: OpenOffice 2D Canvas Engine (Exact OpenOffice Engine) */}
          {engineMode === 'openoffice' && (
            <PixelOfficeConsole
              selectedAgent={selectedAgent}
              onAgentClick={handleAgentClick}
              onBackgroundClick={handleBackgroundClick}
            />
          )}

          {/* Mode 1: 2D Realistic Office (NvLabsOrg Imported) */}
          {engineMode === 'realistic' && (
            <RealisticOfficeView
              selectedAgent={selectedAgent}
              onAgentClick={handleAgentClick}
              onBackgroundClick={handleBackgroundClick}
            />
          )}

          {/* Mode 2: 2D Tactical Blueprint (Interactive Vector Grid) */}
          {engineMode === '2d' && (
            <TacticalBlueprint
              selectedAgent={selectedAgent}
              onAgentClick={handleAgentClick}
              onBackgroundClick={handleBackgroundClick}
            />
          )}

          {/* Mode 3: 3D Cyber Isometric (React Three Fiber) */}
          {engineMode === 'r3f' && (
            <OfficeScene
              selectedAgent={selectedAgent}
              onAgentClick={handleAgentClick}
              onBackgroundClick={handleBackgroundClick}
            />
          )}

          {/* Mode 4: 3D Full Orbit (Babylon.js) */}
          {engineMode === 'babylon' && (
            <BabylonCanvas onSelectionChange={handleBabylonSelectionChange} />
          )}
        </OfficeErrorBoundary>

        {/* Unified Right Sidebar Panel for Selected Agent */}
        {selectedAgent && (
          <AgentDetailSidebar
            agent={selectedAgent}
            onClose={() => setSelectedAgent(null)}
            onShowToast={showToast}
          />
        )}

        {/* Babylon Room Selection Panel */}
        {engineMode === 'babylon' && babylonSelection.type === 'room' && babylonSelection.room && (
          <RoomPanel
            room={babylonSelection.room}
            agentCount={babylonSelection.agentCount ?? 0}
            onClose={() => setBabylonSelection({ type: null })}
          />
        )}
      </div>
    </div>
  );
}
