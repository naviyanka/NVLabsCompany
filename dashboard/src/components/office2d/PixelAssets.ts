import type { Desk2D, Direction, EnvironmentalProp2D, Furniture2D, InteractivePOI } from './types';

/**
 * ============================================================================
 * PIXEL ASSETS LIBRARY - 3/4 ISOMETRIC PROJECTION SPRITE ARCHITECTURE
 * ============================================================================
 * 
 * Centralized, multi-planar sprite asset library for the 2D/2.5D Open Office simulation.
 * 
 * Every furniture item, compute chassis, fixture, and appliance is constructed
 * from discrete visual layers:
 *   1. contactShadow  -> Deep ambient ground occlusion + soft directional drop shadow
 *   2. base           -> Structural foundations (steel legs, plinths, casters, pedestals)
 *   3. frontFace      -> Vertical front-facing depth planes (doors, drawers, rails, modesty boards)
 *   4. topSurface     -> Illuminated top horizontal planes (overhead light reception, texture, bevels)
 *   5. sideFace       -> Dimensional side elevations with ambient occlusion & corner returns
 *   6. details        -> Accessories, status LED arrays, cable bundles, displays, animations
 */

// ============================================================================
// 1. MATERIAL PALETTES & COLOR SCIENCE
// ============================================================================

export const PIXEL_PALETTES = {
  wood: {
    carbon: {
      top: '#1c1e24',
      bevel: '#2e323d',
      front: '#131418',
      side: '#0d0e11',
      trim: '#3b404e',
      shadow: '#07080a',
      grain: 'rgba(255, 255, 255, 0.03)',
    },
    dark_mahogany: {
      top: '#451a13',
      bevel: '#61281e',
      front: '#2e0f0a',
      side: '#1f0906',
      trim: '#783528',
      shadow: '#100403',
      grain: 'rgba(255, 200, 160, 0.05)',
    },
    walnut: {
      top: '#38281c',
      bevel: '#4f3b2c',
      front: '#261b12',
      side: '#1a120b',
      trim: '#694f3a',
      shadow: '#0e0905',
      grain: 'rgba(255, 220, 180, 0.04)',
    },
    oak: {
      top: '#4d3d2c',
      bevel: '#6b5740',
      front: '#362a1e',
      side: '#241c13',
      trim: '#856d51',
      shadow: '#140f09',
      grain: 'rgba(255, 230, 190, 0.05)',
    },
    light_birch: {
      top: '#5e4e3b',
      bevel: '#7a6750',
      front: '#423729',
      side: '#2e261c',
      trim: '#968167',
      shadow: '#19150f',
      grain: 'rgba(255, 240, 210, 0.06)',
    },
  },
  metal: {
    steel: {
      top: '#475569',
      bevel: '#64748b',
      front: '#334155',
      side: '#1e293b',
      trim: '#94a3b8',
      dark: '#0f172a',
    },
    dark_chassis: {
      top: '#1e2029',
      bevel: '#2b2e3b',
      front: '#14161d',
      side: '#0c0d12',
      trim: '#3f4357',
      dark: '#06070a',
    },
    chrome: {
      top: '#e2e8f0',
      bevel: '#f8fafc',
      front: '#94a3b8',
      side: '#64748b',
      trim: '#ffffff',
      dark: '#334155',
    },
    brass: {
      top: '#ca8a04',
      bevel: '#eab308',
      front: '#854d0e',
      side: '#713f12',
      trim: '#fef08a',
      dark: '#422006',
    },
  },
  fabric: {
    executive_leather: {
      top: '#542617',
      bevel: '#753925',
      front: '#3a180d',
      side: '#250e07',
      cushion: '#632e1d',
      stitch: '#ca8a04',
    },
    mesh_black: {
      top: '#1f2430',
      bevel: '#2d3345',
      front: '#141720',
      side: '#0d0f14',
      cushion: '#272e3d',
      stitch: '#38bdf8',
    },
    fabric_indigo: {
      top: '#3730a3',
      bevel: '#4f46e5',
      front: '#252174',
      side: '#19174f',
      cushion: '#4338ca',
      stitch: '#818cf8',
    },
    fabric_teal: {
      top: '#0f766e',
      bevel: '#14b8a6',
      front: '#094e49',
      side: '#043431',
      cushion: '#115e59',
      stitch: '#2dd4bf',
    },
    fabric_amber: {
      top: '#b45309',
      bevel: '#f59e0b',
      front: '#78350f',
      side: '#451a03',
      cushion: '#92400e',
      stitch: '#fbbf24',
    },
  },
};

// ============================================================================
// 2. TEMPLATE INTERFACE DEFINITIONS
// ============================================================================

export interface IsometricTemplate<TProps> {
  name: string;
  contactShadow: (ctx: CanvasRenderingContext2D, props: TProps) => void;
  base: (ctx: CanvasRenderingContext2D, props: TProps) => void;
  frontFace: (ctx: CanvasRenderingContext2D, props: TProps) => void;
  topSurface: (ctx: CanvasRenderingContext2D, props: TProps) => void;
  sideFace: (ctx: CanvasRenderingContext2D, props: TProps) => void;
  details?: (ctx: CanvasRenderingContext2D, props: TProps, now?: number) => void;
  render: (ctx: CanvasRenderingContext2D, props: TProps, now?: number) => void;
}

