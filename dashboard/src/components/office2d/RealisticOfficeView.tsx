import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { RealisticAvatar } from './RealisticAvatar';
import { mockAgents3D, managerAgent, status3DColors, statusLabels } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';
import { Layers, ZoomIn, ZoomOut, Maximize2, Check } from 'lucide-react';

interface RealisticOfficeViewProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onBackgroundClick?: () => void;
}

const OFFICE_THEMES = [
  { id: 'realistic', name: 'High-Res Studio', path: '/offices/realistic-office.png' },
  { id: 'cyberpunk', name: 'Cyberpunk HQ', path: '/offices/cyberpunk.jpeg' },
  { id: 'cozy', name: 'Modern Cozy', path: '/offices/modern-cozy.jpeg' },
  { id: 'sifi', name: 'Sci-Fi Lab', path: '/offices/sifi.jpeg' },
  { id: 'darkLegend', name: 'Dark Legend', path: '/offices/darkLegend.jpeg' },
];

const REALISTIC_SPRITES: Record<number, string> = {
  0: '/assets/characters/char_0.png',
  1: '/assets/characters/char_1.png',
  2: '/assets/characters/char_2.png',
  3: '/assets/characters/char_3.png',
  4: '/assets/characters/char_4.png',
  5: '/assets/characters/char_5.png',
  6: '/assets/characters/char_6.png',
};

const IMG_TOP = 16.7;
const IMG_SCALE = 0.667;

const p = (x: number, iy: number) => ({ x, y: IMG_TOP + iy * IMG_SCALE });

const DESK_POSITIONS = [
  // Top-left room (Planning)
  p(20.3, -8), p(29.8, -7.8), p(16.2, 17.5), p(28.5, 17.5),
  // Top-center room (Development)
  p(47, -7.5), p(55.77, -7.5), p(43.9, 18.9), p(46.7, 18.9),
  // Top-right room (QA & Security)
  p(73.5, -7), p(81.3, -7), p(72.7, 18), p(75.4, 18),
  // Mid-left room (Data)
  p(16.5, 44), p(20.2, 44), p(15.9, 54.7), p(18.5, 54.7),
  // Center (Meeting room)
  p(46.5, 45.5), p(51.4, 39), p(56, 45), p(51.5, 62.5),
  // Mid-right room (Automation)
  p(75.8, 44), p(87, 44), p(74.8, 54.3), p(77.5, 54.3),
  // Bottom-left room (Research)
  p(16.5, 87.3), p(24, 98), p(12.5, 117), p(27.4, 106),
  // Bottom-center room (Operations)
  p(46.8, 87), p(57.2, 87), p(45.3, 116.8), p(58.7, 116.65),
  // Bottom-right room (Support)
  p(76, 87), p(87, 87), p(86.1, 116.9), p(88.6, 116.5),
];

const ZONE_LABELS = [
  { name: 'Planning Zone', x: 23, y: IMG_TOP + -18.5 * IMG_SCALE, color: '#a855f7' },
  { name: 'Development Zone', x: 51, y: IMG_TOP + -18.5 * IMG_SCALE, color: '#22c55e' },
  { name: 'QA & Security Zone', x: 80, y: IMG_TOP + -18.5 * IMG_SCALE, color: '#f97316' },
  { name: 'Data Zone', x: 22.5, y: IMG_TOP + 27.8 * IMG_SCALE, color: '#06b6d4' },
  { name: 'Executive Suite', x: 52, y: IMG_TOP + 25.8 * IMG_SCALE, color: '#eab308' },
  { name: 'Automation Zone', x: 81, y: IMG_TOP + 27.8 * IMG_SCALE, color: '#3b82f6' },
  { name: 'Research Zone', x: 21, y: IMG_TOP + 71 * IMG_SCALE, color: '#ec4899' },
  { name: 'Operations Zone', x: 52, y: IMG_TOP + 71 * IMG_SCALE, color: '#84cc16' },
  { name: 'Support Zone', x: 81, y: IMG_TOP + 71 * IMG_SCALE, color: '#14b8a6' },
];

const ENTRANCE = { x: 50, y: IMG_TOP };

const HALL_TOP = p(50, 30);
const HALL_MID = p(50, 50);
const HALL_BOT = p(50, 75);
const HALL_LEFT_TOP = p(32, 30);
const HALL_LEFT_MID = p(32, 50);
const HALL_LEFT_BOT = p(32, 75);
const HALL_RIGHT_TOP = p(67, 30);
const HALL_RIGHT_MID = p(67, 50);
const HALL_RIGHT_BOT = p(67, 75);

