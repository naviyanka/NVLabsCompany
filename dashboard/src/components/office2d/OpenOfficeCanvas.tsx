import { useEffect, useRef, useState, useCallback } from 'react';
import type { Agent2D, EnvironmentalProp2D, Furniture2D, InteractivePOI, LightingMode, SimSpeed, Desk2D } from './types';
import { OFFICE_2D_LAYOUT } from './office2DMap';
import { drawOfficeFloor } from './floorRenderer';
import {
  drawDeskShadow,
  draw3DDesk,
  drawChairShadow,
  draw3DChair,
  drawConferenceTable,
  drawRoundCafeTable,
  drawEspressoMachine,
  drawArcadeCabinet,
  drawWaterCooler,
  drawVendingMachine,
  drawServerRack3D,
  drawPlushSofa,
  drawCoffeeTable,
  drawZenBench,
  drawZenFountain,
  drawPottedPlant,
  drawWhiteboard,
  drawBookshelf,
  drawEnvironmentalProp,
} from './furnitureRenderer';
import { drawOfficeLighting } from './lightingEngine';
import { drawPixelAgent } from './agentSprites';
import {
  updateAgentsSimulation,
  navigateToPoint,
  navigateToDesk,
} from './movementEngine';
import { retroAudio } from '@/utils/retroAudio';
import {
  Monitor,
  Cpu,
  Zap,
  Activity,
  Sparkles,
  ArrowRight,
} from 'lucide-react';

interface OpenOfficeCanvasProps {
  agents: Agent2D[];
  onAgentsChange: (agents: Agent2D[]) => void;
  selectedAgentId: string | null;
  onSelectAgent: (agent: Agent2D | null) => void;
  onSelectPoi: (poi: InteractivePOI | null) => void;
  simSpeed: SimSpeed;
  lighting: LightingMode;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  searchFilter: string;
  departmentFilter: string | null;
}

type RenderEntity =
  | { type: 'desk'; data: Desk2D; sortY: number }
  | { type: 'chair'; data: { id: string; x: number; y: number; facing: 'down' | 'up' | 'left' | 'right'; isOccupied: boolean; isExecutive: boolean }; sortY: number }
  | { type: 'furniture'; data: Furniture2D; sortY: number }
  | { type: 'poi'; data: InteractivePOI; sortY: number }
  | { type: 'prop'; data: EnvironmentalProp2D; sortY: number }
  | { type: 'agent'; data: Agent2D; sortY: number };