// ============================================================================
// 3. SPRITE TEMPLATE: WORKSTATION / DESK
// ============================================================================

export interface DeskSpriteProps {
  x: number;
  y: number;
  width: number;
  height: number;
  woodTone?: keyof typeof PIXEL_PALETTES.wood;
  deskType?: 'developer' | 'designer' | 'manager' | 'systems' | 'data' | 'qa' | 'research' | 'ops' | 'support' | 'architect' | 'standard';
  monitorSetup?: 'single' | 'dual' | 'triple' | 'curved' | 'vertical_dual' | 'laptop_monitor' | 'executive';
  screenColor?: string;
  accessories?: ('coffee' | 'espresso' | 'headphones' | 'lamp' | 'tablet' | 'notes' | 'sticky_notes' | 'plant' | 'cables' | 'notebook' | 'phone' | 'can' | 'laptop' | 'papers' | 'energy_drink' | 'water_bottle' | 'keyboard' | 'mouse' | 'cert_plaque' | 'pen_holder')[];
  lampOn?: boolean;
}

export const DeskTemplate: IsometricTemplate<DeskSpriteProps> = {
  name: 'Desk',

  // 1. DISTINCT CONTACT SHADOW LAYER
  contactShadow: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    // Deep contact occlusion under leg touch points & pedestal
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.beginPath();
    ctx.roundRect(-2, props.height - 6, props.width + 4, 12, 3);
    ctx.fill();

    // Directional soft cast shadow extending downward
    ctx.fillStyle = 'rgba(0, 0, 0, 0.28)';
    ctx.beginPath();
    ctx.roundRect(-4, props.height - 2, props.width + 8, 16, 4);
    ctx.fill();

    ctx.restore();
  },

  // 2. BASE LAYER (Legs, Levelers, Pedestal Carcass, Modesty Cavity, Cables)
  base: (ctx, props) => {
    const { width, height, woodTone = 'carbon', deskType = 'developer', accessories = [] } = props;
    const mat = PIXEL_PALETTES.wood[woodTone] || PIXEL_PALETTES.wood.carbon;
    const desktopH = height - 4;
    const legInset = 4;
    const hasPedestal = width >= 60;

    // Modesty cavity background
    ctx.fillStyle = mat.shadow;
    ctx.fillRect(legInset + 2, 8, width - (legInset * 2 + 4), desktopH - 6);

    // Steel leg crossbars & feet
    const legW = 3;
    ctx.fillStyle = '#090a0f';
    ctx.fillRect(legInset, 8, legW, desktopH + 2);
    ctx.fillStyle = '#475569';
    ctx.fillRect(legInset, 8, 1, desktopH + 2);
    ctx.fillStyle = '#64748b';
    ctx.fillRect(legInset - 1, desktopH + 1, legW + 2, 2);

    if (!hasPedestal) {
      ctx.fillStyle = '#090a0f';
      ctx.fillRect(width - legInset - legW, 8, legW, desktopH + 2);
      ctx.fillStyle = '#475569';
      ctx.fillRect(width - legInset - legW, 8, 1, desktopH + 2);
      ctx.fillStyle = '#64748b';
      ctx.fillRect(width - legInset - legW - 1, desktopH + 1, legW + 2, 2);
    }

    // Cable harness spine
    if (accessories.includes('cables')) {
      ctx.fillStyle = '#050608';
      ctx.fillRect(width / 2 - 6, 8, 12, desktopH - 8);
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(width / 2 - 3, 8);
      ctx.lineTo(width / 2 - 2, desktopH);
      ctx.stroke();

      ctx.strokeStyle = '#ef4444';
      ctx.beginPath();
      ctx.moveTo(width / 2 + 1, 8);
      ctx.lineTo(width / 2 + 2, desktopH);
      ctx.stroke();

      ctx.strokeStyle = '#10b981';
      ctx.beginPath();
      ctx.moveTo(width / 2 + 3, 8);
      ctx.lineTo(width / 2 + 3, desktopH);
      ctx.stroke();
    }

    // Under-desk PC tower
    if (deskType === 'developer' || deskType === 'systems' || deskType === 'data') {
      const pcX = legInset + 3;
      const pcY = desktopH - 16;
      const pcW = 10;
      const pcH = 16;

      ctx.fillStyle = '#0f172a';
      ctx.fillRect(pcX, pcY, pcW, pcH);
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(pcX + 1, pcY + 1, pcW - 2, pcH - 2);
      ctx.fillStyle = '#020617';
      ctx.fillRect(pcX + 2, pcY + 4, pcW - 4, pcH - 6);
      ctx.fillStyle = '#06b6d4';
      ctx.fillRect(pcX + 3, pcY + 6, 4, 4);
    }
  },

  // 3. FRONT FACE LAYER (Front Desktop Edge Thickness, Drawer Fronts, Pull Handles)
  frontFace: (ctx, props) => {
    const { width, height, woodTone = 'carbon' } = props;
    const mat = PIXEL_PALETTES.wood[woodTone] || PIXEL_PALETTES.wood.carbon;
    const topThickness = 5;
    const desktopH = height - 4;
    const legInset = 4;
    const hasPedestal = width >= 60;

    // Modesty board panel
    ctx.fillStyle = mat.front;
    ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), desktopH - 12);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), 3);

    // Pedestal drawer unit front face & tiers
    if (hasPedestal) {
      const drawerW = 16;
      const drawerX = width - drawerW - legInset;
      const drawerY = 8;
      const drawerH = desktopH - 6;

      ctx.fillStyle = mat.front;
      ctx.fillRect(drawerX + 1, drawerY, drawerW - 1, drawerH);

      const tierH = Math.floor(drawerH / 3);
      for (let i = 0; i < 3; i++) {
        const ty = drawerY + i * tierH;
        ctx.fillStyle = '#050608';
        ctx.fillRect(drawerX + 1, ty, drawerW - 1, 1);

        ctx.fillStyle = mat.bevel;
        ctx.fillRect(drawerX + 2, ty + 1, drawerW - 3, tierH - 2);

        // Chrome pull handle
        ctx.fillStyle = '#94a3b8';
        ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 2);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 1);
      }
    }

    // Desktop front slab thickness
    ctx.fillStyle = mat.front;
    ctx.fillRect(0, desktopH - topThickness, width, topThickness);
    ctx.fillStyle = mat.shadow;
    ctx.fillRect(0, desktopH - 1, width, 1);
  },

  // 4. TOP SURFACE LAYER (Illuminated Desktop Slab, Grain Texture, Bevel Highlights, Desk Mat)
  topSurface: (ctx, props) => {
    const { width, height, woodTone = 'carbon', deskType = 'developer' } = props;
    const mat = PIXEL_PALETTES.wood[woodTone] || PIXEL_PALETTES.wood.carbon;
    const topThickness = 5;
    const desktopH = height - 4;

    // Illuminated top horizontal plane
    ctx.fillStyle = mat.top;
    ctx.fillRect(1, 1, width - 2, desktopH - topThickness);

    // Texture grain
    ctx.strokeStyle = mat.grain;
    ctx.lineWidth = 1;
    for (let gx = 6; gx < width - 6; gx += 14) {
      ctx.beginPath();
      ctx.moveTo(gx, 2);
      ctx.lineTo(gx + 4, desktopH - topThickness - 1);
      ctx.stroke();
    }

    // Perimeter bevel highlights
    ctx.fillStyle = mat.bevel;
    ctx.fillRect(1, 1, width - 2, 1); // back bevel
    ctx.fillRect(1, desktopH - topThickness - 1, width - 2, 1); // front edge highlight

    // Stitched desk mat
    const matInsetX = Math.floor(width * 0.12);
    const matW = width - matInsetX * 2;
    const matH = desktopH - topThickness - 4;
    const matY = 3;

    ctx.fillStyle = '#090a0f';
    ctx.fillRect(matInsetX, matY, matW, matH);
    ctx.strokeStyle = deskType === 'manager' ? '#ca8a04' : '#38bdf840';
    ctx.lineWidth = 1;
    ctx.strokeRect(matInsetX + 0.5, matY + 0.5, matW - 1, matH - 1);
  },

  // 5. SIDE FACE LAYER (Left & Right Perspective Elevation Planes)
  sideFace: (ctx, props) => {
    const { width, height, woodTone = 'carbon' } = props;
    const mat = PIXEL_PALETTES.wood[woodTone] || PIXEL_PALETTES.wood.carbon;
    const desktopH = height - 4;
    const legInset = 4;
    const hasPedestal = width >= 60;

    // Desktop side profile lines
    ctx.fillStyle = mat.side;
    ctx.fillRect(0, 0, 1, desktopH);
    ctx.fillRect(width - 1, 0, 1, desktopH);

    // Pedestal drawer side return
    if (hasPedestal) {
      const drawerW = 16;
      const drawerX = width - drawerW - legInset;
      const drawerY = 8;
      const drawerH = desktopH - 6;

      ctx.fillStyle = mat.side;
      ctx.fillRect(drawerX, drawerY, 1, drawerH);
    }
  },

  // 6. DETAILS LAYER (Monitors, Keyboard, Mouse, Accessories)
  details: (ctx, props, now = 0) => {
    const {
      width,
      height,
      deskType = 'developer',
      monitorSetup = 'dual',
      screenColor = '#38bdf8',
      accessories = [],
      lampOn = true,
    } = props;
    const topThickness = 5;
    const desktopH = height - 4;

    const matInsetX = Math.floor(width * 0.12);
    const matW = width - matInsetX * 2;
    const matH = desktopH - topThickness - 4;
    const matY = 3;

    // Mechanical keyboard
    const kbW = Math.min(22, matW - 14);
    const kbH = 8;
    const kbX = matInsetX + 4;
    const kbY = matY + matH - kbH - 2;

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(kbX, kbY, kbW, kbH);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(kbX, kbY, kbW, kbH - 1);
    ctx.fillStyle = '#334155';
    ctx.fillRect(kbX + 1, kbY, kbW - 2, 1);

    const keyPulse = Math.sin(now / 500);
    const keyColor = deskType === 'designer' ? '#f43f5e' : keyPulse > 0 ? '#38bdf8' : '#818cf8';
    for (let kx = kbX + 2; kx < kbX + kbW - 2; kx += 3) {
      ctx.fillStyle = keyColor;
      ctx.fillRect(kx, kbY + 2, 2, 2);
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(kx, kbY + 5, 2, 1);
    }

    // Ergonomic Mouse
    const mouseX = matInsetX + matW - 7;
    const mouseY = kbY + 1;
    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.roundRect(mouseX, mouseY, 4, 6, 1.5);
    ctx.fill();
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(mouseX + 1, mouseY + 2, 2, 1);

    // Multi-Monitor Displays
    renderDeskDisplays(ctx, width, monitorSetup, screenColor, now);

    // Accessories
    renderDeskProps(ctx, width, desktopH, accessories, lampOn, deskType, now);
  },

  // COMPOSITE RENDERER
  render: (ctx, props, now = 0) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    DeskTemplate.base(ctx, props);
    DeskTemplate.frontFace(ctx, props);
    DeskTemplate.topSurface(ctx, props);
    DeskTemplate.sideFace(ctx, props);
    if (DeskTemplate.details) {
      DeskTemplate.details(ctx, props, now);
    }

    ctx.restore();
  },
};