const ZONE_PATHS: Record<number, Array<{ x: number; y: number }>> = {
  0: [HALL_TOP, HALL_LEFT_TOP], 1: [HALL_TOP, HALL_LEFT_TOP], 2: [HALL_TOP, HALL_LEFT_TOP], 3: [HALL_TOP, HALL_LEFT_TOP],
  4: [HALL_TOP], 5: [HALL_TOP], 6: [HALL_TOP], 7: [HALL_TOP],
  8: [HALL_TOP, HALL_RIGHT_TOP], 9: [HALL_TOP, HALL_RIGHT_TOP], 10: [HALL_TOP, HALL_RIGHT_TOP], 11: [HALL_TOP, HALL_RIGHT_TOP],
  12: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID], 13: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID], 14: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID], 15: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID],
  16: [HALL_TOP, HALL_MID], 17: [HALL_TOP, HALL_MID], 18: [HALL_TOP, HALL_MID], 19: [HALL_TOP, HALL_MID],
  20: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID], 21: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID], 22: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID], 23: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID],
  24: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID, HALL_LEFT_BOT], 25: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID, HALL_LEFT_BOT], 26: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID, HALL_LEFT_BOT], 27: [HALL_TOP, HALL_LEFT_TOP, HALL_LEFT_MID, HALL_LEFT_BOT],
  28: [HALL_TOP, HALL_MID, HALL_BOT], 29: [HALL_TOP, HALL_MID, HALL_BOT], 30: [HALL_TOP, HALL_MID, HALL_BOT], 31: [HALL_TOP, HALL_MID, HALL_BOT],
  32: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID, HALL_RIGHT_BOT], 33: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID, HALL_RIGHT_BOT], 34: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID, HALL_RIGHT_BOT], 35: [HALL_TOP, HALL_RIGHT_TOP, HALL_RIGHT_MID, HALL_RIGHT_BOT],
};

/**
 * Enhanced 2D Realistic Office View with Continuous Wandering Loop.
 * Agents walk in from the entrance to their desks, and periodically wander
 * to the Executive Suite meeting room, coffee break lounge, or peer desks.
 */