export function OpenOfficeCanvas({
  agents,
  onAgentsChange,
  selectedAgentId,
  onSelectAgent,
  onSelectPoi,
  simSpeed,
  lighting,
  zoom,
  onZoomChange,
  searchFilter,
  departmentFilter,
}: OpenOfficeCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Pan offsets
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Hover states
  const [hoveredAgentId, setHoveredAgentId] = useState<string | null>(null);
  const [hoveredPoiId, setHoveredPoiId] = useState<string | null>(null);
  const [hoveredDeskId, setHoveredDeskId] = useState<string | null>(null);

  // Refs for animation loop
  const agentsRef = useRef<Agent2D[]>(agents);
  agentsRef.current = agents;
  const lastTimeRef = useRef<number>(performance.now());
  const reqIdRef = useRef<number>(0);

  // Center the office map initially on mount
  useEffect(() => {
    if (containerRef.current) {
      const { clientWidth, clientHeight } = containerRef.current;
      const initialPanX = (clientWidth - OFFICE_2D_LAYOUT.width * zoom) / 2;
      const initialPanY = (clientHeight - OFFICE_2D_LAYOUT.height * zoom) / 2;
      setPan({ x: initialPanX, y: initialPanY });
    }
  }, []);

  // Main 60 FPS Unified Depth Render & Simulation Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) return;

    const render = (time: number) => {
      const deltaMs = Math.min(time - lastTimeRef.current, 50); // clamp delta
      lastTimeRef.current = time;
      const now = Date.now();

      // 1. Advance agent simulation
      if (simSpeed > 0) {
        const updatedAgents = updateAgentsSimulation(agentsRef.current, deltaMs, simSpeed);
        agentsRef.current = updatedAgents;
        if (Math.random() < 0.25) {
          onAgentsChange(updatedAgents);
        }
      }

      // 2. Clear canvas viewport
      ctx.save();
      ctx.fillStyle = '#060608';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Apply Pan & Zoom Transformation
      ctx.translate(pan.x, pan.y);
      ctx.scale(zoom, zoom);

      // Crisp pixel-art mode
      ctx.imageSmoothingEnabled = false;

      // 3. Render Architectural Floors & Walls
      drawOfficeFloor(ctx, OFFICE_2D_LAYOUT);

      // Filter visible agents
      const visibleAgents = [...agentsRef.current].filter((a) => {
        if (searchFilter && !a.name.toLowerCase().includes(searchFilter.toLowerCase())) {
          return false;
        }
        if (departmentFilter && a.zoneId !== departmentFilter) {
          return false;
        }
        return true;
      });

      // 4. UNIFIED CONTACT SHADOW PASS
      // Render all contact shadows with rich ambient occlusion and directional blur
      OFFICE_2D_LAYOUT.desks.forEach((desk) => {
        drawDeskShadow(ctx, desk);
        // Desk chair shadow
        drawChairShadow(ctx, desk.seatX - 10, desk.seatY - 10);
      });

      OFFICE_2D_LAYOUT.furniture.forEach((f) => {
        if (f.type === 'chair') {
          drawChairShadow(ctx, f.x, f.y);
        } else if (f.type === 'plant') {
          // Plant canopy ground shadow
          ctx.save();
          ctx.shadowColor = 'rgba(0, 0, 0, 0.8)';
          ctx.shadowBlur = 8;
          ctx.shadowOffsetY = 3;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
          ctx.beginPath();
          ctx.ellipse(f.x + f.width / 2, f.y + f.height - 2, f.width * 0.45, 6, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        } else if (f.type === 'sofa') {
          // Sofa wide contact shadow
          ctx.save();
          ctx.shadowColor = 'rgba(0, 0, 0, 0.85)';
          ctx.shadowBlur = 10;
          ctx.shadowOffsetY = 4;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
          ctx.beginPath();
          ctx.roundRect(f.x - 2, f.y + f.height - 6, f.width + 4, 12, 4);
          ctx.fill();
          ctx.restore();
        } else if (f.type === 'table') {
          // Conference & Coffee table shadow
          ctx.save();
          ctx.shadowColor = 'rgba(0, 0, 0, 0.85)';
          ctx.shadowBlur = 10;
          ctx.shadowOffsetY = 4;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
          ctx.beginPath();
          ctx.roundRect(f.x - 3, f.y + f.height - 8, f.width + 6, 14, 4);
          ctx.fill();
          ctx.restore();
        } else if (f.type === 'server_rack') {
          // Server rack deep foundation shadow
          ctx.save();
          ctx.shadowColor = 'rgba(0, 0, 0, 0.9)';
          ctx.shadowBlur = 12;
          ctx.shadowOffsetY = 5;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
          ctx.beginPath();
          ctx.roundRect(f.x - 2, f.y + f.height - 6, f.width + 4, 12, 3);
          ctx.fill();
          ctx.restore();
        }
      });

      // POI ground shadows
      OFFICE_2D_LAYOUT.pois.forEach((poi) => {
        ctx.save();
        ctx.shadowColor = 'rgba(0, 0, 0, 0.75)';
        ctx.shadowBlur = 8;
        ctx.shadowOffsetY = 3;
        ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
        if (poi.type === 'fountain') {
          ctx.beginPath();
          ctx.arc(poi.x + poi.width / 2, poi.y + poi.height / 2 + 4, poi.width / 2 + 3, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.beginPath();
          ctx.roundRect(poi.x - 2, poi.y + poi.height - 6, poi.width + 4, 12, 3);
          ctx.fill();
        }
        ctx.restore();
      });

      visibleAgents.forEach((agent) => {
        // Agent soft directional shadow with real blur filter
        ctx.save();
        ctx.shadowColor = 'rgba(0, 0, 0, 0.7)';
        ctx.shadowBlur = 6;
        ctx.shadowOffsetY = 2;
        ctx.beginPath();
        ctx.ellipse(agent.x, agent.y + 3, 11, 4.5, 0, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
        ctx.fill();
        ctx.restore();
      });

      // 5. CONSTRUCT & SORT UNIFIED DEPTH RENDER QUEUE
      const renderQueue: RenderEntity[] = [];

      // A. Desks
      OFFICE_2D_LAYOUT.desks.forEach((desk) => {
        renderQueue.push({
          type: 'desk',
          data: desk,
          sortY: desk.y + desk.height - 2,
        });

        // Associated Workstation Chair
        const isOccupied = visibleAgents.some(
          (a) => a.deskId === desk.id && a.state2D === 'working_at_desk' && Math.hypot(a.x - desk.seatX, a.y - desk.seatY) < 15
        );
        renderQueue.push({
          type: 'chair',
          data: {
            id: `desk-chair-${desk.id}`,
            x: desk.seatX - 10,
            y: desk.seatY - 10,
            facing: desk.facing,
            isOccupied,
            isExecutive: desk.deskType === 'manager',
          },
          // Placed slightly behind or at seat level
          sortY: desk.seatY + 2,
        });
      });

      // B. Furniture (Tables, Sofas, Server Racks, Plants, Chairs)
      OFFICE_2D_LAYOUT.furniture.forEach((f) => {
        renderQueue.push({
          type: 'furniture',
          data: f,
          sortY: f.y + f.height,
        });
      });

      // C. Interactive POIs
      OFFICE_2D_LAYOUT.pois.forEach((poi) => {
        renderQueue.push({
          type: 'poi',
          data: poi,
          sortY: poi.y + poi.height,
        });
      });

      // D. Environmental Props (Filing cabinets, printers, clocks, posters, bins)
      if (OFFICE_2D_LAYOUT.environmentalProps) {
        OFFICE_2D_LAYOUT.environmentalProps.forEach((prop) => {
          renderQueue.push({
            type: 'prop',
            data: prop,
            sortY: prop.y + prop.height,
          });
        });
      }

      // E. Active AI Agents
      visibleAgents.forEach((agent) => {
        renderQueue.push({
          type: 'agent',
          data: agent,
          sortY: agent.y + 1,
        });
      });

      // Sort all depth entities by ascending Y
      renderQueue.sort((a, b) => a.sortY - b.sortY);

      // 6. DRAW ALL ENTITIES IN EXACT FRONT-TO-BACK DEPTH ORDER
      renderQueue.forEach((entity) => {
        if (entity.type === 'desk') {
          draw3DDesk(ctx, entity.data, now);
        } else if (entity.type === 'chair') {
          draw3DChair(
            ctx,
            entity.data.x,
            entity.data.y,
            entity.data.facing,
            entity.data.isOccupied,
            entity.data.isExecutive
          );
        } else if (entity.type === 'furniture') {
          const f = entity.data;
          if (f.type === 'table') {
            if (f.id === 'sofa-table') {
              drawCoffeeTable(ctx, f);
            } else if (f.id === 'cafe-round-table') {
              drawRoundCafeTable(ctx, f);
            } else {
              drawConferenceTable(ctx, f, now);
            }
          } else if (f.type === 'chair') {
            draw3DChair(ctx, f.x, f.y, 'down', false, false);
          } else if (f.type === 'sofa') {
            if (f.id.includes('bench')) {
              drawZenBench(ctx, f);
            } else {
              drawPlushSofa(ctx, f);
            }
          } else if (f.type === 'server_rack') {
            drawServerRack3D(ctx, f, now);
          } else if (f.type === 'plant') {
            drawPottedPlant(ctx, f);
          }
        } else if (entity.type === 'poi') {
          const poi = entity.data;
          const isSelected = selectedAgentId === null && hoveredPoiId === poi.id;
          if (poi.type === 'coffee_machine') {
            drawEspressoMachine(ctx, poi, now, isSelected);
          } else if (poi.type === 'arcade') {
            drawArcadeCabinet(ctx, poi, now, isSelected);
          } else if (poi.type === 'water_cooler') {
            drawWaterCooler(ctx, poi, now);
          } else if (poi.type === 'vending_machine') {
            drawVendingMachine(ctx, poi, now);
          } else if (poi.type === 'server_rack') {
            drawServerRack3D(ctx, poi, now);
          } else if (poi.type === 'whiteboard') {
            drawWhiteboard(ctx, poi);
          } else if (poi.type === 'fountain') {
            drawZenFountain(ctx, poi, now);
          } else if (poi.type === 'bookshelf') {
            drawBookshelf(ctx, poi);
          }
        } else if (entity.type === 'prop') {
          drawEnvironmentalProp(ctx, entity.data, now);
        } else if (entity.type === 'agent') {
          drawPixelAgent(
            ctx,
            entity.data,
            entity.data.id === selectedAgentId,
            entity.data.id === hoveredAgentId
          );
        }
      });

      // 7. ATMOSPHERIC & RADIAL LIGHTING OVERLAY PASS
      drawOfficeLighting(ctx, OFFICE_2D_LAYOUT, visibleAgents, lighting, now);

      ctx.restore();

      reqIdRef.current = requestAnimationFrame(render);
    };

    reqIdRef.current = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(reqIdRef.current);
    };
  }, [pan, zoom, simSpeed, lighting, selectedAgentId, hoveredAgentId, hoveredPoiId, searchFilter, departmentFilter, onAgentsChange]);

  // Convert client mouse coordinates to world coordinates
  const screenToWorld = useCallback(
    (screenX: number, screenY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      const clientX = screenX - rect.left;
      const clientY = screenY - rect.top;
      return {
        x: (clientX - pan.x) / zoom,
        y: (clientY - pan.y) / zoom,
      };
    },
    [pan, zoom]
  );

  // Mouse Down: Start dragging
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button === 0) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  // Mouse Move: Pan map or update hover hit testing
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
      return;
    }

    const { x: worldX, y: worldY } = screenToWorld(e.clientX, e.clientY);

    // Hit test Agents (radius 24px)
    let foundAgentId: string | null = null;
    for (const agent of agentsRef.current) {
      if (Math.hypot(agent.x - worldX, agent.y - worldY) < 24) {
        foundAgentId = agent.id;
        break;
      }
    }
    setHoveredAgentId(foundAgentId);

    // Hit test POIs
    let foundPoiId: string | null = null;
    if (!foundAgentId) {
      for (const poi of OFFICE_2D_LAYOUT.pois) {
        if (
          worldX >= poi.x &&
          worldX <= poi.x + poi.width &&
          worldY >= poi.y &&
          worldY <= poi.y + poi.height
        ) {
          foundPoiId = poi.id;
          break;
        }
      }
    }
    setHoveredPoiId(foundPoiId);

    // Hit test Desks
    let foundDeskId: string | null = null;
    if (!foundAgentId && !foundPoiId) {
      for (const desk of OFFICE_2D_LAYOUT.desks) {
        if (
          worldX >= desk.x - 4 &&
          worldX <= desk.x + desk.width + 4 &&
          worldY >= desk.y - 4 &&
          worldY <= desk.y + desk.height + 16
        ) {
          foundDeskId = desk.id;
          break;
        }
      }
    }
    setHoveredDeskId(foundDeskId);
  };

  // Mouse Up / Click: Handle clicks on Agents, POIs, Desks, or empty floor
  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    setIsDragging(false);

    const { x: worldX, y: worldY } = screenToWorld(e.clientX, e.clientY);

    // 1. Check Agent Click
    for (const agent of agentsRef.current) {
      if (Math.hypot(agent.x - worldX, agent.y - worldY) < 24) {
        retroAudio.playChime();
        onSelectAgent(agent);
        return;
      }
    }

    // 2. Check POI Click
    for (const poi of OFFICE_2D_LAYOUT.pois) {
      if (
        worldX >= poi.x &&
        worldX <= poi.x + poi.width &&
        worldY >= poi.y &&
        worldY <= poi.y + poi.height
      ) {
        retroAudio.playChime();
        onSelectPoi(poi);
        return;
      }
    }

    // 3. Check Desk Click
    for (const desk of OFFICE_2D_LAYOUT.desks) {
      if (
        worldX >= desk.x - 4 &&
        worldX <= desk.x + desk.width + 4 &&
        worldY >= desk.y - 4 &&
        worldY <= desk.y + desk.height + 16
      ) {
        if (selectedAgentId) {
          const targetAgent = agentsRef.current.find((a) => a.id === selectedAgentId);
          if (targetAgent) {
            retroAudio.playFootstep();
            const isOwnDesk = targetAgent.deskId === desk.id;
            const updated = navigateToDesk(
              targetAgent,
              desk.id,
              isOwnDesk ? 'Returning to my workstation 💻' : `Heading to ${desk.id} to collaborate 🤝`
            );
            const nextList = agentsRef.current.map((a) => (a.id === selectedAgentId ? updated : a));
            agentsRef.current = nextList;
            onAgentsChange(nextList);
            return;
          }
        }

        const deskAgent = agentsRef.current.find((a) => a.deskId === desk.id);
        if (deskAgent) {
          retroAudio.playChime();
          onSelectAgent(deskAgent);
          return;
        }
      }
    }

    // 4. Clicked empty floor with a selected agent -> Route agent to target location!
    if (selectedAgentId) {
      const targetAgent = agentsRef.current.find((a) => a.id === selectedAgentId);
      if (
        targetAgent &&
        worldX >= 0 &&
        worldX <= OFFICE_2D_LAYOUT.width &&
        worldY >= 0 &&
        worldY <= OFFICE_2D_LAYOUT.height
      ) {
        retroAudio.playFootstep();
        const updated = navigateToPoint(targetAgent, worldX, worldY);
        updated.bubble = {
          text: 'Walking to target position...',
          emoji: '🚶',
          expiresAt: Date.now() + 4000,
          type: 'action',
        };
        const nextList = agentsRef.current.map((a) => (a.id === selectedAgentId ? updated : a));
        agentsRef.current = nextList;
        onAgentsChange(nextList);
      }
    }
  };

  // Mouse Wheel: Smooth Zoom centered on mouse cursor (Native Non-Passive Listener)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleNativeWheel = (e: WheelEvent) => {
      // Strictly prevent page scroll ONLY when scrolling on the office floor canvas
      e.preventDefault();
      e.stopPropagation();

      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newZoom = Math.min(Math.max(zoom * zoomFactor, 0.5), 2.2);

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      setPan((prev) => ({
        x: mouseX - (mouseX - prev.x) * (newZoom / zoom),
        y: mouseY - (mouseY - prev.y) * (newZoom / zoom),
      }));

      onZoomChange(newZoom);
    };

    canvas.addEventListener('wheel', handleNativeWheel, { passive: false });
    return () => {
      canvas.removeEventListener('wheel', handleNativeWheel);
    };
  }, [zoom, onZoomChange]);

  // Resize canvas on container size change
  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current && canvasRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        canvasRef.current.width = clientWidth;
        canvasRef.current.height = clientHeight;
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const hoveredDesk = hoveredDeskId
    ? OFFICE_2D_LAYOUT.desks.find((d) => d.id === hoveredDeskId)
    : null;
  const assignedAgent = hoveredDesk
    ? agents.find((a) => a.deskId === hoveredDesk.id)
    : null;
  const selectedAgent = selectedAgentId
    ? agents.find((a) => a.id === selectedAgentId)
    : null;

  const tooltipScreenX = hoveredDesk
    ? (hoveredDesk.x + hoveredDesk.width / 2) * zoom + pan.x
    : 0;
  const tooltipScreenY = hoveredDesk
    ? hoveredDesk.y * zoom + pan.y - 14
    : 0;

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative overflow-hidden bg-[#060608] select-none"
      style={{
        cursor: hoveredAgentId
          ? 'pointer'
          : hoveredPoiId
          ? 'pointer'
          : hoveredDeskId
          ? 'pointer'
          : isDragging
          ? 'grabbing'
          : 'grab',
      }}
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        className="w-full h-full block"
      />

      {/* Desk Hover State Tooltip */}
      {hoveredDesk && (
        <div
          className="absolute z-30 pointer-events-none transition-all duration-75 ease-out -translate-x-1/2 -translate-y-full pb-2 animate-in fade-in zoom-in-95 duration-100"
          style={{
            left: `${tooltipScreenX}px`,
            top: `${tooltipScreenY}px`,
          }}
        >
          <div className="w-80 rounded-xl bg-[#090D16]/95 backdrop-blur-md border border-emerald-500/40 shadow-2xl shadow-emerald-950/60 p-3.5 text-xs text-white font-sans">
            {/* Header: Desk Identifier & Zone */}
            <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-white/[0.08]">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                  <Monitor className="w-3.5 h-3.5" />
                </div>
                <div>
                  <div className="font-mono font-bold text-white text-xs tracking-tight flex items-center gap-1.5">
                    {hoveredDesk.name || hoveredDesk.id}
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-white/[0.08] text-slate-300 font-normal">
                      {hoveredDesk.zoneId.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {hoveredDesk.deskType ? hoveredDesk.deskType.toUpperCase() : 'WORKSTATION'} • {hoveredDesk.monitorSetup ? hoveredDesk.monitorSetup.toUpperCase() : 'DUAL'} DISPLAY
                  </div>
                </div>
              </div>

              {/* Status Indicator */}
              <div className="flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    assignedAgent ? 'bg-emerald-400' : 'bg-slate-400'
                  }`} />
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${
                    assignedAgent ? 'bg-emerald-500' : 'bg-slate-500'
                  }`} />
                </span>
                <span className="text-[10px] font-mono text-slate-400">
                  {assignedAgent ? 'OCCUPIED' : 'VACANT'}
                </span>
              </div>
            </div>

            {/* Assigned Agent Details */}
            {assignedAgent ? (
              <div className="pt-2.5 space-y-2.5">
                {/* Agent Identity & Role */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-emerald-600 to-cyan-500 flex items-center justify-center text-white font-mono font-bold text-[11px] shadow-sm">
                      {assignedAgent.name.charAt(0)}
                    </div>
                    <div>
                      <div className="font-semibold text-white text-xs flex items-center gap-1">
                        {assignedAgent.name}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {assignedAgent.role}
                      </div>
                    </div>
                  </div>

                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-500/30 text-emerald-300">
                    {assignedAgent.model}
                  </span>
                </div>

                {/* Real-Time Task Status Card */}
                <div className="p-2.5 rounded-lg bg-black/50 border border-white/[0.08] space-y-1.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5 text-emerald-400 font-medium font-mono text-[10px] uppercase tracking-wider">
                      <Activity className="w-3 h-3 animate-pulse" />
                      Current Task
                    </div>
                    <span className="font-mono text-emerald-300 text-[10px] font-bold">
                      {assignedAgent.taskProgress || 0}%
                    </span>
                  </div>

                  {/* Task Description */}
                  <div className="text-white text-[11px] font-medium leading-snug line-clamp-2">
                    {assignedAgent.currentTask || 'Executing scheduled system routines'}
                  </div>

                  {/* Progress Bar */}
                  <div className="w-full bg-white/[0.1] rounded-full h-1.5 overflow-hidden">
                    <div
                      className="bg-gradient-to-r from-emerald-500 to-teal-400 h-full rounded-full transition-all duration-300"
                      style={{ width: `${Math.max(5, assignedAgent.taskProgress || 0)}%` }}
                    />
                  </div>

                  {/* Agent Activity State */}
                  <div className="flex items-center justify-between pt-1 text-[10px] text-slate-400 border-t border-white/[0.04]">
                    <span>State:</span>
                    <span className="font-mono text-slate-200">
                      {assignedAgent.state2D === 'working_at_desk'
                        ? '💻 Deep Focus (At Desk)'
                        : assignedAgent.state2D === 'walking_to_desk'
                        ? '🚶 Walking to Desk (A*)'
                        : assignedAgent.state2D === 'at_breakroom'
                        ? '☕ Breakroom / Lounge'
                        : assignedAgent.state2D === 'walking_to_breakroom'
                        ? '🚶 Grabbing Coffee'
                        : assignedAgent.state2D === 'in_meeting'
                        ? '👥 Standup Meeting'
                        : assignedAgent.state2D === 'inspecting_server'
                        ? '🖥️ Cluster Diagnostics'
                        : '🚶 Roaming Floor'}
                    </span>
                  </div>
                </div>

                {/* Telemetry Metrics Grid */}
                <div className="grid grid-cols-3 gap-1.5 pt-0.5 text-center text-[10px] font-mono">
                  <div className="p-1.5 rounded-md bg-white/[0.03] border border-white/[0.05]">
                    <div className="text-slate-400 flex items-center justify-center gap-1">
                      <Zap className="w-2.5 h-2.5 text-amber-400" />
                      Energy
                    </div>
                    <div className="font-bold text-amber-300 mt-0.5">
                      {assignedAgent.energy}%
                    </div>
                  </div>
                  <div className="p-1.5 rounded-md bg-white/[0.03] border border-white/[0.05]">
                    <div className="text-slate-400 flex items-center justify-center gap-1">
                      <Cpu className="w-2.5 h-2.5 text-cyan-400" />
                      CPU
                    </div>
                    <div className="font-bold text-cyan-300 mt-0.5">
                      {assignedAgent.cpu}%
                    </div>
                  </div>
                  <div className="p-1.5 rounded-md bg-white/[0.03] border border-white/[0.05]">
                    <div className="text-slate-400 flex items-center justify-center gap-1">
                      <Sparkles className="w-2.5 h-2.5 text-purple-400" />
                      Tokens
                    </div>
                    <div className="font-bold text-purple-300 mt-0.5">
                      {(assignedAgent.tokensUsed / 1000).toFixed(1)}k
                    </div>
                  </div>
                </div>

                {/* Active Bubble (if any) */}
                {assignedAgent.bubble && assignedAgent.bubble.expiresAt > Date.now() && (
                  <div className="px-2 py-1 rounded bg-white/[0.04] border border-white/[0.08] text-[10px] text-slate-300 flex items-center gap-1.5 italic">
                    <span>{assignedAgent.bubble.emoji || '💬'}</span>
                    <span className="line-clamp-1">"{assignedAgent.bubble.text}"</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="py-4 text-center space-y-1">
                <div className="text-slate-400 text-xs">Unassigned Workstation</div>
                <div className="text-[10px] text-slate-500">
                  Ready for new agent assignment or hot-desking
                </div>
              </div>
            )}

            {/* Interaction Hint Footer */}
            <div className="mt-2.5 pt-2 border-t border-white/[0.08] flex items-center justify-between text-[10px] text-slate-400 font-mono">
              <div className="flex items-center gap-1 text-emerald-400/90">
                <ArrowRight className="w-3 h-3" />
                {selectedAgent
                  ? `Click to route ${selectedAgent.name} here (A*)`
                  : 'Click desk to inspect agent'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