// ============================================================================
// 4. SPRITE TEMPLATE: ERGONOMIC & EXECUTIVE CHAIR
// ============================================================================

export interface ChairSpriteProps {
  x: number;
  y: number;
  facing?: Direction;
  isExecutive?: boolean;
}

export const ChairTemplate: IsometricTemplate<ChairSpriteProps> = {
  name: 'Chair',

  // 1. CONTACT SHADOW
  contactShadow: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.48)';
    ctx.beginPath();
    ctx.ellipse(10, 13, 9, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = 'rgba(0, 0, 0, 0.22)';
    ctx.beginPath();
    ctx.ellipse(10, 15, 11, 6, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  },

  // 2. BASE LAYER (5-Spoke Caster Wheelbase & Gas Cylinder)
  base: (ctx, props) => {
    const { isExecutive = false } = props;
    const cx = 10;
    const cy = 12;

    ctx.strokeStyle = isExecutive ? '#ca8a04' : '#64748b';
    ctx.lineWidth = 1.2;

    for (let i = 0; i < 5; i++) {
      const angle = (i * Math.PI * 2) / 5 + Math.PI / 2;
      const rx = cx + Math.cos(angle) * 7;
      const ry = cy + Math.sin(angle) * 4;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(rx, ry);
      ctx.stroke();

      ctx.fillStyle = '#090a0f';
      ctx.fillRect(rx - 1, ry - 1, 2, 2);
    }

    // Chrome Gas Lift Cylinder
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(cx - 1, cy - 4, 2, 4);
    ctx.fillStyle = '#334155';
    ctx.fillRect(cx, cy - 4, 1, 4);
  },

  // 3. FRONT FACE LAYER (Seat Pan Edge Thickness & Armrest Stanchions)
  frontFace: (ctx, props) => {
    const { isExecutive = false } = props;
    const mat = isExecutive ? PIXEL_PALETTES.fabric.executive_leather : PIXEL_PALETTES.fabric.mesh_black;
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatH = 10;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;

    // Vertical seat edge
    ctx.fillStyle = mat.front;
    ctx.fillRect(seatX, seatY + seatH - 2, seatW, 2);

    // Armrest vertical stanchions
    ctx.fillStyle = '#334155';
    ctx.fillRect(seatX - 2, seatY + 1, 2, 5);
    ctx.fillRect(seatX + seatW, seatY + 1, 2, 5);
  },

  // 4. TOP SURFACE LAYER (Contoured Cushioned Seat Pan & Armrest Pads)
  topSurface: (ctx, props) => {
    const { isExecutive = false } = props;
    const mat = isExecutive ? PIXEL_PALETTES.fabric.executive_leather : PIXEL_PALETTES.fabric.mesh_black;
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatH = 10;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;

    // Seat cushion top
    ctx.fillStyle = mat.top;
    ctx.beginPath();
    ctx.roundRect(seatX, seatY, seatW, seatH - 2, 2);
    ctx.fill();

    // Specular highlight & stitch seam
    ctx.fillStyle = mat.bevel;
    ctx.fillRect(seatX + 2, seatY + 1, seatW - 4, 1);

    // Armrest top pads
    ctx.fillStyle = '#090a0f';
    ctx.fillRect(seatX - 3, seatY, 3, 2);
    ctx.fillRect(seatX + seatW, seatY, 3, 2);
  },

  // 5. SIDE FACE LAYER (Side Elevation Return)
  sideFace: (ctx, props) => {
    const { isExecutive = false } = props;
    const mat = isExecutive ? PIXEL_PALETTES.fabric.executive_leather : PIXEL_PALETTES.fabric.mesh_black;
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;

    ctx.fillStyle = mat.side;
    ctx.fillRect(seatX, seatY, 1, 8);
    ctx.fillRect(seatX + seatW - 1, seatY, 1, 8);
  },

  // 6. DETAILS LAYER (Ergonomic Backrest & Lumbar Pillow)
  details: (ctx, props) => {
    const { facing = 'down', isExecutive = false } = props;
    const mat = isExecutive ? PIXEL_PALETTES.fabric.executive_leather : PIXEL_PALETTES.fabric.mesh_black;
    const cx = 10;
    const cy = 12;
    const seatY = cy - 8;

    if (facing === 'down') {
      const backW = 12;
      const backH = 8;
      const backX = cx - backW / 2;
      const backY = seatY - 5;

      ctx.fillStyle = mat.side;
      ctx.beginPath();
      ctx.roundRect(backX, backY, backW, backH, 2);
      ctx.fill();

      ctx.fillStyle = mat.top;
      ctx.fillRect(backX + 2, backY + 1, backW - 4, backH - 2);

      // Lumbar support highlight
      ctx.fillStyle = isExecutive ? '#ca8a04' : '#38bdf8';
      ctx.fillRect(cx - 2, backY + 3, 4, 2);
    } else if (facing === 'up') {
      const backW = 14;
      const backH = 10;
      const backX = cx - backW / 2;
      const backY = seatY - 2;

      ctx.fillStyle = mat.front;
      ctx.beginPath();
      ctx.roundRect(backX, backY, backW, backH, 2);
      ctx.fill();

      ctx.fillStyle = mat.bevel;
      ctx.fillRect(backX + 1, backY + 1, backW - 2, 1);
    }
  },

  render: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    ChairTemplate.base(ctx, props);
    ChairTemplate.frontFace(ctx, props);
    ChairTemplate.topSurface(ctx, props);
    ChairTemplate.sideFace(ctx, props);
    if (ChairTemplate.details) {
      ChairTemplate.details(ctx, props);
    }

    ctx.restore();
  },
};

