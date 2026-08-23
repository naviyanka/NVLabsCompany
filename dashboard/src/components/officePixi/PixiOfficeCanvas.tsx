import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Application,
  Container,
  Graphics,
  Sprite,
  Text,
  TextStyle,
  Texture,
} from 'pixi.js';
import type {
  Agent2D,
  InteractivePOI,
  LightingMode,
  SimSpeed,
} from '../office2d/types';
import { OFFICE_2D_LAYOUT } from '../office2d/office2DMap';
import { pixiTextureManager, pixiAssetLoader } from './PixiSpriteFactory';
import { drawPixelAgent } from '../office2d/agentSprites';
import {
  updateAgentsSimulation,
  navigateToPoint,
  navigateToDesk,
} from '../office2d/movementEngine';
import { retroAudio } from '@/utils/retroAudio';
import {
  Monitor,
  Cpu,
  Zap,
  Activity,
  Sparkles,
  ArrowRight,
} from 'lucide-react';

interface PixiOfficeCanvasProps {
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

export function PixiOfficeCanvas({
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
}: PixiOfficeCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);

  // Pan offsets
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Hover states
  const [hoveredAgentId, setHoveredAgentId] = useState<string | null>(null);
  const [hoveredPoiId, setHoveredPoiId] = useState<string | null>(null);
  const [hoveredDeskId, setHoveredDeskId] = useState<string | null>(null);

  // Synchronized state refs for PixiJS render ticker
  const agentsRef = useRef<Agent2D[]>(agents);
  agentsRef.current = agents;

  const simSpeedRef = useRef<SimSpeed>(simSpeed);
  simSpeedRef.current = simSpeed;

  const lightingRef = useRef<LightingMode>(lighting);
  lightingRef.current = lighting;

  const zoomRef = useRef<number>(zoom);
  zoomRef.current = zoom;

  const panRef = useRef(pan);
  panRef.current = pan;

  const selectedAgentIdRef = useRef<string | null>(selectedAgentId);
  selectedAgentIdRef.current = selectedAgentId;

  const hoveredAgentIdRef = useRef<string | null>(hoveredAgentId);
  hoveredAgentIdRef.current = hoveredAgentId;

  const hoveredDeskIdRef = useRef<string | null>(hoveredDeskId);
  hoveredDeskIdRef.current = hoveredDeskId;

  const searchFilterRef = useRef(searchFilter);
  searchFilterRef.current = searchFilter;

  const departmentFilterRef = useRef(departmentFilter);
  departmentFilterRef.current = departmentFilter;

  // Center the office map initially on mount
  useEffect(() => {
    if (containerRef.current) {
      const { clientWidth, clientHeight } = containerRef.current;
      const initialPanX = (clientWidth - OFFICE_2D_LAYOUT.width * zoom) / 2;
      const initialPanY = (clientHeight - OFFICE_2D_LAYOUT.height * zoom) / 2;
      const centered = { x: initialPanX, y: initialPanY };
      setPan(centered);
      panRef.current = centered;
    }
  }, []);

  // Initialize PixiJS Application
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let isDestroyed = false;
    const app = new Application();

