import { Users, Activity, Coffee, AlertCircle, WifiOff, Box, Eye, Layout, Compass } from 'lucide-react';
import { mockAgents3D, managerAgent, status3DColors } from '@/config/office3dLayout';

export type EngineMode = 'openoffice' | 'realistic' | '2d' | 'r3f' | 'babylon';

interface StatsBarProps {
  engineMode: EngineMode;
  onEngineModeChange: (mode: EngineMode) => void;
  onCameraPreset?: (preset: 'overview' | 'dev' | 'manager') => void;
}

/**
 * Top HUD Bar overlay for the Office App.
 * Displays real-time agent metrics, camera presets, and the Engine Switcher tabs.
 */
export function StatsBar({ engineMode, onEngineModeChange, onCameraPreset }: StatsBarProps) {
  const allAgents = [...mockAgents3D, managerAgent];
  const total = allAgents.length;
  const active = allAgents.filter((a) => a.status === 'working').length;
  const idle = allAgents.filter((a) => a.status === 'idle').length;
  const review = allAgents.filter((a) => a.status === 'review').length;
  const offline = allAgents.filter((a) => a.status === 'offline').length;

  const stats = [
    { label: 'Total', value: total, icon: Users, color: '#ffffff' },
    { label: 'Working', value: active, icon: Activity, color: status3DColors.working },
    { label: 'Idle', value: idle, icon: Coffee, color: status3DColors.idle },
    { label: 'Review', value: review, icon: AlertCircle, color: status3DColors.review },
    { label: 'Offline', value: offline, icon: WifiOff, color: status3DColors.offline },
  ];

  return (
    <div className="absolute top-0 left-0 right-0 z-10 pointer-events-none">
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#080d1a]/90 backdrop-blur-md border-b border-white/[0.08]">
        {/* Left: Agent Metrics Telemetry */}
        <div className="flex items-center gap-4 pointer-events-auto">
          <div className="flex items-center gap-2 pr-3 border-r border-white/10">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-bold text-white uppercase tracking-wider">OFFICE CONSOLE</span>
          </div>

          <div className="hidden sm:flex items-center gap-4">
            {stats.map((stat) => (
              <div key={stat.label} className="flex items-center gap-1.5 text-xs">
                <stat.icon size={13} style={{ color: stat.color }} />
                <span className="text-gray-400">{stat.label}:</span>
                <span className="font-semibold font-mono" style={{ color: stat.color }}>
                  {stat.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Camera Presets & Engine Mode Switcher */}
        <div className="flex items-center gap-3 pointer-events-auto">
          {/* Camera Quick Presets (Only visible in 3D modes) */}
          {(engineMode === 'r3f' || engineMode === 'babylon') && onCameraPreset && (
            <div className="hidden lg:flex items-center gap-1 bg-dark-surface/80 border border-white/[0.08] rounded-lg p-1 text-xs">
              <button
                onClick={() => onCameraPreset('overview')}
                className="px-2 py-1 rounded text-gray-300 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-1"
                title="Overview Perspective"
              >
                <Compass size={12} />
                Overview
              </button>
              <button
                onClick={() => onCameraPreset('dev')}
                className="px-2 py-1 rounded text-gray-300 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-1"
                title="Focus Dev Zone"
              >
                <Eye size={12} />
                Dev Zone
              </button>
              <button
                onClick={() => onCameraPreset('manager')}
                className="px-2 py-1 rounded text-gray-300 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-1"
                title="Executive Cabin"
              >
                <Box size={12} />
                Cabin
              </button>
            </div>
          )}

          {/* Engine Mode Switcher Tabs */}
          <div className="flex items-center bg-dark-bg/80 border border-white/[0.1] rounded-xl p-1 shadow-inner text-xs font-medium">
            <button
              onClick={() => onEngineModeChange('openoffice')}
              className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                engineMode === 'openoffice'
                  ? 'bg-primary-500 text-white shadow-md font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Layout size={13} />
              OpenOffice 2D Canvas
            </button>
            <button
              onClick={() => onEngineModeChange('realistic')}
              className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                engineMode === 'realistic'
                  ? 'bg-primary-500 text-white shadow-md font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Layout size={13} />
              2D Realistic (NvLabsOrg)
            </button>
            <button
              onClick={() => onEngineModeChange('2d')}
              className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                engineMode === '2d'
                  ? 'bg-primary-500 text-white shadow-md font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Layout size={13} />
              2D Tactical Blueprint
            </button>
            <button
              onClick={() => onEngineModeChange('r3f')}
              className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                engineMode === 'r3f'
                  ? 'bg-primary-500 text-white shadow-md font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Box size={13} />
              3D Cyber (R3F)
            </button>
            <button
              onClick={() => onEngineModeChange('babylon')}
              className={`px-3 py-1 rounded-lg transition-all flex items-center gap-1.5 ${
                engineMode === 'babylon'
                  ? 'bg-primary-500 text-white shadow-md font-semibold'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Compass size={13} />
              3D Orbit (Babylon)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