// ============================================================================
// 5. SPRITE TEMPLATE: 42U DATACENTER SERVER RACK
// ============================================================================

export interface ServerRackSpriteProps {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const ServerRackTemplate: IsometricTemplate<ServerRackSpriteProps> = {
  name: 'ServerRack',

  // 1. CONTACT SHADOW
  contactShadow: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.beginPath();
    ctx.roundRect(-2, props.height - 4, props.width + 4, 8, 2);
    ctx.fill();

    ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
    ctx.beginPath();
    ctx.roundRect(-4, props.height - 1, props.width + 8, 12, 3);
    ctx.fill();

    ctx.restore();
  },

  // 2. BASE LAYER (Chassis Outer Shell & Floor Plinth)
  base: (ctx, props) => {
    const { width, height } = props;

    // Chassis frame
    ctx.fillStyle = '#06070a';
    ctx.fillRect(0, 0, width, height);

    // Floor plinth & kickplate
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(1, height - 4, width - 2, 4);
    ctx.fillStyle = '#334155';
    ctx.fillRect(2, height - 3, width - 4, 1);
  },

  // 3. FRONT FACE LAYER (19" Vertical Rails & Tiered Server Blade Trays)
  frontFace: (ctx, props) => {
    const { width, height } = props;
    const railX = 3;
    const railY = 6;
    const railW = width - 6;
    const railH = height - 10;

    // Recessed mounting channel
    ctx.fillStyle = '#0b0e14';
    ctx.fillRect(railX, railY, railW, railH);

    // Blade tiers
    const tierHeight = 5;
    const numTiers = Math.floor(railH / tierHeight);

    for (let i = 0; i < numTiers; i++) {
      const ty = railY + i * tierHeight;
      ctx.fillStyle = i % 2 === 0 ? '#141822' : '#1c2230';
      ctx.fillRect(railX + 1, ty, railW - 2, tierHeight - 1);

      ctx.fillStyle = '#2b3345';
      ctx.fillRect(railX + 1, ty, railW - 2, 1);

      // Intake grill
      ctx.fillStyle = '#080a0f';
      ctx.fillRect(railX + 3, ty + 1, railW - 14, tierHeight - 2);
    }
  },