    async function initPixi() {
      await app.init({
        width: container?.clientWidth || 1200,
        height: container?.clientHeight || 800,
        backgroundColor: 0x060608,
        antialias: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
        autoDensity: true,
      });

      if (isDestroyed || !container) {
        app.destroy(true, { children: true });
        return;
      }

      // Preload all 3/4 perspective office furniture, appliances, compute racks and props
      await pixiAssetLoader.preloadAll();

      if (isDestroyed || !container) {
        app.destroy(true, { children: true });
        return;
      }

      appRef.current = app;
      container.appendChild(app.canvas);

      // World Root Container
      const worldContainer = new Container();
      app.stage.addChild(worldContainer);

      // 1. Floor & Architecture Layer
      const floorGraphics = new Graphics();
      worldContainer.addChild(floorGraphics);

      // 2. Room Wall & Zone Headers Layer
      const roomHeaderContainer = new Container();
      worldContainer.addChild(roomHeaderContainer);

      // 3. Static & Dynamic Entity Container (Z-Sorted)
      const entityContainer = new Container();
      worldContainer.addChild(entityContainer);

      // 4. Dynamic Lighting Atmosphere Layer
      const lightingGraphics = new Graphics();
      worldContainer.addChild(lightingGraphics);

      // 5. Navigation Path & Agent Bubble Layer
      const overlayContainer = new Container();
      worldContainer.addChild(overlayContainer);

      // Draw Static Architectural Floor Plan once
      drawPixiFloor(floorGraphics, roomHeaderContainer);

      // Agent dynamic canvases for pixel agent rendering into Pixi textures
      const agentCanvasMap = new Map<string, HTMLCanvasElement>();
      const visualPositionsMap = new Map<string, { x: number; y: number }>();

      let lastTime = performance.now();

      // PixiJS Ticker Loop (60 FPS)
      app.ticker.add(() => {
        const now = performance.now();
        const deltaMs = Math.min(now - lastTime, 50);
        lastTime = now;
        const currentSimSpeed = simSpeedRef.current;

        // 1. Update Agent Simulation State
        if (currentSimSpeed > 0) {
          const updated = updateAgentsSimulation(agentsRef.current, deltaMs, currentSimSpeed);
          agentsRef.current = updated;
          if (Math.random() < 0.2) {
            onAgentsChange(updated);
          }
        }

        // 2. Sync World Container Transform (Pan & Zoom)
        worldContainer.position.set(panRef.current.x, panRef.current.y);
        worldContainer.scale.set(zoomRef.current, zoomRef.current);

        // 3. Filter visible agents
        const curSearch = searchFilterRef.current.toLowerCase();
        const curDept = departmentFilterRef.current;
        const visibleAgents = agentsRef.current.filter((a) => {
          if (curSearch && !a.name.toLowerCase().includes(curSearch)) return false;
          if (curDept && a.zoneId !== curDept) return false;
          return true;
        });

        // 4. Clear & Rebuild Entity Container with Y-Sorting
        entityContainer.removeChildren();
        overlayContainer.removeChildren();

        const animFrame = Math.floor(now / 200);

        interface SortableEntity {
          y: number;
          render: (target: Container) => void;
        }

        const sortables: SortableEntity[] = [];

        // A. 3/4 Perspective Desks & Chairs
        OFFICE_2D_LAYOUT.desks.forEach((desk) => {
          const isHovered = hoveredDeskIdRef.current === desk.id;

          // If hovered, render glowing floor halo and targeting reticle
          if (isHovered) {
            const highlightG = new Graphics();
            // Floor halo
            highlightG.roundRect(desk.x - 6, desk.y - 6, desk.width + 12, desk.height + 12, 6);
            highlightG.fill({ color: 0x10b981, alpha: 0.18 });
            highlightG.stroke({ color: 0x34d399, width: 1.5, alpha: 0.85 });

            // Corner tech brackets
            const cw = 7;
            // Top-left
            highlightG.moveTo(desk.x - 8, desk.y - 6 + cw);
            highlightG.lineTo(desk.x - 8, desk.y - 8);
            highlightG.lineTo(desk.x - 6 + cw, desk.y - 8);
            // Top-right
            highlightG.moveTo(desk.x + desk.width + 6 - cw, desk.y - 8);
            highlightG.lineTo(desk.x + desk.width + 8, desk.y - 8);
            highlightG.lineTo(desk.x + desk.width + 8, desk.y - 6 + cw);
            // Bottom-right
            highlightG.moveTo(desk.x + desk.width + 8, desk.y + desk.height + 6 - cw);
            highlightG.lineTo(desk.x + desk.width + 8, desk.y + desk.height + 8);
            highlightG.lineTo(desk.x + desk.width + 6 - cw, desk.y + desk.height + 8);
            // Bottom-left
            highlightG.moveTo(desk.x - 6 + cw, desk.y + desk.height + 8);
            highlightG.lineTo(desk.x - 8, desk.y + desk.height + 8);
            highlightG.lineTo(desk.x - 8, desk.y + desk.height + 6 - cw);
            highlightG.stroke({ color: 0x10b981, width: 2, alpha: 0.95 });

            sortables.push({
              y: desk.y - 8,
              render: (c) => c.addChild(highlightG),
            });
          }

          const deskTex = pixiTextureManager.getDeskTexture(desk);
          const deskSprite = new Sprite(deskTex);
          deskSprite.position.set(desk.x - 16, desk.y - 16);

          sortables.push({
            y: desk.y + desk.height - 2,
            render: (c) => c.addChild(deskSprite),
          });

          // Chair
          const isOccupied = visibleAgents.some(
            (a) => a.deskId === desk.id && a.state2D === 'working_at_desk' && Math.hypot(a.x - desk.seatX, a.y - desk.seatY) < 16
          );
          const chairTex = pixiTextureManager.getChairTexture(desk.facing, desk.deskType === 'manager');
          const chairSprite = new Sprite(chairTex);
          chairSprite.position.set(desk.seatX - 18, desk.seatY - 18);

          sortables.push({
            y: desk.seatY + (isOccupied ? -4 : 2),
            render: (c) => c.addChild(chairSprite),
          });
        });

        // B. 3/4 Perspective Furniture (Tables, Sofas, Plants, Server Racks)
        OFFICE_2D_LAYOUT.furniture.forEach((f) => {
          let tex: Texture | null = null;
          let offsetY = 10;

          if (f.type === 'server_rack') {
            tex = pixiTextureManager.getServerRackTexture(f, animFrame);
            offsetY = 12;
          } else if (f.type === 'table') {
            tex = pixiTextureManager.getTableTexture(f);
            offsetY = 10;
          } else if (f.type === 'sofa') {
            tex = pixiTextureManager.getSofaTexture(f);
            offsetY = 10;
          } else if (f.type === 'plant') {
            tex = pixiTextureManager.getPlantTexture(f);
            offsetY = 10;
          } else if (f.type === 'chair') {
            tex = pixiTextureManager.getChairTexture('down', false);
            offsetY = 8;
          }

          if (tex) {
            const sprite = new Sprite(tex);
            sprite.position.set(f.x - offsetY, f.y - offsetY);
            sortables.push({
              y: f.y + f.height,
              render: (c) => c.addChild(sprite),
            });
          }
        });

        // C. 3/4 Perspective Interactive POIs (Arcade, Vending, Coffee, Water, Server, Whiteboard, Fountain, Bookshelf)
        OFFICE_2D_LAYOUT.pois.forEach((poi) => {
          let tex: Texture | null = null;
          let pad = 12;

          if (poi.type === 'arcade') {
            tex = pixiTextureManager.getArcadeCabinetTexture(poi, animFrame);
          } else if (poi.type === 'vending_machine') {
            tex = pixiTextureManager.getVendingMachineTexture(poi, animFrame);
          } else if (poi.type === 'server_rack') {
            tex = pixiTextureManager.getServerRackTexture(poi, animFrame);
          } else if (poi.type === 'coffee_machine') {
            tex = pixiTextureManager.getEspressoMachineTexture(poi, animFrame);
            pad = 10;
          } else if (poi.type === 'water_cooler') {
            tex = pixiTextureManager.getWaterCoolerTexture(poi, animFrame);
            pad = 8;
          } else if (poi.type === 'whiteboard') {
            tex = pixiTextureManager.getWhiteboardTexture(poi);
            pad = 10;
          } else if (poi.type === 'bookshelf') {
            tex = pixiTextureManager.getBookshelfTexture(poi);
            pad = 10;
          } else if (poi.type === 'fountain') {
            tex = pixiTextureManager.getZenFountainTexture(poi, animFrame);
          }

          if (tex) {
            const sprite = new Sprite(tex);
            sprite.position.set(poi.x - pad, poi.y - pad);
            sortables.push({
              y: poi.y + poi.height,
              render: (c) => c.addChild(sprite),
            });
          }
        });

        // D. 3/4 Perspective Environmental Props (Filing Cabinets, Clocks, Printers, Bins)
        if (OFFICE_2D_LAYOUT.environmentalProps) {
          OFFICE_2D_LAYOUT.environmentalProps.forEach((prop) => {
            const tex = pixiTextureManager.getPropTexture(prop, now);
            const sprite = new Sprite(tex);
            sprite.position.set(prop.x - 8, prop.y - 8);
            sortables.push({
              y: prop.y + prop.height,
              render: (c) => c.addChild(sprite),
            });
          });
        }

        // E. 3/4 Perspective AI Agents with Animated Directional Walk Sprites
        visibleAgents.forEach((agent) => {
          const isSel = agent.id === selectedAgentIdRef.current;
          const isHov = agent.id === hoveredAgentIdRef.current;

          // Smooth visual position lerp interpolation
          let visual = visualPositionsMap.get(agent.id);
          if (!visual) {
            visual = { x: agent.x, y: agent.y };
            visualPositionsMap.set(agent.id, visual);
          } else {
            const lerpFactor = Math.min(1, 0.45 * (deltaMs / 16.667));
            const diffX = agent.x - visual.x;
            const diffY = agent.y - visual.y;
            if (Math.hypot(diffX, diffY) > 80) {
              visual.x = agent.x;
              visual.y = agent.y;
            } else {
              visual.x += diffX * lerpFactor;
              visual.y += diffY * lerpFactor;
            }
          }

          // Get or create agent canvas
          let aCanvas = agentCanvasMap.get(agent.id);
          if (!aCanvas) {
            aCanvas = document.createElement('canvas');
            aCanvas.width = 64;
            aCanvas.height = 64;
            agentCanvasMap.set(agent.id, aCanvas);
          }

          const aCtx = aCanvas.getContext('2d');
          if (aCtx) {
            aCtx.clearRect(0, 0, 64, 64);
            aCtx.save();
            aCtx.translate(32, 40);
            drawPixelAgent(aCtx, { ...agent, x: 0, y: 0 }, isSel, isHov);
            aCtx.restore();
          }

          const aTex = Texture.from(aCanvas);
          aTex.update();
          const aSprite = new Sprite(aTex);
          aSprite.position.set(visual.x - 32, visual.y - 40);

          sortables.push({
            y: visual.y + 1,
            render: (c) => c.addChild(aSprite),
          });

          // Draw speech / thought bubble in overlay layer
          if (agent.bubble && agent.bubble.expiresAt > now) {
            const bubbleG = new Graphics();
            const bx = visual.x;
            const by = visual.y - 42;
            const text = agent.bubble.text;
            const estimatedW = Math.min(Math.max(text.length * 6.5 + 24, 60), 220);
            const bH = 22;

            bubbleG.roundRect(bx - estimatedW / 2, by - bH, estimatedW, bH, 5);
            bubbleG.fill({ color: 0x0f172a, alpha: 0.94 });
            bubbleG.stroke({ color: isSel ? 0xffb020 : 0x38bdf8, width: 1.5 });

            // Pointer tail
            bubbleG.poly([
              bx - 4, by,
              bx + 4, by,
              bx, by + 5,
            ]);
            bubbleG.fill({ color: 0x0f172a, alpha: 0.94 });

            overlayContainer.addChild(bubbleG);

            const bText = new Text({
              text: `${agent.bubble.emoji || '💬'} ${text}`,
              style: new TextStyle({
                fontFamily: 'monospace',
                fontSize: 9,
                fontWeight: 'bold',
                fill: 0xf8fafc,
              }),
            });
            bText.anchor.set(0.5, 0.5);
            bText.position.set(bx, by - bH / 2);
            overlayContainer.addChild(bText);
          }

          // If selected or moving with path, draw active A* path with animated nodes
          if (isSel && (agent.isMoving || (agent.path && agent.path.length > 0))) {
            const pathG = new Graphics();
            const allWaypoints: { x: number; y: number }[] = [];
            
            allWaypoints.push({ x: agent.x, y: agent.y });
            if (agent.targetX !== agent.x || agent.targetY !== agent.y) {
              allWaypoints.push({ x: agent.targetX, y: agent.targetY });
            }
            if (agent.path && agent.path.length > 0) {
              agent.path.forEach((pt) => allWaypoints.push({ x: pt.x, y: pt.y }));
            }

            if (allWaypoints.length >= 2) {
              // 1. Draw glowing background path line
              pathG.moveTo(allWaypoints[0]!.x, allWaypoints[0]!.y);
              for (let i = 1; i < allWaypoints.length; i++) {
                pathG.lineTo(allWaypoints[i]!.x, allWaypoints[i]!.y);
              }
              pathG.stroke({ color: 0xffb020, width: 3, alpha: 0.45 });

              // 2. Draw crisp foreground path line
              pathG.moveTo(allWaypoints[0]!.x, allWaypoints[0]!.y);
              for (let i = 1; i < allWaypoints.length; i++) {
                pathG.lineTo(allWaypoints[i]!.x, allWaypoints[i]!.y);
              }
              pathG.stroke({ color: 0xffd54f, width: 1.5, alpha: 0.95 });

              // 3. Draw waypoint nodes along the route
              for (let i = 1; i < allWaypoints.length - 1; i++) {
                const wp = allWaypoints[i]!;
                pathG.circle(wp.x, wp.y, 2.5);
                pathG.fill({ color: 0xffb020, alpha: 0.8 });
                pathG.stroke({ color: 0xffffff, width: 1, alpha: 0.9 });
              }

              // 4. Draw destination target reticle at final endpoint
              const finalPoint = allWaypoints[allWaypoints.length - 1]!;
              const pulse = 4 + Math.sin(now / 200) * 1.5;
              pathG.circle(finalPoint.x, finalPoint.y, pulse);
              pathG.stroke({ color: 0xffb020, width: 1.5, alpha: 0.9 });
              pathG.circle(finalPoint.x, finalPoint.y, 2);
              pathG.fill({ color: 0xffd54f, alpha: 1 });
            }

            overlayContainer.addChild(pathG);
          }
        });

        // Sort all entities by ascending Y (correct isometric depth order)
        sortables.sort((a, b) => a.y - b.y);
        sortables.forEach((s) => s.render(entityContainer));

        // 5. Dynamic Lighting & Atmospheric Color Overlay
        drawPixiLighting(lightingGraphics, lightingRef.current, visibleAgents, now);
      });
    }

