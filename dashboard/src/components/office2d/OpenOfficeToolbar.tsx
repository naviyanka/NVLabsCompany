import { useState } from 'react';
import type { LightingMode, SimSpeed } from './types';
import { retroAudio } from '@/utils/retroAudio';
import {
  Video,
  Coffee,
  Zap,
  Compass,
  Play,
  Pause,
  Sun,
  Moon,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
  Search,
} from 'lucide-react';

interface OpenOfficeToolbarProps {
  simSpeed: SimSpeed;
  onSimSpeedChange: (speed: SimSpeed) => void;
  lighting: LightingMode;
  onLightingChange: (lighting: LightingMode) => void;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onResetZoom: () => void;
  onAllHands: () => void;
  onCoffeeBreak: () => void;
  onSprintRush: () => void;
  onFreeRoam: () => void;
  searchFilter: string;
  onSearchFilterChange: (val: string) => void;
  departmentFilter: string | null;
  onDepartmentFilterChange: (val: string | null) => void;
}

export function OpenOfficeToolbar({
  simSpeed,
  onSimSpeedChange,
  lighting,
  onLightingChange,
  zoom,
  onZoomChange,
  onResetZoom,
  onAllHands,
  onCoffeeBreak,
  onSprintRush,
  onFreeRoam,
  searchFilter,
  onSearchFilterChange,
  departmentFilter,
  onDepartmentFilterChange,
}: OpenOfficeToolbarProps) {
  const [isMuted, setIsMuted] = useState(retroAudio.isMuted());

  const handleToggleMute = () => {
    const muted = retroAudio.toggleMute();
    setIsMuted(muted);
  };

  return (
    <header className="h-14 px-4 bg-[#0A0A0B]/95 backdrop-blur border-b border-white/[0.08] flex items-center justify-between gap-3 shrink-0 z-20 select-none">
      <div className="flex items-center gap-3">
        <div className="hidden lg:flex items-center gap-1.5 pl-2 border-l border-white/[0.08]">
          <button
            onClick={onAllHands}
            title="Summon all agents to War Room conference table"
            className="px-2.5 py-1 rounded-md bg-[#A855F7]/10 hover:bg-[#A855F7]/20 border border-[#A855F7]/30 text-[#C084FC] text-xs font-mono flex items-center gap-1.5 transition-colors"
          >
            <Video className="w-3.5 h-3.5" />
            All-Hands Sync
          </button>

          <button
            onClick={onCoffeeBreak}
            title="Send all agents on a coffee and arcade break"
            className="px-2.5 py-1 rounded-md bg-[#F59E0B]/10 hover:bg-[#F59E0B]/20 border border-[#F59E0B]/30 text-[#FBBF24] text-xs font-mono flex items-center gap-1.5 transition-colors"
          >
            <Coffee className="w-3.5 h-3.5" />
            Coffee Break
          </button>

          <button
            onClick={onSprintRush}
            title="Dispatch everyone back to workstation desks at sprint velocity"
            className="px-2.5 py-1 rounded-md bg-[#10B981]/10 hover:bg-[#10B981]/20 border border-[#10B981]/30 text-[#34D399] text-xs font-mono flex items-center gap-1.5 transition-colors"
          >
            <Zap className="w-3.5 h-3.5" />
            Sprint Rush
          </button>

          <button
            onClick={onFreeRoam}
            title="Let all idle agents freely roam around the office"
            className="px-2.5 py-1 rounded-md bg-[#38BDF8]/10 hover:bg-[#38BDF8]/20 border border-[#38BDF8]/30 text-[#38BDF8] text-xs font-mono flex items-center gap-1.5 transition-colors"
          >
            <Compass className="w-3.5 h-3.5" />
            Free Roam
          </button>
        </div>
      </div>

      {/* Right: Search, Filter, Sim Speed, Lighting, Sound & Zoom */}
      <div className="flex items-center gap-2">
        {/* Search Agent */}
        <div className="relative hidden sm:block">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchFilter}
            onChange={(e) => onSearchFilterChange(e.target.value)}
            placeholder="Search agent..."
            className="w-32 md:w-40 pl-8 pr-2.5 py-1 rounded-md bg-white/[0.04] border border-white/[0.08] text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Department Filter */}
        <select
          value={departmentFilter || ''}
          onChange={(e) => onDepartmentFilterChange(e.target.value || null)}
          className="hidden md:block py-1 px-2.5 rounded-md bg-white/[0.04] border border-white/[0.08] text-xs text-[#E2E8F0] font-mono focus:outline-none focus:border-[#FFB020]"
        >
          <option value="">All Zones</option>
          <option value="development">Engineering Pod</option>
          <option value="data-automation">Data & Automation</option>
          <option value="qa-security">Security & QA</option>
          <option value="research">Research Lab</option>
          <option value="operations">Operations Hub</option>
          <option value="breakroom">Breakroom & Arcade</option>
          <option value="zen-garden">Zen Garden</option>
        </select>

        {/* Speed Controls: Pause, 1x, 2x, 4x */}
        <div className="flex items-center p-0.5 rounded-md bg-white/[0.04] border border-white/[0.08]">
          <button
            onClick={() => onSimSpeedChange(simSpeed === 0 ? 1 : 0)}
            title={simSpeed === 0 ? 'Resume simulation' : 'Pause simulation'}
            className={`p-1 rounded text-xs transition-colors ${
              simSpeed === 0 ? 'bg-[#EF4444] text-white' : 'text-[#9C9C9F] hover:text-white'
            }`}
          >
            {simSpeed === 0 ? <Play className="w-3.5 h-3.5 fill-current" /> : <Pause className="w-3.5 h-3.5" />}
          </button>
          {([1, 2, 4] as SimSpeed[]).map((spd) => (
            <button
              key={spd}
              onClick={() => onSimSpeedChange(spd)}
              className={`px-1.5 py-0.5 rounded text-[11px] font-mono font-bold transition-colors ${
                simSpeed === spd ? 'bg-[#FFB020] text-black' : 'text-[#9C9C9F] hover:text-white'
              }`}
            >
              {spd}x
            </button>
          ))}
        </div>

        {/* Lighting Mode */}
        <div className="flex items-center p-0.5 rounded-md bg-white/[0.04] border border-white/[0.08]">
          <button
            onClick={() => onLightingChange('day')}
            title="Day Lighting"
            className={`p-1 rounded text-xs transition-colors ${
              lighting === 'day' ? 'bg-[#FFB020] text-black' : 'text-[#9C9C9F] hover:text-white'
            }`}
          >
            <Sun className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onLightingChange('cyberpunk')}
            title="Cyberpunk Neon"
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold transition-colors ${
              lighting === 'cyberpunk'
                ? 'bg-[#8B5CF6] text-white'
                : 'text-[#9C9C9F] hover:text-white'
            }`}
          >
            NEON
          </button>
          <button
            onClick={() => onLightingChange('night')}
            title="Night Shift"
            className={`p-1 rounded text-xs transition-colors ${
              lighting === 'night' ? 'bg-[#38BDF8] text-black' : 'text-[#9C9C9F] hover:text-white'
            }`}
          >
            <Moon className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Sound Toggle */}
        <button
          onClick={handleToggleMute}
          title={isMuted ? 'Unmute 8-bit sound effects' : 'Mute 8-bit sound effects'}
          className={`p-1.5 rounded-md border text-xs transition-colors ${
            isMuted
              ? 'border-white/[0.08] text-[#6B6B6E] hover:text-white'
              : 'border-[#FFB020]/40 bg-[#FFB020]/10 text-[#FFB020]'
          }`}
        >
          {isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
        </button>

        {/* Zoom Controls */}
        <div className="flex items-center p-0.5 rounded-md bg-white/[0.04] border border-white/[0.08]">
          <button
            onClick={() => onZoomChange(Math.max(zoom * 0.85, 0.5))}
            title="Zoom Out"
            className="p-1 text-[#9C9C9F] hover:text-white"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onResetZoom}
            title="Reset View"
            className="px-1 text-[10px] font-mono text-[#9C9C9F] hover:text-white"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            onClick={() => onZoomChange(Math.min(zoom * 1.15, 2.2))}
            title="Zoom In"
            className="p-1 text-[#9C9C9F] hover:text-white"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
}