  // 4. TOP SURFACE LAYER (Illuminated Roof Plate & Cooling Fan Cowls)
  topSurface: (ctx, props) => {
    const { width } = props;

    ctx.fillStyle = '#1e222d';
    ctx.fillRect(1, 1, width - 2, 5);
    ctx.fillStyle = '#333a4c';
    ctx.fillRect(1, 1, width - 2, 1);

    // Top exhaust fans
    ctx.fillStyle = '#0a0d14';
    ctx.beginPath();
    ctx.arc(width * 0.3, 3.5, 2, 0, Math.PI * 2);
    ctx.arc(width * 0.7, 3.5, 2, 0, Math.PI * 2);
    ctx.fill();
  },

  // 5. SIDE FACE LAYER (Side Elevation Depth & Shading)
  sideFace: (ctx, props) => {
    const { width, height } = props;

    ctx.fillStyle = '#0a0c10';
    ctx.fillRect(0, 0, 1, height);
    ctx.fillRect(width - 1, 0, 1, height);
  },

  // 6. DETAILS LAYER (Blinking Status LEDs, Cable Runs & Glass Door Sheen)
  details: (ctx, props, now = 0) => {
    const { width, height } = props;
    const railX = 3;
    const railY = 6;
    const railW = width - 6;
    const railH = height - 10;
    const tierHeight = 5;
    const numTiers = Math.floor(railH / tierHeight);

    for (let i = 0; i < numTiers; i++) {
      const ty = railY + i * tierHeight;
      const ledSeed = i * 137 + now / 180;
      const led1 = Math.sin(ledSeed) > 0.2;
      const led2 = Math.cos(ledSeed * 1.3) > -0.1;
      const isAlert = i === 3 && Math.sin(now / 150) > 0.5;

      // Status indicator lights
      ctx.fillStyle = isAlert ? '#ef4444' : led1 ? '#10b981' : '#047857';
      ctx.fillRect(railW - 7, ty + 1, 2, 1);

      ctx.fillStyle = led2 ? '#06b6d4' : '#0e7490';
      ctx.fillRect(railW - 4, ty + 1, 2, 1);

      // Patch cable loops
      if (i % 3 === 0) {
        ctx.strokeStyle = i % 6 === 0 ? '#38bdf8' : '#eab308';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(railX + 7, ty + 3, 2, 0, Math.PI);
        ctx.stroke();
      }
    }

    // Tinted glass door with glossy reflection
    ctx.strokeStyle = '#38bdf830';
    ctx.lineWidth = 1;
    ctx.strokeRect(railX, railY, railW, railH);

    ctx.fillStyle = 'rgba(6, 182, 212, 0.08)';
    ctx.beginPath();
    ctx.moveTo(railX + 2, railY);
    ctx.lineTo(railX + 8, railY);
    ctx.lineTo(railX + 2, railY + railH);
    ctx.fill();
  },