    initPixi();

    // Handle container resize
    const handleResize = () => {
      if (appRef.current && containerRef.current) {
        appRef.current.renderer.resize(
          containerRef.current.clientWidth,
          containerRef.current.clientHeight
        );
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      isDestroyed = true;
      window.removeEventListener('resize', handleResize);
      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
        appRef.current = null;
      }
    };
  }, []);

  // Helper to draw the architectural floor plan in PixiJS Graphics
  function drawPixiFloor(g: Graphics, headerContainer: Container) {
    g.clear();
    headerContainer.removeChildren();

    // Overall Floor Boundary & Shadow
    g.roundRect(0, 0, OFFICE_2D_LAYOUT.width, OFFICE_2D_LAYOUT.height, 12);
    g.fill({ color: 0x0a0c12, alpha: 1 });
    g.stroke({ color: 0x1e293b, width: 3 });

    // Draw individual rooms
    OFFICE_2D_LAYOUT.rooms.forEach((room) => {
      const hexColor = parseInt(room.floorColor.replace('#', '0x'), 16) || 0x1e293b;
      const borderHex = parseInt(room.wallColor.replace('#', '0x'), 16) || 0x334155;
      const accentHex = parseInt(room.accentColor.replace('#', '0x'), 16) || 0x38bdf8;

      // Room Floor Slab
      g.roundRect(room.x, room.y, room.width, room.height, 6);
      g.fill({ color: hexColor, alpha: 0.95 });
      g.stroke({ color: borderHex, width: 2 });

      // Room Header Pill Banner
      const labelW = Math.min(room.label.length * 7.5 + 20, room.width - 20);
      const headerG = new Graphics();
      headerG.roundRect(room.x + 8, room.y + 8, labelW, 18, 4);
      headerG.fill({ color: 0x090d16, alpha: 0.88 });
      headerG.stroke({ color: accentHex, width: 1.2 });
      headerContainer.addChild(headerG);

      const headerText = new Text({
        text: room.label,
        style: new TextStyle({
          fontFamily: 'monospace',
          fontSize: 8.5,
          fontWeight: 'bold',
          fill: accentHex,
          letterSpacing: 1,
        }),
      });
      headerText.position.set(room.x + 14, room.y + 12);
      headerContainer.addChild(headerText);
    });

    // Draw partition walls
    OFFICE_2D_LAYOUT.walls.forEach((wall) => {
      g.roundRect(wall.x, wall.y, wall.width, wall.height, 2);
      g.fill({ color: 0x1e293b, alpha: 1 });
      g.stroke({ color: 0x334155, width: 1 });
    });
  }

  // Helper to draw PixiJS dynamic lighting pass
  function drawPixiLighting(
    g: Graphics,
    mode: LightingMode,
    agents: Agent2D[],
    now: number
  ) {
    g.clear();

    if (mode === 'day') {
      // Crisp daylight - subtle ambient warmth
      g.rect(0, 0, OFFICE_2D_LAYOUT.width, OFFICE_2D_LAYOUT.height);
      g.fill({ color: 0xfffaed, alpha: 0.03 });
    } else if (mode === 'cyberpunk') {
      // Cyberpunk matrix neon atmosphere
      g.rect(0, 0, OFFICE_2D_LAYOUT.width, OFFICE_2D_LAYOUT.height);
      g.fill({ color: 0x050814, alpha: 0.45 });

      // Server room cyber-glow
      const sRoom = OFFICE_2D_LAYOUT.rooms.find((r) => r.type === 'server');
      if (sRoom) {
        g.roundRect(sRoom.x, sRoom.y, sRoom.width, sRoom.height, 6);
        g.fill({ color: 0x06b6d4, alpha: 0.08 + Math.sin(now / 500) * 0.03 });
      }

      // Breakroom arcade neon pink glow
      const bRoom = OFFICE_2D_LAYOUT.rooms.find((r) => r.type === 'breakroom');
      if (bRoom) {
        g.roundRect(bRoom.x, bRoom.y, bRoom.width, bRoom.height, 6);
        g.fill({ color: 0xd946ef, alpha: 0.08 + Math.cos(now / 600) * 0.03 });
      }
    } else if (mode === 'night') {
      // Midnight dark room with luminous cones around active workstations
      g.rect(0, 0, OFFICE_2D_LAYOUT.width, OFFICE_2D_LAYOUT.height);
      g.fill({ color: 0x020408, alpha: 0.72 });

      // Desk lamps and active agents illumination halos
      agents.forEach((a) => {
        if (a.state2D === 'working_at_desk') {
          g.circle(a.x, a.y, 45);
          g.fill({ color: 0xfef08a, alpha: 0.14 });
        }
      });
    }
  }

  // Convert client mouse coordinates to world coordinates
  const screenToWorld = useCallback(
    (screenX: number, screenY: number) => {
      const container = containerRef.current;
      if (!container) return { x: 0, y: 0 };
      const rect = container.getBoundingClientRect();
      const clientX = screenX - rect.left;
      const clientY = screenY - rect.top;
      return {
        x: (clientX - pan.x) / zoom,
        y: (clientY - pan.y) / zoom,
      };
    },
    [pan, zoom]
  );

  // Mouse Drag to Pan
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button === 0) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (isDragging) {
      const nextPan = {
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      };
      setPan(nextPan);
      panRef.current = nextPan;
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
    hoveredAgentIdRef.current = foundAgentId;

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
  const handleMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
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
        // If an agent is selected, route them directly to this desk's seat via A*!
        if (selectedAgentId) {
          const targetAgent = agentsRef.current.find((a) => a.id === selectedAgentId);
          if (targetAgent) {
            retroAudio.playFootstep();
            const isOwnDesk = targetAgent.deskId === desk.id;
            const updated = navigateToDesk(
              targetAgent,
              desk.id,
              isOwnDesk ? 'Returning to my workstation 💻' : `Heading over to ${desk.id} to collaborate 🤝`
            );
            const nextList = agentsRef.current.map((a) => (a.id === selectedAgentId ? updated : a));
            agentsRef.current = nextList;
            onAgentsChange(nextList);
            return;
          }
        }

        // If no agent is selected, select the agent who sits at this desk
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
          text: 'Walking to target coordinates...',
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

  // Mouse Wheel: Smooth Zoom centered on mouse cursor
  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const newZoom = Math.min(Math.max(zoom * zoomFactor, 0.45), 2.2);

    const container = containerRef.current;
    if (container) {
      const rect = container.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const nextPan = {
        x: mouseX - (mouseX - pan.x) * (newZoom / zoom),
        y: mouseY - (mouseY - pan.y) * (newZoom / zoom),
      };
      setPan(nextPan);
      panRef.current = nextPan;
    }

    onZoomChange(newZoom);
  };

  const hoveredDesk = hoveredDeskId
    ? OFFICE_2D_LAYOUT.desks.find((d) => d.id === hoveredDeskId)
    : null;
  const assignedAgent = hoveredDesk
    ? agents.find((a) => a.deskId === hoveredDesk.id)
    : null;
  const selectedAgent = selectedAgentId
    ? agents.find((a) => a.id === selectedAgentId)
    : null;

  // Screen coordinates for desk tooltip
  const tooltipScreenX = hoveredDesk
    ? (hoveredDesk.x + hoveredDesk.width / 2) * zoom + pan.x
    : 0;
  const tooltipScreenY = hoveredDesk
    ? hoveredDesk.y * zoom + pan.y - 14
    : 0;

  return (
    <div
      ref={containerRef}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onWheel={handleWheel}
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