export function RealisticOfficeView({ selectedAgent, onAgentClick, onBackgroundClick }: RealisticOfficeViewProps) {
  const [activeTheme, setActiveTheme] = useState(OFFICE_THEMES[0]);
  const [statusFilter, setStatusFilter] = useState<'all' | 'working' | 'idle' | 'offline'>('all');
  const [zoomScale, setZoomScale] = useState(1);
  const [showThemeMenu, setShowThemeMenu] = useState(false);

  const allAgents = useMemo(() => [managerAgent, ...mockAgents3D], []);

  const filteredAgents = useMemo(() => {
    if (statusFilter === 'all') return allAgents;
    return allAgents.filter((a) => a.status === statusFilter);
  }, [allAgents, statusFilter]);

  return (
    <div
      onClick={onBackgroundClick}
      className="w-full h-full relative overflow-hidden bg-[#05070d] flex items-center justify-center p-2 select-none"
    >
      {/* Top Floating Control UI */}
      <div className="absolute top-16 left-6 z-20 flex items-center gap-2 pointer-events-auto">
        {/* Theme Picker Switcher Dropdown */}
        <div className="relative">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowThemeMenu((v) => !v);
            }}
            className="px-3 py-1.5 rounded-xl bg-slate-900/90 border border-white/10 hover:border-primary-500/50 text-xs font-medium text-white shadow-xl backdrop-blur-md flex items-center gap-2 transition-all"
          >
            <Layers size={14} className="text-primary-400" />
            <span>{activeTheme.name}</span>
          </button>

          {showThemeMenu && (
            <div className="absolute top-full left-0 mt-2 w-44 rounded-xl bg-slate-950/95 border border-white/10 shadow-2xl backdrop-blur-xl p-1.5 space-y-1 z-30 animate-fadeIn">
              {OFFICE_THEMES.map((theme) => (
                <button
                  key={theme.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setActiveTheme(theme);
                    setShowThemeMenu(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center justify-between transition-colors ${
                    activeTheme.id === theme.id
                      ? 'bg-primary-500/20 text-primary-300 font-semibold'
                      : 'text-gray-300 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <span>{theme.name}</span>
                  {activeTheme.id === theme.id && <Check size={12} className="text-primary-400" />}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Status Filter Badges */}
        <div className="flex items-center bg-slate-900/90 border border-white/10 rounded-xl p-1 shadow-xl backdrop-blur-md text-xs">
          {(['all', 'working', 'idle', 'offline'] as const).map((st) => (
            <button
              key={st}
              onClick={(e) => {
                e.stopPropagation();
                setStatusFilter(st);
              }}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-medium capitalize transition-all ${
                statusFilter === st
                  ? 'bg-primary-500 text-white font-semibold shadow'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Top Right Zoom Controls */}
      <div className="absolute top-16 right-6 z-20 flex items-center gap-1.5 bg-slate-900/90 border border-white/10 rounded-xl p-1 shadow-xl backdrop-blur-md text-xs pointer-events-auto">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setZoomScale((z) => Math.min(z + 0.15, 1.4));
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Zoom In"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setZoomScale((z) => Math.max(z - 0.15, 0.8));
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Zoom Out"
        >
          <ZoomOut size={14} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setZoomScale(1);
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Reset Fit"
        >
          <Maximize2 size={14} />
        </button>
      </div>

      {/* Main Floor Plan Container */}
      <div
        style={{ transform: `scale(${zoomScale})` }}
        className="relative w-full max-w-6xl aspect-[3/2] rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-[#090c15] transition-transform duration-300 ease-out"
      >
        {/* Floor Background Image */}
        <img
          src={activeTheme.path}
          alt={activeTheme.name}
          className="absolute inset-0 w-full h-[106%] object-cover object-center select-none pointer-events-none transition-all duration-500"
          onError={(e) => {
            (e.target as HTMLImageElement).src = '/offices/realistic-office.png';
          }}
        />

        {/* Zone Overlay Badges */}
        {ZONE_LABELS.map((z) => (
          <div
            key={z.name}
            style={{
              position: 'absolute',
              left: `${z.x}%`,
              top: `${z.y}%`,
              transform: 'translateX(-50%)',
              backgroundColor: `${z.color}35`,
              borderColor: `${z.color}80`,
              boxShadow: `0 0 12px ${z.color}30`,
            }}
            className="px-2.5 py-0.5 rounded-full border text-[10px] font-bold text-white whitespace-nowrap pointer-events-none backdrop-blur-sm tracking-wide uppercase"
          >
            <span style={{ color: z.color }} className="mr-1">●</span>
            {z.name}
          </div>
        ))}

        {/* Workstation Desk Spot Highlights */}
        {DESK_POSITIONS.map((desk, idx) => (
          <div
            key={`desk-${idx}`}
            style={{
              position: 'absolute',
              left: `${desk.x}%`,
              top: `${desk.y}%`,
              transform: 'translate(-50%, -50%)',
            }}
            className="w-3 h-3 rounded-full bg-primary-500/20 border border-primary-400/40 animate-pulse pointer-events-none"
          />
        ))}

        {/* Agent Character Sprites with Dynamic Pathfinding & Wandering */}
        {filteredAgents.map((agent, i) => {
          const originalIdx = allAgents.findIndex((a) => a.id === agent.id);
          const deskIdx = (originalIdx >= 0 ? originalIdx : i) % DESK_POSITIONS.length;
          const desk = DESK_POSITIONS[deskIdx];
          const isSelected = selectedAgent?.id === agent.id;
          const palette = i % 7;

          return (
            <AgentSpriteItem
              key={agent.id}
              agent={agent}
              desk={desk}
              path={ZONE_PATHS[deskIdx] ?? []}
              isSelected={isSelected}
              palette={palette}
              delay={i * 0.3}
              onSelect={() => onAgentClick(agent)}
            />
          );
        })}
      </div>
    </div>
  );
}

function AgentSpriteItem({
  agent,
  desk,
  path,
  isSelected,
  palette,
  delay,
  onSelect,
}: {
  agent: MockAgent3D;
  desk: { x: number; y: number };
  path: Array<{ x: number; y: number }>;
  isSelected: boolean;
  palette: number;
  delay: number;
  onSelect: () => void;
}) {
  const [pos, setPos] = useState<{ x: number; y: number }>(ENTRANCE);
  const [isWalking, setIsWalking] = useState(true);
  const [direction, setDirection] = useState<0 | 1 | 2>(2); // 0=front, 1=back, 2=side
  const [hovered, setHovered] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const statusColor = status3DColors[agent.status] ?? '#9ca3af';

  // Helper to compute facing direction based on movement delta
  const updateDirection = useCallback((from: { x: number; y: number }, to: { x: number; y: number }) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    if (Math.abs(dy) > Math.abs(dx)) {
      setDirection(dy > 0 ? 0 : 1);
    } else {
      setDirection(2);
    }
  }, []);

  // Continuous Wandering Behavior Loop
  const startWanderLoop = useCallback((currentPos: { x: number; y: number }) => {
    // Meeting room / Lounge locations for wandering
    const meetingSpot = DESK_POSITIONS[16] ?? ENTRANCE;
    const dataLounge = DESK_POSITIONS[12] ?? ENTRANCE;
    const targetWanderSpot = Math.random() > 0.5 ? meetingSpot : dataLounge;

    // Staggered wander timing: idle agents wander more frequently than working agents
    const pauseBeforeWander = agent.status === 'working' ? 12000 + Math.random() * 15000 : 4000 + Math.random() * 6000;

    timerRef.current = setTimeout(() => {
      // 1. Walk from current position to meeting/break spot
      setIsWalking(true);
      updateDirection(currentPos, targetWanderSpot);
      setPos(targetWanderSpot);

      // 2. Stay at meeting spot chatting/break for 4 to 7 seconds
      const breakDuration = 4000 + Math.random() * 3000;
      timerRef.current = setTimeout(() => {
        setIsWalking(false);

        // 3. Walk back to assigned workstation desk
        timerRef.current = setTimeout(() => {
          setIsWalking(true);
          updateDirection(targetWanderSpot, desk);
          setPos(desk);

          // 4. Arrive at desk and repeat wander loop
          timerRef.current = setTimeout(() => {
            setIsWalking(false);
            setDirection(0);
            startWanderLoop(desk);
          }, 1800);
        }, breakDuration);
      }, 1800);
    }, pauseBeforeWander);
  }, [agent.status, desk, updateDirection]);

  // Initial Entrance Walk-in Sequence
  useEffect(() => {
    const fullPath = [ENTRANCE, ...path, desk];
    let stepIdx = 0;

    const walkNext = () => {
      stepIdx++;
      if (stepIdx >= fullPath.length) {
        // Arrived at workstation desk
        setIsWalking(false);
        setDirection(0);
        // Start continuous wander loop after initial arrival
        startWanderLoop(desk);
        return;
      }
      const prevPos = fullPath[stepIdx - 1];
      const nextPos = fullPath[stepIdx];
      if (prevPos && nextPos) {
        updateDirection(prevPos, nextPos);
        setPos(nextPos);
      }
      timerRef.current = setTimeout(walkNext, 650);
    };

    timerRef.current = setTimeout(() => {
      setPos(fullPath[0] ?? ENTRANCE);
      timerRef.current = setTimeout(walkNext, 650);
    }, delay * 1000);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [desk, path, delay, updateDirection, startWanderLoop]);

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'absolute',
        left: `${pos.x}%`,
        top: `${pos.y}%`,
        transform: 'translate(-50%, -100%)',
        transition: 'left 0.65s ease-in-out, top 0.65s ease-in-out',
      }}
      className="cursor-pointer z-10 group"
    >
      {/* Sprite Container */}
      <div
        className={`transition-all duration-300 ${
          isSelected ? 'scale-125 -translate-y-1' : 'hover:scale-110'
        }`}
        style={{
          filter: isSelected
            ? `drop-shadow(0 0 10px ${statusColor})`
            : agent.status === 'working'
            ? `drop-shadow(0 0 5px ${statusColor}a0)`
            : 'none',
        }}
      >
        <RealisticAvatar
          src={REALISTIC_SPRITES[palette] ?? REALISTIC_SPRITES[0] ?? '/assets/characters/char_0.png'}
          direction={direction}
          walking={isWalking}
          size={52}
        />
      </div>

      {/* Ground Status Ring */}
      <div
        style={{
          backgroundColor: statusColor,
          boxShadow: `0 0 8px ${statusColor}`,
        }}
        className="w-2.5 h-2.5 rounded-full absolute -bottom-1 left-1/2 -translate-x-1/2 border border-black/40"
      />

      {/* Tooltip Hover Label */}
      {(hovered || isSelected) && (
        <div
          style={{ borderColor: `${statusColor}80` }}
          className="absolute bottom-[calc(100%+6px)] left-1/2 -translate-x-1/2 px-2.5 py-1 rounded-lg bg-slate-950/90 backdrop-blur-md border text-[10px] text-white whitespace-nowrap shadow-xl z-30 flex items-center gap-1.5 animate-fadeIn"
        >
          <span className="font-semibold">{agent.name}</span>
          <span className="text-gray-400 text-[9px]">({agent.role})</span>
          <span style={{ color: statusColor }} className="text-[8px]">● {statusLabels[agent.status]}</span>
        </div>
      )}
    </div>
  );
}