  render: (ctx, props, now = 0) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    ServerRackTemplate.base(ctx, props);
    ServerRackTemplate.frontFace(ctx, props);
    ServerRackTemplate.topSurface(ctx, props);
    ServerRackTemplate.sideFace(ctx, props);
    if (ServerRackTemplate.details) {
      ServerRackTemplate.details(ctx, props, now);
    }

    ctx.restore();
  },
};

// ============================================================================
// 6. SPRITE TEMPLATE: FILING CABINET & STORAGE CREDENZA
// ============================================================================

export interface CabinetSpriteProps {
  x: number;
  y: number;
  width: number;
  height: number;
  material?: 'steel' | 'mahogany' | 'oak';
  drawerTiers?: number;
}

export const CabinetTemplate: IsometricTemplate<CabinetSpriteProps> = {
  name: 'Cabinet',

  // 1. CONTACT SHADOW
  contactShadow: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.beginPath();
    ctx.roundRect(-1, props.height - 3, props.width + 2, 6, 2);
    ctx.fill();

    ctx.restore();
  },

  // 2. BASE LAYER (Chassis Foundation & Plinth)
  base: (ctx, props) => {
    const { width, height } = props;

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, height);

    ctx.fillStyle = '#090a0f';
    ctx.fillRect(1, height - 3, width - 2, 3);
  },

  // 3. FRONT FACE LAYER (Tiered Drawer Panels, Recessed Pulls, Label Cards)
  frontFace: (ctx, props) => {
    const { width, height, drawerTiers = 3 } = props;
    const topH = 3;
    const usableH = height - topH - 4;
    const drawerH = Math.floor(usableH / drawerTiers);

    for (let d = 0; d < drawerTiers; d++) {
      const dy = topH + 1 + d * drawerH;

      // Drawer recess
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(2, dy, width - 4, drawerH - 1);

      ctx.fillStyle = '#334155';
      ctx.fillRect(2, dy, width - 4, 1);

      // Card/label index holder
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(width / 2 - 3, dy + 2, 6, 1.5);

      // Chrome drawer pull handle
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(width / 2 - 4, dy + Math.floor(drawerH / 2), 8, 1.5);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(width / 2 - 4, dy + Math.floor(drawerH / 2), 8, 0.8);
    }
  },

  // 4. TOP SURFACE LAYER (Illuminated Beveled Top Slab)
  topSurface: (ctx, props) => {
    const { width } = props;

    ctx.fillStyle = '#475569';
    ctx.fillRect(1, 1, width - 2, 3);

    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(1, 1, width - 2, 1);
  },

  // 5. SIDE FACE LAYER (Side Elevation Panel & Trim)
  sideFace: (ctx, props) => {
    const { width, height } = props;

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, 0, 1, height);
    ctx.fillRect(width - 1, 0, 1, height);
  },

  // 6. DETAILS LAYER (Top Accessory / Paper Stack)
  details: (ctx, props) => {
    const { width } = props;

    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(3, 0, 6, 1);
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(width - 7, 0, 4, 1);
  },

  render: (ctx, props) => {
    ctx.save();
    ctx.translate(props.x, props.y);

    CabinetTemplate.base(ctx, props);
    CabinetTemplate.frontFace(ctx, props);
    CabinetTemplate.topSurface(ctx, props);
    CabinetTemplate.sideFace(ctx, props);
    if (CabinetTemplate.details) {
      CabinetTemplate.details(ctx, props);
    }

    ctx.restore();
  },
};

// ============================================================================
// 7. HELPER RENDERERS FOR MONITORS & DESK PROPS
// ============================================================================

function renderDeskDisplays(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  setup: string,
  screenColor: string,
  now: number
) {
  const centerX = deskW / 2;
  const baseY = 3;

  // Mount clamp
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(centerX - 4, baseY - 2, 8, 4);
  ctx.fillStyle = '#334155';
  ctx.fillRect(centerX - 1, baseY - 6, 2, 6);

  if (setup === 'triple') {
    renderSingleScreen(ctx, centerX - 26, baseY - 12, 18, 12, screenColor, 'terminal', now);
    renderSingleScreen(ctx, centerX - 12, baseY - 14, 24, 14, screenColor, 'ide', now);
    renderSingleScreen(ctx, centerX + 14, baseY - 12, 18, 12, screenColor, 'chart', now);
  } else if (setup === 'curved') {
    const mw = 36;
    const mh = 14;
    const mx = centerX - mw / 2;
    const my = baseY - 14;

    ctx.fillStyle = '#475569';
    ctx.fillRect(centerX - 5, my + mh, 10, 2);
    ctx.fillRect(centerX - 1, my + mh - 3, 2, 3);

    ctx.fillStyle = '#090a0f';
    ctx.beginPath();
    ctx.roundRect(mx, my, mw, mh, 2);
    ctx.fill();

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(mx + 1, my + 1, mw - 2, mh - 2);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(mx + 2, my + 2, mw - 4, mh - 4);

    ctx.fillStyle = '#ec4899';
    ctx.fillRect(mx + 4, my + 4, 8, 5);
    ctx.fillStyle = '#8b5cf6';
    ctx.fillRect(mx + 14, my + 4, 10, 3);
    ctx.fillStyle = '#06b6d4';
    ctx.fillRect(mx + 26, my + 4, 6, 6);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.beginPath();
    ctx.moveTo(mx + 4, my + 2);
    ctx.lineTo(mx + 10, my + 2);
    ctx.lineTo(mx + 2, my + mh - 2);
    ctx.lineTo(mx + 2, my + 6);
    ctx.fill();
  } else if (setup === 'vertical_dual') {
    renderSingleScreen(ctx, centerX - 20, baseY - 18, 12, 20, screenColor, 'code_vertical', now);
    renderSingleScreen(ctx, centerX - 5, baseY - 13, 22, 13, screenColor, 'ide', now);
  } else if (setup === 'single') {
    renderSingleScreen(ctx, centerX - 12, baseY - 13, 24, 13, screenColor, 'ide', now);
  } else {
    // Dual standard
    renderSingleScreen(ctx, centerX - 22, baseY - 13, 20, 13, screenColor, 'ide', now);
    renderSingleScreen(ctx, centerX + 2, baseY - 13, 20, 13, screenColor, 'terminal', now);
  }
}

function renderSingleScreen(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  _screenColor: string,
  contentType: 'ide' | 'terminal' | 'chart' | 'code_vertical',
  now: number
) {
  // Stand
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(x + w / 2 - 4, y + h, 8, 2);
  ctx.fillStyle = '#334155';
  ctx.fillRect(x + w / 2 - 1, y + h - 3, 2, 3);

  // Bezel
  ctx.fillStyle = '#050608';
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(x + 1, y, w - 2, 1);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(x, y + 1, 1, h - 2);

  // Screen active panel
  ctx.fillStyle = '#030712';
  ctx.fillRect(x + 1, y + 1, w - 2, h - 2);

  if (contentType === 'terminal') {
    ctx.fillStyle = '#022c22';
    ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
    ctx.fillStyle = '#10b981';
    ctx.fillRect(x + 3, y + 3, 4, 1);
    ctx.fillStyle = '#34d399';
    ctx.fillRect(x + 8, y + 3, w - 11, 1);
    ctx.fillRect(x + 3, y + 5, w - 7, 1);
    ctx.fillRect(x + 3, y + 7, w - 10, 1);
    if (Math.sin(now / 250) > 0) {
      ctx.fillStyle = '#a7f3d0';
      ctx.fillRect(x + 3, y + 9, 2, 2);
    }
  } else if (contentType === 'code_vertical') {
    ctx.fillStyle = '#090d16';
    ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
    for (let ly = y + 3; ly < y + h - 3; ly += 2) {
      const isIndented = (ly / 2) % 3 === 0;
      ctx.fillStyle = (ly / 2) % 2 === 0 ? '#38bdf8' : '#a855f7';
      ctx.fillRect(isIndented ? x + 5 : x + 3, ly, isIndented ? w - 9 : w - 7, 1);
    }
  } else if (contentType === 'chart') {
    ctx.fillStyle = '#0c101d';
    ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(x + 3, y + h - 5, 2, 2);
    ctx.fillRect(x + 6, y + h - 7, 2, 4);
    ctx.fillRect(x + 9, y + h - 6, 2, 3);
    ctx.fillRect(x + 12, y + h - 8, 2, 5);
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x + 3, y + 4);
    ctx.lineTo(x + 8, y + 6);
    ctx.lineTo(x + 13, y + 3);
    ctx.stroke();
  } else {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(x + 2, y + 2, 3, h - 4);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(x + 6, y + 3, 5, 1);
    ctx.fillStyle = '#fbbf24';
    ctx.fillRect(x + 12, y + 3, 4, 1);
    ctx.fillStyle = '#ec4899';
    ctx.fillRect(x + 7, y + 5, 6, 1);
    ctx.fillStyle = '#10b981';
    ctx.fillRect(x + 6, y + 7, w - 9, 1);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(x + 7, y + 9, 4, 1);
  }

  // Specular sheen
  ctx.fillStyle = 'rgba(255, 255, 255, 0.16)';
  ctx.beginPath();
  ctx.moveTo(x + 2, y + 2);
  ctx.lineTo(x + 6, y + 2);
  ctx.lineTo(x + 2, y + 6);
  ctx.fill();

  // Power LED
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(x + w - 2, y + h - 1, 1, 1);
}

function renderDeskProps(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  desktopH: number,
  accessories: string[],
  lampOn: boolean | undefined,
  deskType: string,
  now: number
) {
  // Gooseneck Lamp
  if (accessories.includes('lamp') || deskType === 'manager') {
    const lampX = 4;
    const lampY = 4;

    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.ellipse(lampX + 3, lampY + 8, 3, 1.5, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = deskType === 'manager' ? '#ca8a04' : '#64748b';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(lampX + 3, lampY + 8);
    ctx.lineTo(lampX + 5, lampY + 3);
    ctx.lineTo(lampX + 8, lampY + 4);
    ctx.stroke();

    ctx.fillStyle = deskType === 'manager' ? '#15803d' : '#e2e8f0';
    ctx.beginPath();
    ctx.roundRect(lampX + 6, lampY + 2, 5, 3, 1);
    ctx.fill();

    if (lampOn) {
      ctx.fillStyle = 'rgba(254, 240, 138, 0.22)';
      ctx.beginPath();
      ctx.ellipse(lampX + 9, lampY + 9, 10, 6, 0.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Coffee mug with steam
  if (accessories.includes('coffee') || deskType === 'developer') {
    const mugX = deskW - 8;
    const mugY = desktopH - 11;

    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(mugX, mugY, 4, 5);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(mugX + 3, mugY, 1, 5);

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(mugX + 4.5, mugY + 2.5, 1.5, -Math.PI / 2, Math.PI / 2);
    ctx.stroke();

    ctx.fillStyle = '#451a03';
    ctx.fillRect(mugX + 1, mugY + 1, 2, 1);

    const steamY = (now / 150) % 6;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.fillRect(mugX + 1 + (Math.sin(now / 200) > 0 ? 1 : 0), mugY - 2 - steamY, 1, 2);
  }

  // Potted Succulent
  if (accessories.includes('plant')) {
    const px = deskW - 8;
    const py = 3;

    ctx.fillStyle = '#c2410c';
    ctx.fillRect(px, py + 3, 5, 4);
    ctx.fillStyle = '#9a3412';
    ctx.fillRect(px + 4, py + 3, 1, 4);

    ctx.fillStyle = '#15803d';
    ctx.fillRect(px + 1, py + 1, 3, 2);
    ctx.fillStyle = '#22c55e';
    ctx.fillRect(px + 2, py, 2, 2);
  }

  // Studio Headphones
  if (accessories.includes('headphones')) {
    const hx = 4;
    const hy = desktopH - 12;

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(hx + 3, hy + 3, 3, Math.PI, 0);
    ctx.stroke();

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(hx - 1, hy + 2, 2, 4);
    ctx.fillRect(hx + 5, hy + 2, 2, 4);
  }

  // Open Notebook & Pen
  if (accessories.includes('notebook') || deskType === 'manager') {
    const nx = deskW - 14;
    const ny = desktopH - 12;

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(nx, ny, 7, 5);
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(nx + 3, ny, 1, 5);
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(nx + 1, ny + 1, 2, 1);
    ctx.fillRect(nx + 1, ny + 3, 2, 1);
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(nx + 8, ny, 1, 5);
  }

  // Sticky Notes
  if (accessories.includes('notes')) {
    const stX = 5;
    const stY = desktopH - 10;
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(stX, stY, 3, 3);
    ctx.fillStyle = '#f43f5e';
    ctx.fillRect(stX + 4, stY, 3, 3);
  }
}

// ============================================================================
// 8. UNIFIED PIXEL ASSETS REGISTRY
// ============================================================================

export const PixelAssets = {
  palettes: PIXEL_PALETTES,
  desk: DeskTemplate,
  chair: ChairTemplate,
  serverRack: ServerRackTemplate,
  cabinet: CabinetTemplate,

  // Direct Rendering Accessors
  renderDesk: (ctx: CanvasRenderingContext2D, desk: Desk2D, now = 0) => {
    DeskTemplate.render(ctx, desk, now);
  },
  renderDeskShadow: (ctx: CanvasRenderingContext2D, desk: Desk2D) => {
    DeskTemplate.contactShadow(ctx, desk);
  },

  renderChair: (
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    facing: Direction = 'down',
    isExecutive = false
  ) => {
    ChairTemplate.render(ctx, { x, y, facing, isExecutive });
  },
  renderChairShadow: (ctx: CanvasRenderingContext2D, x: number, y: number) => {
    ChairTemplate.contactShadow(ctx, { x, y });
  },

  renderServerRack: (
    ctx: CanvasRenderingContext2D,
    f: Furniture2D | InteractivePOI,
    now = 0
  ) => {
    ServerRackTemplate.render(ctx, f, now);
  },
  renderServerRackShadow: (
    ctx: CanvasRenderingContext2D,
    f: Furniture2D | InteractivePOI
  ) => {
    ServerRackTemplate.contactShadow(ctx, f);
  },

  renderCabinet: (
    ctx: CanvasRenderingContext2D,
    prop: EnvironmentalProp2D,
    tiers = 3
  ) => {
    CabinetTemplate.render(ctx, {
      x: prop.x,
      y: prop.y,
      width: prop.width,
      height: prop.height,
      drawerTiers: tiers,
    });
  },
  renderCabinetShadow: (
    ctx: CanvasRenderingContext2D,
    prop: EnvironmentalProp2D
  ) => {
    CabinetTemplate.contactShadow(ctx, {
      x: prop.x,
      y: prop.y,
      width: prop.width,
      height: prop.height,
    });
  },
};
