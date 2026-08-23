import type { Desk2D, Direction, EnvironmentalProp2D, Furniture2D, InteractivePOI } from './types';

/**
 * 2.5D High-Fidelity Pixel-Art Furniture & Environmental Architecture Renderer
 * 
 * Rebuilds all office furniture as true 3/4 perspective pixel-art objects
 * with dimensional volume, illuminated top planes, shaded front/side faces,
 * beveled edges, pedestal drawers, mechanical hardware, cable routing,
 * and realistic contact shadows.
 */

// ==========================================
// COLOR PALETTES FOR AUTHENTIC MATERIALS
// ==========================================
const PALETTES = {
  wood: {
    carbon: { top: '#1c1e24', bevel: '#2e323d', front: '#131418', side: '#0d0e11', trim: '#3b404e', shadow: '#07080a' },
    dark_mahogany: { top: '#451a13', bevel: '#61281e', front: '#2e0f0a', side: '#1f0906', trim: '#783528', shadow: '#100403' },
    walnut: { top: '#38281c', bevel: '#4f3b2c', front: '#261b12', side: '#1a120b', trim: '#694f3a', shadow: '#0e0905' },
    oak: { top: '#4d3d2c', bevel: '#6b5740', front: '#362a1e', side: '#241c13', trim: '#856d51', shadow: '#140f09' },
    light_birch: { top: '#5e4e3b', bevel: '#7a6750', front: '#423729', side: '#2e261c', trim: '#968167', shadow: '#19150f' },
  },
  metal: {
    steel: { top: '#475569', bevel: '#64748b', front: '#334155', side: '#1e293b', trim: '#94a3b8', dark: '#0f172a' },
    dark_chassis: { top: '#1e2029', bevel: '#2b2e3b', front: '#14161d', side: '#0c0d12', trim: '#3f4357', dark: '#06070a' },
    chrome: { top: '#e2e8f0', bevel: '#f8fafc', front: '#94a3b8', side: '#64748b', trim: '#ffffff', dark: '#334155' },
    brass: { top: '#ca8a04', bevel: '#eab308', front: '#854d0e', side: '#713f12', trim: '#fef08a', dark: '#422006' },
  },
  fabric: {
    executive_leather: { top: '#542617', bevel: '#753925', front: '#3a180d', side: '#250e07', cushion: '#632e1d' },
    mesh_black: { top: '#1f2430', bevel: '#2d3345', front: '#141720', side: '#0d0f14', cushion: '#272e3d' },
    fabric_indigo: { top: '#3730a3', bevel: '#4f46e5', front: '#252174', side: '#19174f', cushion: '#4338ca' },
    fabric_teal: { top: '#0f766e', bevel: '#14b8a6', front: '#094e49', side: '#043431', cushion: '#115e59' },
    fabric_amber: { top: '#b45309', bevel: '#f59e0b', front: '#78350f', side: '#451a03', cushion: '#92400e' },
  },
};

// ==========================================
// 1. DESKS & INDIVIDUAL WORKSTATIONS (3D REBUILD)
// ==========================================

export function drawDeskShadow(ctx: CanvasRenderingContext2D, desk: Desk2D) {
  ctx.save();
  ctx.translate(desk.x, desk.y);

  // Soft blurred ambient occlusion drop shadow
  ctx.shadowColor = 'rgba(0, 0, 0, 0.85)';
  ctx.shadowBlur = 10;
  ctx.shadowOffsetY = 3;

  // Deep contact shadow directly under the desk footprint
  ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
  ctx.beginPath();
  ctx.roundRect(-2, desk.height - 6, desk.width + 4, 12, 3);
  ctx.fill();

  // Directional cast shadow extending downward
  ctx.shadowBlur = 8;
  ctx.shadowOffsetY = 4;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.beginPath();
  ctx.roundRect(-4, desk.height - 2, desk.width + 8, 14, 4);
  ctx.fill();

  ctx.restore();
}

/**
 * Renders a full 3/4 perspective workstation sprite with:
 * - Thick beveled wooden/carbon desktop with top highlight
 * - Under-desk pedestal drawer unit with handles & seams
 * - Steel legs & foot crossbars
 * - Modesty panel & cable management drop
 * - Premium desk mat
 * - Multi-monitor setups with stands & bezel highlights
 * - Real mechanical keyboard, mouse, headphones, coffee mug, desk lamp
 */
export function draw3DDesk(ctx: CanvasRenderingContext2D, desk: Desk2D, now: number) {
  ctx.save();
  ctx.translate(desk.x, desk.y);

  const {
    width,
    height,
    woodTone = 'carbon',
    deskType = 'developer',
    monitorSetup = 'dual',
    screenColor,
    accessories = [],
    lampOn = true,
  } = desk;

  const mat = PALETTES.wood[woodTone] || PALETTES.wood.carbon;

  // Geometry dimensions
  const topThickness = 5;
  const desktopH = height - 4;
  const legInset = 4;
  const hasDrawerLeft = width >= 60;

  // 1. UNDER-DESK STRUCTURE & KNEEWELL CAVITY
  // Back modesty panel (dark recessed area)
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(legInset + 2, 8, width - (legInset * 2 + 4), desktopH - 6);

  // Recessed modesty board
  ctx.fillStyle = mat.front;
  ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), desktopH - 12);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
  ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), 3); // shadow under top

  // Cable routing trough & grommet cables
  if (accessories.includes('cables')) {
    ctx.fillStyle = '#050608';
    ctx.fillRect(width / 2 - 6, 8, 12, desktopH - 8);
    // Colored wire bundle
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

  // 2. PEDESTAL DRAWER UNIT (Right side)
  if (hasDrawerLeft) {
    const drawerW = 16;
    const drawerX = width - drawerW - legInset;
    const drawerY = 8;
    const drawerH = desktopH - 6;

    // Drawer unit body
    ctx.fillStyle = mat.side;
    ctx.fillRect(drawerX, drawerY, drawerW, drawerH);

    // Front face
    ctx.fillStyle = mat.front;
    ctx.fillRect(drawerX + 1, drawerY, drawerW - 1, drawerH);

    // 3 Individual Drawer tiers with seams
    const tierH = Math.floor(drawerH / 3);
    for (let i = 0; i < 3; i++) {
      const ty = drawerY + i * tierH;
      // Drawer gap seam
      ctx.fillStyle = '#050608';
      ctx.fillRect(drawerX + 1, ty, drawerW - 1, 1);

      // Drawer panel face
      ctx.fillStyle = mat.bevel;
      ctx.fillRect(drawerX + 2, ty + 1, drawerW - 3, tierH - 2);

      // Metallic pull handle
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 2);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 1); // highlight
    }
  }

  // 3. STEEL LEGS & FOOT CROSSBARS
  const legW = 3;
  // Left leg
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(legInset, 8, legW, desktopH + 2);
  ctx.fillStyle = '#334155';
  ctx.fillRect(legInset, 8, 1, desktopH + 2); // left leg highlight
  // Foot leveler
  ctx.fillStyle = '#64748b';
  ctx.fillRect(legInset - 1, desktopH + 1, legW + 2, 2);

  // Right leg (if no drawer unit, or behind it)
  if (!hasDrawerLeft) {
    ctx.fillStyle = '#090a0f';
    ctx.fillRect(width - legInset - legW, 8, legW, desktopH + 2);
    ctx.fillStyle = '#334155';
    ctx.fillRect(width - legInset - legW, 8, 1, desktopH + 2);
    ctx.fillStyle = '#64748b';
    ctx.fillRect(width - legInset - legW - 1, desktopH + 1, legW + 2, 2);
  }

  // 4. PC TOWER / DOCKING STATION UNDER DESK
  if (deskType === 'developer' || deskType === 'systems' || deskType === 'data') {
    const pcX = legInset + 3;
    const pcY = desktopH - 16;
    const pcW = 10;
    const pcH = 16;

    // Chassis body
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(pcX, pcY, pcW, pcH);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(pcX + 1, pcY + 1, pcW - 2, pcH - 2);

    // Front intake mesh
    ctx.fillStyle = '#020617';
    ctx.fillRect(pcX + 2, pcY + 4, pcW - 4, pcH - 6);

    // RGB Fan Glow & Activity Blinker
    const fanPulse = Math.sin(now / 200) > 0 ? '#06b6d4' : '#0284c7';
    ctx.fillStyle = fanPulse;
    ctx.fillRect(pcX + 3, pcY + 6, 4, 4);

    // Power button & USB ports
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(pcX + 3, pcY + 2, 2, 1);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(pcX + 6, pcY + 2, 1, 1);
  }

  // 5. MAIN DESKTOP SLAB (3D PERSPECTIVE)
  // Front face (thickness & drop shadow)
  ctx.fillStyle = mat.front;
  ctx.fillRect(0, desktopH - topThickness, width, topThickness);
  // Bottom shadow rim of front face
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(0, desktopH - 1, width, 1);

  // Left & Right side edge bevels
  ctx.fillStyle = mat.side;
  ctx.fillRect(0, 0, 1, desktopH);
  ctx.fillRect(width - 1, 0, 1, desktopH);

  // Base top surface slab
  ctx.fillStyle = mat.top;
  ctx.fillRect(1, 1, width - 2, desktopH - topThickness);

  // Distinct lighter-toned illuminated desktop surface layer
  ctx.fillStyle = 'rgba(255, 255, 255, 0.07)';
  ctx.fillRect(2, 2, width - 4, desktopH - topThickness - 2);

  // Wood grain streaks / brushed-metal fine horizontal highlight lines
  ctx.strokeStyle = mat.bevel;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let gy = 4; gy < desktopH - topThickness - 2; gy += 3) {
    ctx.moveTo(3, gy);
    ctx.lineTo(width - 3, gy);
  }
  ctx.stroke();

  // Angled cross-grain texture streaks
  ctx.strokeStyle = mat.trim + '30';
  for (let gx = 8; gx < width - 8; gx += 12) {
    ctx.beginPath();
    ctx.moveTo(gx, 2);
    ctx.lineTo(gx + 5, desktopH - topThickness - 1);
    ctx.stroke();
  }

  // Top-left primary specular highlight rim (light source from top-left)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.22)';
  ctx.fillRect(1, 1, width - 2, 1); // top edge
  ctx.fillRect(1, 1, 1, desktopH - topThickness); // left edge

  // Front bevel edge line
  ctx.fillStyle = mat.bevel;
  ctx.fillRect(1, desktopH - topThickness - 1, width - 2, 1);

  // 6. OVERSIZED ERGONOMIC DESK MAT WITH STITCHED RIM & TWO-TONE FILL
  const matInsetX = Math.floor(width * 0.12);
  const matW = width - matInsetX * 2;
  const matH = desktopH - topThickness - 4;
  const matY = 3;

  // Mat base
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(matInsetX, matY, matW, matH);
  // Inner textured surface
  ctx.fillStyle = '#11141c';
  ctx.fillRect(matInsetX + 1, matY + 1, matW - 2, matH - 2);

  // Top-left mat highlight & stitched hem
  ctx.strokeStyle = deskType === 'manager' ? '#ca8a04' : '#38bdf850';
  ctx.lineWidth = 1;
  ctx.strokeRect(matInsetX + 0.5, matY + 0.5, matW - 1, matH - 1);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
  ctx.fillRect(matInsetX + 1, matY + 1, matW - 2, 1);

  // 7. CRISP KEYBOARD & MOUSE SILHOUETTE
  const kbW = Math.min(24, matW - 14);
  const kbH = 8;
  const kbX = matInsetX + 4;
  const kbY = matY + matH - kbH - 2;

  // Mechanical Keyboard Base Chassis (2-tone bevel)
  ctx.fillStyle = '#090d16';
  ctx.fillRect(kbX, kbY, kbW, kbH);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(kbX + 1, kbY + 1, kbW - 2, kbH - 2);
  // Top highlight edge on keyboard chassis
  ctx.fillStyle = '#475569';
  ctx.fillRect(kbX + 1, kbY, kbW - 2, 1);

  // Keycap Matrix with RGB Underglow and distinct Key Rows
  const keyPulse = Math.sin(now / 500);
  const keyColor = deskType === 'designer' ? '#f43f5e' : keyPulse > 0 ? '#38bdf8' : '#818cf8';
  for (let kx = kbX + 2; kx < kbX + kbW - 3; kx += 3) {
    // Number/Function row
    ctx.fillStyle = keyColor;
    ctx.fillRect(kx, kbY + 2, 2, 1.5);
    // Home row keys
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(kx, kbY + 4, 2, 1.5);
  }
  // Spacebar silhouette
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(kbX + Math.floor(kbW / 2) - 4, kbY + 6, 8, 1);

  // Ergonomic Sculpted Mouse
  const mouseX = matInsetX + matW - 8;
  const mouseY = kbY + 1;
  // Mouse base shadow & chassis
  ctx.fillStyle = '#090d16';
  ctx.beginPath();
  ctx.roundRect(mouseX, mouseY, 5, 7, 2);
  ctx.fill();
  // Mouse top shell (2-tone)
  ctx.fillStyle = '#1e293b';
  ctx.beginPath();
  ctx.roundRect(mouseX + 0.5, mouseY + 0.5, 4, 6, 1.5);
  ctx.fill();
  // Top-left highlight
  ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
  ctx.fillRect(mouseX + 1, mouseY + 1, 2, 1);
  // Scroll wheel & RGB indicator
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(mouseX + 2, mouseY + 2, 1, 2);

  // 8. MONITORS & MULTI-DISPLAY ARRAYS (3D VOLUMETRIC REBUILD)
  drawWorkstationMonitors(ctx, width, desktopH, monitorSetup, screenColor, deskType, now);

  // 9. HANDCRAFTED ACCESSORIES & PERSONAL STORYTELLING
  drawWorkstationProps(ctx, width, desktopH, accessories, lampOn, deskType, now);

  ctx.restore();
}

/**
 * Multi-Monitor Display Rig Renderer
 */
function drawWorkstationMonitors(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  _desktopH: number,
  setup: string,
  screenColor: string,
  _deskType: string,
  now: number
) {
  const centerX = deskW / 2;
  const baseY = 3;

  // Heavy-duty Dual-Arm Desktop Mount (Pole & Crossbar)
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(centerX - 4, baseY - 2, 8, 4); // base clamp
  ctx.fillStyle = '#334155';
  ctx.fillRect(centerX - 1, baseY - 6, 2, 6); // riser pole

  if (setup === 'executive') {
    // EXECUTIVE SUITE MONITOR RIG (Wide OLED Display with Gold Trim)
    drawSingleMonitor(ctx, centerX - 16, baseY - 14, 32, 14, screenColor, '#ca8a04', 'ide', now);
  } else if (setup === 'triple') {
    // TRIPLE MONITOR COCKPIT (Data / Systems / Ops)
    drawSingleMonitor(ctx, centerX - 26, baseY - 12, 18, 12, screenColor, '#10b981', 'terminal', now);
    drawSingleMonitor(ctx, centerX - 12, baseY - 14, 24, 14, screenColor, '#38bdf8', 'ide', now);
    drawSingleMonitor(ctx, centerX + 14, baseY - 12, 18, 12, screenColor, '#f59e0b', 'chart', now);
  } else if (setup === 'curved') {
    // 34" ULTRA-WIDE CURVED DISPLAY (Designer / Architect)
    const mw = 38;
    const mh = 14;
    const mx = centerX - mw / 2;
    const my = baseY - 14;

    // Curved Stand
    ctx.fillStyle = '#475569';
    ctx.fillRect(centerX - 5, my + mh, 10, 2);
    ctx.fillRect(centerX - 1, my + mh - 3, 2, 3);

    // Bezel
    ctx.fillStyle = '#090a0f';
    ctx.beginPath();
    ctx.roundRect(mx, my, mw, mh, 2);
    ctx.fill();

    // Curved screen curve highlight
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(mx + 1, my + 1, mw - 2, mh - 2);

    // Active OLED Screen Content
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(mx + 2, my + 2, mw - 4, mh - 4);

    // Art / Design UI
    ctx.fillStyle = '#ec4899';
    ctx.fillRect(mx + 4, my + 4, 8, 5);
    ctx.fillStyle = '#8b5cf6';
    ctx.fillRect(mx + 14, my + 4, 10, 3);
    ctx.fillStyle = '#06b6d4';
    ctx.fillRect(mx + 26, my + 4, 6, 6);

    // Specular glass glare diagonal
    ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.beginPath();
    ctx.moveTo(mx + 4, my + 2);
    ctx.lineTo(mx + 10, my + 2);
    ctx.lineTo(mx + 2, my + mh - 2);
    ctx.lineTo(mx + 2, my + 6);
    ctx.fill();
  } else if (setup === 'vertical_dual') {
    // 1 Vertical Code Monitor + 1 Landscape Primary Monitor
    drawSingleMonitor(ctx, centerX - 20, baseY - 18, 12, 20, screenColor, '#10b981', 'code_vertical', now);
    drawSingleMonitor(ctx, centerX - 5, baseY - 13, 22, 13, screenColor, '#38bdf8', 'ide', now);
  } else if (setup === 'laptop_monitor') {
    // 1 Landscape Primary Monitor + 1 Open Side Laptop
    drawSingleMonitor(ctx, centerX - 20, baseY - 13, 22, 13, screenColor, '#38bdf8', 'ide', now);
    // Open Silver Laptop on Right
    const lx = centerX + 6;
    const ly = baseY + 4;
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(lx, ly - 7, 14, 9);
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(lx + 1, ly - 6, 12, 7);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(lx - 1, ly + 2, 16, 5);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(lx + 1, ly + 3, 12, 3);
  } else if (setup === 'single') {
    // Standard Single Monitor
    drawSingleMonitor(ctx, centerX - 12, baseY - 13, 24, 13, screenColor, '#a855f7', 'ide', now);
  } else {
    // DUAL MONITOR RIG (Default Developer Setup)
    drawSingleMonitor(ctx, centerX - 22, baseY - 13, 20, 13, screenColor, '#38bdf8', 'ide', now);
    drawSingleMonitor(ctx, centerX + 2, baseY - 13, 20, 13, screenColor, '#10b981', 'terminal', now);
  }
}

/**
 * High-detail single monitor sprite with stand, bezel, lit screen, and glass reflections
 */
function drawSingleMonitor(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  themeColor: string,
  accentColor: string,
  contentType: 'ide' | 'terminal' | 'chart' | 'code_vertical',
  now: number
) {
  // 1. Desk Stand Base & Upright (2-tone metallic finish)
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(x + w / 2 - 4, y + h, 8, 2);
  ctx.fillStyle = '#475569';
  ctx.fillRect(x + w / 2 - 4, y + h, 8, 1); // metallic stand highlight
  ctx.fillStyle = '#334155';
  ctx.fillRect(x + w / 2 - 1, y + h - 3, 2, 3);

  // 2. Bezel Chassis with 3D Depth
  ctx.fillStyle = '#050608';
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = '#334155';
  ctx.fillRect(x + 1, y, w - 2, 1); // top bezel specular line
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(x, y + 1, 1, h - 2); // left bezel edge

  // 3. Screen Glass Panel with Subtle Glowing Screen Ambient Fill
  const glowColor = accentColor || themeColor || '#38bdf8';
  ctx.fillStyle = '#020617';
  ctx.fillRect(x + 1, y + 1, w - 2, h - 2);

  // 4. Subtle Glowing Ambient Screen Fill (accent tint)
  ctx.fillStyle = glowColor + '30';
  ctx.fillRect(x + 2, y + 2, w - 4, h - 4);

  // 5. 1px Brighter Screen Rim
  ctx.strokeStyle = glowColor + '55';
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 1.5, y + 1.5, w - 3, h - 3);

  // 6. Render Dynamic High-Detail Screen Content
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

  // 7. Specular Glass Glare Diagonal
  ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
  ctx.beginPath();
  ctx.moveTo(x + 2, y + 2);
  ctx.lineTo(x + 6, y + 2);
  ctx.lineTo(x + 2, y + 6);
  ctx.fill();

  // 8. Power LED Indicator
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(x + w - 2, y + h - 1, 1, 1);
}

/**
 * Handcrafted props, beverages, stationery, and lamps
 */
function drawWorkstationProps(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  desktopH: number,
  accessories: string[],
  lampOn: boolean | undefined,
  deskType: string,
  now: number
) {
  // A. Gooseneck Anglepoise Desk Lamp / Brass Banker's Lamp
  if (accessories.includes('lamp') || deskType === 'manager' || deskType === 'architect') {
    const lampX = 4;
    const lampY = 4;

    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.ellipse(lampX + 3, lampY + 8, 3, 1.5, 0, 0, Math.PI * 2);
    ctx.fill();

    const isGold = deskType === 'manager' || deskType === 'architect';
    ctx.strokeStyle = isGold ? '#ca8a04' : '#64748b';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(lampX + 3, lampY + 8);
    ctx.lineTo(lampX + 5, lampY + 3);
    ctx.lineTo(lampX + 8, lampY + 4);
    ctx.stroke();

    ctx.fillStyle = isGold ? '#15803d' : '#e2e8f0';
    ctx.beginPath();
    ctx.roundRect(lampX + 6, lampY + 2, 5, 3, 1);
    ctx.fill();

    if (lampOn !== false) {
      ctx.fillStyle = 'rgba(254, 240, 138, 0.22)';
      ctx.beginPath();
      ctx.ellipse(lampX + 9, lampY + 9, 10, 6, 0.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // B. Steaming Ceramic Coffee Mug
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

  // C. Porcelain Espresso Cup & Saucer
  if (accessories.includes('espresso')) {
    const espX = deskW - 12;
    const espY = desktopH - 10;
    ctx.fillStyle = '#f8fafc';
    ctx.beginPath();
    ctx.ellipse(espX + 3, espY + 4, 4, 2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillRect(espX + 1, espY, 4, 4);
    ctx.fillStyle = '#451a03';
    ctx.fillRect(espX + 2, espY + 1, 2, 1);
  }

  // D. Potted Succulent / Bonsai
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

  // E. Studio Headphones
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

  // F. Open Paper Notebook & Pen
  if (accessories.includes('notebook') || deskType === 'manager' || deskType === 'architect') {
    const nx = deskW - 16;
    const ny = desktopH - 12;

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(nx, ny, 7, 5);
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(nx + 3, ny, 1, 5);
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(nx + 1, ny + 1, 2, 1);
    ctx.fillRect(nx + 1, ny + 3, 2, 1);
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(nx + 8, ny, 1, 5); // red pen
  }

  // G. Sticky Notes
  if (accessories.includes('notes') || accessories.includes('sticky_notes')) {
    const stX = 5;
    const stY = desktopH - 10;
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(stX, stY, 3, 3);
    ctx.fillStyle = '#f43f5e';
    ctx.fillRect(stX + 4, stY, 3, 3);
  }

  // H. Energy Drink Can / Soda
  if (accessories.includes('can') || accessories.includes('energy_drink')) {
    const canX = deskW - 8;
    const canY = 3;
    ctx.fillStyle = '#10b981';
    ctx.fillRect(canX, canY, 3, 6);
    ctx.fillStyle = '#22c55e';
    ctx.fillRect(canX, canY + 1, 3, 2);
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(canX + 1, canY - 1, 1, 1);
  }

  // I. Framed Certificate / Desk Plaque
  if (accessories.includes('cert_plaque')) {
    const cpX = 5;
    const cpY = 2;
    ctx.fillStyle = '#ca8a04';
    ctx.fillRect(cpX, cpY, 7, 6);
    ctx.fillStyle = '#fef08a';
    ctx.fillRect(cpX + 1, cpY + 1, 5, 4);
    ctx.fillStyle = '#ca8a04';
    ctx.fillRect(cpX + 2, cpY + 2, 3, 1);
  }

  // J. Pen Holder
  if (accessories.includes('pen_holder')) {
    const phX = deskW - 10;
    const phY = 4;
    ctx.fillStyle = '#334155';
    ctx.fillRect(phX, phY + 2, 4, 5);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(phX + 1, phY - 1, 1, 3);
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(phX + 2, phY - 2, 1, 4);
  }

  // K. Stacked Papers / Blueprint Folders
  if (accessories.includes('papers')) {
    const pX = 5;
    const pY = desktopH - 12;
    ctx.fillStyle = '#cbd5e1';
    ctx.fillRect(pX + 1, pY + 1, 7, 5);
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(pX, pY, 7, 5);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(pX + 1, pY + 1, 4, 1);
    ctx.fillRect(pX + 1, pY + 3, 5, 1);
  }

  // L. Translucent Sports Water Bottle
  if (accessories.includes('water_bottle')) {
    const wbX = 5;
    const wbY = 3;
    ctx.fillStyle = '#0284c7';
    ctx.fillRect(wbX, wbY + 1, 3, 7);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(wbX + 1, wbY + 2, 1, 5);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(wbX + 1, wbY, 1, 1);
  }
}

// ==========================================
// 2. ERGONOMIC 3D PIXEL-ART OFFICE CHAIRS
// ==========================================

export function drawChairShadow(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.save();
  ctx.shadowColor = 'rgba(0, 0, 0, 0.7)';
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.beginPath();
  ctx.ellipse(x + 10, y + 13, 8, 4.5, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/**
 * Rebuilds the office chair with authentic 3D geometry:
 * - 5-Spoke Chrome Wheelbase with mini casters
 * - Pneumatic Gas-Lift Center Cylinder
 * - Ergonomic Contoured Seat Pan with cushion depth
 * - Padded Armrests with metallic supports
 * - Breathable Mesh or Tufted Leather Backrest with Lumbar Spine
 */
export function draw3DChair(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  facing: Direction,
  _isOccupied: boolean,
  isExecutive: boolean
) {
  ctx.save();
  ctx.translate(x, y);

  const mat = isExecutive ? PALETTES.fabric.executive_leather : PALETTES.fabric.mesh_black;

  // 1. 5-SPOKE CHROME/GOLD CASTER WHEELBASE
  ctx.strokeStyle = isExecutive ? '#ca8a04' : '#64748b';
  ctx.lineWidth = 1.2;
  const cx = 10;
  const cy = 12;

  for (let i = 0; i < 5; i++) {
    const angle = (i * Math.PI * 2) / 5 + Math.PI / 2;
    const rx = cx + Math.cos(angle) * 7.5;
    const ry = cy + Math.sin(angle) * 4.5;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(rx, ry);
    ctx.stroke();

    // Metallic caster cap
    ctx.fillStyle = isExecutive ? '#fef08a' : '#cbd5e1';
    ctx.fillRect(rx - 0.5, ry - 0.5, 1, 1);
    ctx.fillStyle = '#090a0f';
    ctx.fillRect(rx - 1, ry, 2, 2);
  }

  // 2. PNEUMATIC GAS LIFT CYLINDER (2-tone chrome)
  ctx.fillStyle = '#475569';
  ctx.fillRect(cx - 1, cy - 4, 2, 4);
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(cx - 1, cy - 4, 1, 4); // chrome specular line

  // 3. ERGONOMIC CONTOURED SEAT PAN (Volumetric Cushion)
  const seatW = 14;
  const seatH = 10;
  const seatX = cx - seatW / 2;
  const seatY = cy - 8;

  // Bottom shadow & front thickness bevel
  ctx.fillStyle = mat.front;
  ctx.fillRect(seatX, seatY + seatH - 2, seatW, 2);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
  ctx.fillRect(seatX, seatY + seatH - 1, seatW, 1);

  // Main Seat Cushion Body (Darker base tone)
  ctx.fillStyle = mat.cushion || mat.front;
  ctx.beginPath();
  ctx.roundRect(seatX, seatY, seatW, seatH - 2, 2.5);
  ctx.fill();

  // Illuminated Upper Cushion Plane (Lighter tone for 2-tone depth split)
  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(seatX + 1, seatY + 1, seatW - 2, seatH - 4, 2);
  ctx.fill();

  // Top-left cushion highlight edge
  ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
  ctx.fillRect(seatX + 2, seatY + 1, seatW - 4, 1);

  // 4. METALLIC & PADDED ARMRESTS (Left & Right)
  // Left armrest
  ctx.fillStyle = '#334155';
  ctx.fillRect(seatX - 2, seatY + 1, 2, 5);
  ctx.fillStyle = '#64748b';
  ctx.fillRect(seatX - 2, seatY + 1, 1, 5); // support highlight
  ctx.fillStyle = mat.side;
  ctx.fillRect(seatX - 3, seatY, 3, 2);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
  ctx.fillRect(seatX - 3, seatY, 3, 1);

  // Right armrest
  ctx.fillStyle = '#334155';
  ctx.fillRect(seatX + seatW, seatY + 1, 2, 5);
  ctx.fillStyle = '#64748b';
  ctx.fillRect(seatX + seatW + 1, seatY + 1, 1, 5);
  ctx.fillStyle = mat.side;
  ctx.fillRect(seatX + seatW, seatY, 3, 2);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
  ctx.fillRect(seatX + seatW, seatY, 3, 1);

  // 5. ERGONOMIC HIGH-BACK CURVED BACKREST WITH LUMBAR SUPPORT
  if (facing === 'down') {
    const backW = 12;
    const backH = 8;
    const backX = cx - backW / 2;
    const backY = seatY - 5;

    // Backrest shell shadow
    ctx.fillStyle = mat.side;
    ctx.beginPath();
    ctx.roundRect(backX, backY, backW, backH, 3);
    ctx.fill();

    // Inner backrest fabric/mesh cushion (2-tone split)
    ctx.fillStyle = mat.top;
    ctx.beginPath();
    ctx.roundRect(backX + 1.5, backY + 1, backW - 3, backH - 2, 2);
    ctx.fill();

    // Top-Rim Specular Edge Highlight (Crucial for curved crown perception)
    ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.fillRect(backX + 2, backY + 0.5, backW - 4, 1);

    // Lumbar spine support & headrest bolster
    ctx.fillStyle = isExecutive ? '#ca8a04' : '#38bdf8';
    ctx.fillRect(cx - 2.5, backY + 3, 5, 2);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.fillRect(cx - 2, backY + 3, 4, 1);
  } else if (facing === 'up') {
    const backW = 14;
    const backH = 10;
    const backX = cx - backW / 2;
    const backY = seatY - 2;

    // Spine and rib support frame
    ctx.fillStyle = mat.front;
    ctx.beginPath();
    ctx.roundRect(backX, backY, backW, backH, 3);
    ctx.fill();

    // Top crown bevel & lumbar band
    ctx.fillStyle = mat.bevel;
    ctx.fillRect(backX + 1, backY, backW - 2, 1.5);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.28)';
    ctx.fillRect(backX + 2, backY, backW - 4, 1);

    // Y-spine spine support
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(cx - 1, backY + 2, 2, backH - 2);
  } else if (facing === 'left') {
    // Side profile curve
    ctx.fillStyle = mat.front;
    ctx.fillRect(seatX + seatW - 3, seatY - 6, 3, 10);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.fillRect(seatX + seatW - 3, seatY - 6, 3, 1); // top rim
  } else {
    ctx.fillStyle = mat.front;
    ctx.fillRect(seatX, seatY - 6, 3, 10);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.fillRect(seatX, seatY - 6, 3, 1);
  }

  ctx.restore();
}

// ==========================================
// 3. 42U DATA CENTER SERVER RACKS (3D REBUILD)
// ==========================================

export function drawServerRack3D(ctx: CanvasRenderingContext2D, f: Furniture2D | InteractivePOI, now: number) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // 1. Heavy Base Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
  ctx.fillRect(-2, height - 4, width + 4, 10);

  // 2. Heavy 42U Steel Outer Frame & Cabinet Sides (Top-Left Highlight)
  ctx.fillStyle = '#06070a';
  ctx.fillRect(0, 0, width, height);

  // Top roof and left frame bevel highlight
  ctx.fillStyle = '#1e222d';
  ctx.fillRect(1, 1, width - 2, 5);
  ctx.fillStyle = '#475569';
  ctx.fillRect(1, 1, width - 2, 1); // top specular rim
  ctx.fillRect(1, 1, 1, height - 2); // left edge specular

  // Top Exhaust Fan Grilles
  ctx.fillStyle = '#0a0d14';
  ctx.beginPath();
  ctx.arc(width * 0.3, 3.5, 2, 0, Math.PI * 2);
  ctx.arc(width * 0.7, 3.5, 2, 0, Math.PI * 2);
  ctx.fill();

  // 3. Recessed 19" Rack Mounting Rails
  const railX = 3;
  const railY = 6;
  const railW = width - 6;
  const railH = height - 10;

  ctx.fillStyle = '#07090e';
  ctx.fillRect(railX, railY, railW, railH);

  // 4. Server Blade Chassis Tiers (Individual 1U / 2U Unit Slots)
  const tierHeight = 5;
  const numTiers = Math.floor(railH / tierHeight);

  for (let i = 0; i < numTiers; i++) {
    const ty = railY + i * tierHeight;

    // Dark seam separator between blade units
    ctx.fillStyle = '#020408';
    ctx.fillRect(railX, ty, railW, 1);

    // Blade chassis metallic faceplate (alternating 2-tone brushed finishes)
    ctx.fillStyle = i % 2 === 0 ? '#131822' : '#1c2333';
    ctx.fillRect(railX + 1, ty + 1, railW - 2, tierHeight - 1);

    // Blade top bevel highlight
    ctx.fillStyle = '#2d3748';
    ctx.fillRect(railX + 1, ty + 1, railW - 2, 0.8);

    // Left rack mounting screw / ear handle
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(railX + 1, ty + 2, 1, 1);
    ctx.fillRect(railX + railW - 2, ty + 2, 1, 1);

    // Recessed hard drive / SSD caddy bay slots
    ctx.fillStyle = '#070a0f';
    ctx.fillRect(railX + 3, ty + 1.5, railW - 14, tierHeight - 2.5);

    // Multi-color blinking status LED matrix (Green, Amber, Red, Cyan Mix)
    const ledSeed = (i * 137 + now / 160);
    const led1 = Math.sin(ledSeed) > 0.1;
    const led2 = Math.cos(ledSeed * 1.4) > -0.2;
    const led3 = Math.sin(ledSeed * 2.1) > 0.4;
    const isAlert = i === 2 && Math.sin(now / 120) > 0.3;

    // Primary activity LED (Green/Cyan/Red)
    ctx.fillStyle = isAlert ? '#ef4444' : led1 ? '#10b981' : '#047857';
    ctx.fillRect(railX + railW - 9, ty + 1.5, 1.5, 1.5);

    // Network throughput LED (Amber / Cyan)
    ctx.fillStyle = led2 ? '#f59e0b' : '#b45309';
    ctx.fillRect(railX + railW - 6, ty + 1.5, 1.5, 1.5);

    // Fiber channel LED (Cyan / Blue)
    ctx.fillStyle = led3 ? '#06b6d4' : '#0284c7';
    ctx.fillRect(railX + railW - 3, ty + 1.5, 1.5, 1.5);

    // Cable patch loops
    if (i % 3 === 0) {
      ctx.strokeStyle = i % 6 === 0 ? '#38bdf8' : '#eab308';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(railX + 7, ty + 3, 2, 0, Math.PI);
      ctx.stroke();
    }
  }

  // 5. Perforated Mesh Glass Door Frame with Specular Reflection
  ctx.strokeStyle = '#38bdf835';
  ctx.lineWidth = 1;
  ctx.strokeRect(railX, railY, railW, railH);

  // Diagonal glass glare sheen
  ctx.fillStyle = 'rgba(56, 189, 248, 0.08)';
  ctx.beginPath();
  ctx.moveTo(railX + 2, railY);
  ctx.lineTo(railX + 10, railY);
  ctx.lineTo(railX + 2, railY + railH);
  ctx.fill();

  // Bottom kickplate with bevel
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(1, height - 4, width - 2, 4);
  ctx.fillStyle = '#334155';
  ctx.fillRect(1, height - 4, width - 2, 1);

  ctx.restore();
}

// ==========================================
// 4. CONFERENCE BOARDROOM TABLE (3D REBUILD)
// ==========================================

export function drawConferenceTable(ctx: CanvasRenderingContext2D, f: Furniture2D, now: number) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const mat = PALETTES.wood.dark_mahogany;

  // 1. Table Ambient Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.beginPath();
  ctx.roundRect(-4, height - 6, width + 8, 14, 6);
  ctx.fill();

  // 2. Heavy Dual Pedestal Base Columns (2-tone metallic base)
  ctx.fillStyle = '#0a0d14';
  ctx.fillRect(width * 0.22 - 6, 8, 12, height - 10);
  ctx.fillRect(width * 0.78 - 6, 12, 12, height - 10);
  ctx.fillStyle = '#475569';
  ctx.fillRect(width * 0.22 - 6, 8, 2, height - 10);
  ctx.fillRect(width * 0.78 - 6, 8, 2, height - 10);

  // 3. Table Thickness & Front Beveled Edge (3D depth)
  const topThickness = 6;
  ctx.fillStyle = mat.front;
  ctx.beginPath();
  ctx.roundRect(0, height - topThickness, width, topThickness, 4);
  ctx.fill();
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(0, height - 1, width, 1);

  // 4. Main Top Tabletop Surface (2-tone rich mahogany)
  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(1, 1, width - 2, height - topThickness, 4);
  ctx.fill();

  // Lighter-toned illuminated top plane
  ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
  ctx.beginPath();
  ctx.roundRect(3, 3, width - 6, height - topThickness - 5, 3);
  ctx.fill();

  // Top-left specular highlight edge
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(2, height - topThickness);
  ctx.lineTo(2, 2);
  ctx.lineTo(width - 2, 2);
  ctx.stroke();

  // Fine woodgrain inlay line
  ctx.strokeStyle = mat.bevel;
  ctx.lineWidth = 1;
  ctx.strokeRect(4, 4, width - 8, height - topThickness - 7);

  // 5. Central Brushed Aluminum Power / Cable Well
  const wellW = width * 0.45;
  const wellH = 10;
  const wellX = (width - wellW) / 2;
  const wellY = (height - topThickness - wellH) / 2;

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(wellX, wellY, wellW, wellH);
  ctx.fillStyle = '#475569';
  ctx.fillRect(wellX + 1, wellY + 1, wellW - 2, wellH - 2);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(wellX + 1, wellY + 1, wellW - 2, 1); // brushed highlight

  // 6. Central Polycom Triangular Conference Phone
  const polyX = width / 2;
  const polyY = wellY + wellH / 2;

  ctx.fillStyle = '#090a0f';
  ctx.beginPath();
  ctx.arc(polyX, polyY, 6, 0, Math.PI * 2);
  ctx.fill();

  const micColor = Math.sin(now / 400) > 0 ? '#38bdf8' : '#0284c7';
  ctx.strokeStyle = micColor;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(polyX, polyY, 4, 0, Math.PI * 2);
  ctx.stroke();

  // 7. Attendees' Open Laptops & Glowing Screens
  const attendeeXOffsets = [width * 0.18, width * 0.35, width * 0.65, width * 0.82];
  attendeeXOffsets.forEach((ax, idx) => {
    // Laptop base
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(ax - 5, wellY - 4, 10, 2);
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(ax - 5, wellY - 4, 10, 0.8);
    // Screen bezel
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(ax - 5, wellY - 9, 10, 5);
    // Glowing screen panel
    const screenGlow = idx % 2 === 0 ? '#38bdf8' : '#a855f7';
    ctx.fillStyle = screenGlow;
    ctx.fillRect(ax - 4, wellY - 8, 8, 3);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
    ctx.fillRect(ax - 4, wellY - 8, 8, 1);

    // Water tumbler with light reflection
    ctx.fillStyle = 'rgba(56, 189, 248, 0.4)';
    ctx.beginPath();
    ctx.arc(ax + 8, wellY + wellH + 2, 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#e0f2fe';
    ctx.lineWidth = 0.8;
    ctx.stroke();
  });

  ctx.restore();
}

// ==========================================
// 5. BREAKROOM & CAFÉ APPLIANCES (3D REBUILD)
// ==========================================

export function drawEspressoMachine(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number,
  isSelected: boolean
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Base Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.fillRect(-2, height - 3, width + 4, 8);

  // Heavy Stainless Steel Body (2-tone brushed metal)
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(0, 0, width, height);

  // Top cup warmer rack with top-left specular highlight
  ctx.fillStyle = '#64748b';
  ctx.fillRect(1, 1, width - 2, 4);
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(1, 1, width - 2, 1); // top rim
  ctx.fillRect(1, 1, 1, height - 2); // left rim

  // Ceramic espresso cups on top rack
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(3, 0, 3, 2);
  ctx.fillRect(8, 0, 3, 2);
  ctx.fillRect(13, 0, 3, 2);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(3, 1, 3, 1);
  ctx.fillRect(8, 1, 3, 1);
  ctx.fillRect(13, 1, 3, 1);

  // Front Control Panel & Pressure Gauges
  ctx.fillStyle = '#334155';
  ctx.fillRect(2, 5, width - 4, height - 10);
  ctx.fillStyle = '#475569';
  ctx.fillRect(2, 5, width - 4, 1);

  // Brass Barometer Pressure Gauges
  ctx.fillStyle = '#eab308';
  ctx.beginPath();
  ctx.arc(6, 8, 2, 0, Math.PI * 2);
  ctx.arc(width - 6, 8, 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fef08a';
  ctx.fillRect(5.5, 7.5, 1, 1); // specular dot

  // Portafilter Group Heads (2-tone chrome)
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(width * 0.3 - 2, 10, 4, 3);
  ctx.fillRect(width * 0.7 - 2, 10, 4, 3);
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(width * 0.3 - 1, 13, 2, 4);
  ctx.fillRect(width * 0.7 - 1, 13, 2, 4);
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(width * 0.3 - 1, 13, 1, 4);
  ctx.fillRect(width * 0.7 - 1, 13, 1, 4);

  // Stainless Drip Tray Grate
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(1, height - 5, width - 2, 5);
  ctx.fillStyle = '#64748b';
  for (let gx = 3; gx < width - 3; gx += 3) {
    ctx.fillRect(gx, height - 4, 1, 3);
  }

  // Steam animation
  if (isSelected || Math.sin(now / 300) > 0.3) {
    const steamY = (now / 120) % 8;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
    ctx.fillRect(width * 0.3, 7 - steamY, 1.5, 2.5);
    ctx.fillRect(width * 0.7, 6 - steamY, 1.5, 2.5);
  }

  ctx.restore();
}

export function drawArcadeCabinet(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number,
  _isSelected: boolean
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Base Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
  ctx.fillRect(-2, height - 4, width + 4, 10);

  // Heavy Cabinet Chassis (2-tone with Neon Magenta Side Art)
  ctx.fillStyle = '#090d16';
  ctx.fillRect(0, 0, width, height);

  // Top-left highlight rim on arcade cabinet
  ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
  ctx.fillRect(1, 1, width - 2, 1);
  ctx.fillRect(1, 1, 1, height - 2);

  ctx.strokeStyle = '#ec4899';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);

  // Illuminated Marquee Banner
  ctx.fillStyle = '#d946ef';
  ctx.fillRect(2, 2, width - 4, 7);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(2, 2, width - 4, 1); // marquee top light
  ctx.font = 'bold 5px monospace';
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.fillText('NEXUS', width / 2, 7);

  // CRT Screen Bezel & Curved Monitor
  const crtX = 3;
  const crtY = 10;
  const crtW = width - 6;
  const crtH = 12;

  ctx.fillStyle = '#020617';
  ctx.fillRect(crtX, crtY, crtW, crtH);

  // Animated space shooter starfield
  const starOffset = (now / 80) % crtH;
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(crtX + 2, crtY + ((starOffset + 3) % crtH), 1, 1);
  ctx.fillRect(crtX + 8, crtY + ((starOffset + 7) % crtH), 1, 1);

  const shipX = crtX + crtW / 2 + Math.sin(now / 350) * 3;
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(shipX - 2, crtY + crtH - 3, 4, 2);
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(shipX - 1, crtY + crtH - 4, 2, 1);

  // CRT Scanlines & Screen Glow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
  for (let sy = crtY; sy < crtY + crtH; sy += 2) {
    ctx.fillRect(crtX, sy, crtW, 1);
  }
  ctx.fillStyle = 'rgba(56, 189, 248, 0.12)';
  ctx.fillRect(crtX, crtY, crtW, crtH);

  // Control Deck (2-tone bevel)
  const deckY = crtY + crtH;
  ctx.fillStyle = '#1e1b4b';
  ctx.fillRect(2, deckY, width - 4, 6);
  ctx.fillStyle = '#312e81';
  ctx.fillRect(2, deckY, width - 4, 1); // deck top highlight

  // Joystick (Red ball with stem)
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.arc(6, deckY + 2, 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fca5a5';
  ctx.fillRect(5.5, deckY + 1, 1, 1);
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(5.5, deckY + 3, 1, 2);

  // Action Buttons
  ctx.fillStyle = '#06b6d4';
  ctx.fillRect(10, deckY + 1, 2, 2);
  ctx.fillRect(13, deckY + 1, 2, 2);
  ctx.fillStyle = '#eab308';
  ctx.fillRect(10, deckY + 3.5, 2, 2);
  ctx.fillRect(13, deckY + 3.5, 2, 2);

  // Coin door with illuminated coin return slots
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(4, deckY + 7, width - 8, height - (deckY + 9));
  ctx.fillStyle = '#f97316';
  ctx.fillRect(6, deckY + 9, 2, 4);
  ctx.fillRect(width - 8, deckY + 9, 2, 4);

  ctx.restore();
}

export function drawVendingMachine(ctx: CanvasRenderingContext2D, poi: InteractivePOI, now: number) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Base Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
  ctx.fillRect(-2, height - 3, width + 4, 8);

  // Heavy Outer Cabinet (2-tone Deep Navy)
  ctx.fillStyle = '#111827';
  ctx.fillRect(0, 0, width, height);

  // Top-left specular highlight edge
  ctx.fillStyle = 'rgba(255, 255, 255, 0.22)';
  ctx.fillRect(1, 1, width - 2, 1);
  ctx.fillRect(1, 1, 1, height - 2);

  // Illuminated Glass Window (Recessed)
  const winX = 2;
  const winY = 4;
  const winW = width - 14;
  const winH = height - 14;

  ctx.fillStyle = '#030712';
  ctx.fillRect(winX, winY, winW, winH);

  // Stocked Beverage Shelves
  const numShelves = 3;
  const shelfH = Math.floor(winH / numShelves);

  for (let s = 0; s < numShelves; s++) {
    const sy = winY + s * shelfH;
    ctx.fillStyle = '#475569';
    ctx.fillRect(winX + 1, sy + shelfH - 1, winW - 2, 1);
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(winX + 1, sy + shelfH - 1, winW - 2, 0.8);

    // Multi-color soda cans with label stripes
    const colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#ec4899'];
    for (let ix = winX + 2; ix < winX + winW - 4; ix += 4) {
      const c = colors[(s * 3 + Math.floor(ix / 4)) % colors.length] || '#ef4444';
      // Can body
      ctx.fillStyle = c;
      ctx.fillRect(ix, sy + 3, 3, shelfH - 4);
      // Can top tab & specular line
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(ix, sy + 3, 3, 1);
    }
  }

  // Specular Glass Reflection
  ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
  ctx.beginPath();
  ctx.moveTo(winX + 2, winY);
  ctx.lineTo(winX + 8, winY);
  ctx.lineTo(winX + 2, winY + winH);
  ctx.fill();

  // Right Side Control Column & LED Display
  const colX = width - 11;
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(colX, 4, 9, winH);
  ctx.fillStyle = '#334155';
  ctx.fillRect(colX, 4, 1, winH); // left seam

  // Green LED Price Readout
  ctx.fillStyle = '#022c22';
  ctx.fillRect(colX + 1, 6, 7, 3);
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(colX + 2, 7, 5, 1);

  // Keypad & Coin Slot
  ctx.fillStyle = '#94a3b8';
  for (let ky = 11; ky < 19; ky += 3) {
    ctx.fillRect(colX + 1.5, ky, 2, 2);
    ctx.fillRect(colX + 4.5, ky, 2, 2);
  }

  // Change Return / Dispense flap
  ctx.fillStyle = Math.sin(now / 300) > 0 ? '#22c55e' : '#15803d';
  ctx.fillRect(colX + 2, 21, 5, 2);

  // Bottom Dispenser Chute
  ctx.fillStyle = '#020617';
  ctx.fillRect(2, height - 8, width - 4, 6);
  ctx.fillStyle = '#334155';
  ctx.fillRect(3, height - 7, width - 6, 4);

  ctx.restore();
}

export function drawWaterCooler(ctx: CanvasRenderingContext2D, poi: InteractivePOI, now: number) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.beginPath();
  ctx.ellipse(width / 2, height - 1, width / 2, 3, 0, 0, Math.PI * 2);
  ctx.fill();

  // Dispenser Body (2-tone white & slate)
  const bodyY = 12;
  const bodyH = height - bodyY;
  ctx.fillStyle = '#f8fafc';
  ctx.beginPath();
  ctx.roundRect(2, bodyY, width - 4, bodyH, 2);
  ctx.fill();

  // Top-left highlight on dispenser
  ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
  ctx.fillRect(2, bodyY, 1, bodyH);
  ctx.fillRect(2, bodyY, width - 4, 1);

  // Right side shadow tone
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(width - 4, bodyY, 2, bodyH);

  // Recessed Cup Dispenser & Taps
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(4, bodyY + 4, width - 8, 8);
  ctx.fillStyle = '#ef4444'; // Hot tap
  ctx.fillRect(5, bodyY + 5, 2, 3);
  ctx.fillStyle = '#38bdf8'; // Cold tap
  ctx.fillRect(width - 7, bodyY + 5, 2, 3);

  // Translucent Blue Water Bottle (2-tone with Water Wave)
  ctx.fillStyle = 'rgba(6, 182, 212, 0.55)';
  ctx.beginPath();
  ctx.roundRect(3, 2, width - 6, 10, 3);
  ctx.fill();

  // Water bottle specular shine
  ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
  ctx.fillRect(4, 3, 2, 8);

  // Animated air bubbles in bottle
  const bubbleY = (now / 200) % 8;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(width / 2, 10 - bubbleY, 1, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

// ==========================================
// 6. LOUNGE, TABLES & SEATING (3D REBUILD)
// ==========================================

export function drawPlushSofa(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const mat = PALETTES.fabric.fabric_amber;

  // 1. Sofa Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.beginPath();
  ctx.roundRect(-2, height - 4, width + 4, 10, 4);
  ctx.fill();

  // 2. Walnut Tapered Wooden Feet
  ctx.fillStyle = '#3e2723';
  ctx.fillRect(3, height - 3, 2, 4);
  ctx.fillRect(width - 5, height - 3, 2, 4);
  ctx.fillStyle = '#6d4c41';
  ctx.fillRect(3, height - 3, 1, 4);

  // 3. Volumetric Backrest with Tufting & Top-Left Specular Edge
  const backH = 8;
  ctx.fillStyle = mat.side;
  ctx.beginPath();
  ctx.roundRect(0, 0, width, backH, 3);
  ctx.fill();

  // Backrest top plane (2-tone split)
  ctx.fillStyle = mat.top;
  ctx.fillRect(2, 1, width - 4, backH - 2);

  // Top-left highlight edge on backrest
  ctx.fillStyle = 'rgba(255, 255, 255, 0.28)';
  ctx.fillRect(1, 1, width - 2, 1);
  ctx.fillRect(1, 1, 1, backH - 1);

  // Diamond Tufting Buttons
  ctx.fillStyle = mat.bevel;
  for (let bx = 6; bx < width - 6; bx += 8) {
    ctx.fillRect(bx, 3, 2, 2);
    ctx.fillStyle = '#451a03';
    ctx.fillRect(bx + 1, 4, 1, 1);
    ctx.fillStyle = mat.bevel;
  }

  // 4. Volumetric Deep Cushion Seat Pan
  const seatY = backH - 2;
  const seatH = height - seatY - 2;

  // Front face drop
  ctx.fillStyle = mat.front;
  ctx.fillRect(0, seatY + seatH - 3, width, 3);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
  ctx.fillRect(0, seatY + seatH - 1, width, 1);

  // Cushion top surface (2-tone)
  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(0, seatY, width, seatH - 3, 2);
  ctx.fill();

  // Cushion top highlight
  ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
  ctx.fillRect(2, seatY + 1, width - 4, 1);

  // 5. Rounded Volumetric Armrests (Left & Right)
  ctx.fillStyle = mat.cushion;
  ctx.beginPath();
  ctx.roundRect(0, seatY - 1, 5, seatH, 2.5);
  ctx.roundRect(width - 5, seatY - 1, 5, seatH, 2.5);
  ctx.fill();

  // Armrest top-left specular highlights
  ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
  ctx.fillRect(1, seatY, 3, 1);
  ctx.fillRect(width - 4, seatY, 3, 1);

  ctx.restore();
}

export function drawCoffeeTable(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
  ctx.beginPath();
  ctx.roundRect(-2, height - 4, width + 4, 8, 3);
  ctx.fill();

  // Brass Hairpin Legs (2-tone metallic finish)
  ctx.strokeStyle = '#ca8a04';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(3, 4);
  ctx.lineTo(3, height);
  ctx.moveTo(width - 3, 4);
  ctx.lineTo(width - 3, height);
  ctx.stroke();
  ctx.strokeStyle = '#fef08a';
  ctx.lineWidth = 0.8;
  ctx.beginPath();
  ctx.moveTo(3, 4);
  ctx.lineTo(3, height - 2);
  ctx.stroke();

  // Smoked Glass Tabletop Surface (2-tone with Top-Left Highlight)
  ctx.fillStyle = 'rgba(30, 41, 59, 0.88)';
  ctx.beginPath();
  ctx.roundRect(0, 0, width, height - 4, 3);
  ctx.fill();

  // Top-left highlight rim
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 5);

  // Magazine & Remote with specular glint
  ctx.fillStyle = '#f43f5e';
  ctx.fillRect(width * 0.3, 4, 8, 6);
  ctx.fillStyle = '#fda4af';
  ctx.fillRect(width * 0.3, 4, 8, 1);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(width * 0.65, 5, 4, 8);
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(width * 0.65 + 1, 6, 2, 1);

  ctx.restore();
}

export function drawRoundCafeTable(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const cx = width / 2;
  const cy = height / 2;
  const rx = width / 2;
  const ry = height / 2 - 2;

  // 1. Table Ambient Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.beginPath();
  ctx.ellipse(cx, cy + 8, rx + 4, ry * 0.7, 0, 0, Math.PI * 2);
  ctx.fill();

  // 2. Heavy Cast-Iron / Steel Center Pedestal
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(cx - 3, cy, 6, height - cy);
  ctx.fillStyle = '#475569';
  ctx.fillRect(cx - 3, cy, 2, height - cy); // highlight

  // Pedestal Base Plate
  ctx.fillStyle = '#1e293b';
  ctx.beginPath();
  ctx.ellipse(cx, height - 2, 12, 4, 0, 0, Math.PI * 2);
  ctx.fill();

  // 3. Wooden Tabletop Slab Front Thickness (3D Edge)
  ctx.fillStyle = '#261b12';
  ctx.beginPath();
  ctx.ellipse(cx, cy + 3, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();

  // 4. Main Top Tabletop Surface (Rich Walnut with Top-Left Highlight)
  ctx.fillStyle = '#4a3525';
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();

  // Top Surface Specular Highlight Arc (Top-Left quadrant)
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx - 1, ry - 1, 0, Math.PI, Math.PI * 1.75);
  ctx.stroke();

  // Wood Grain Ring Inlay
  ctx.strokeStyle = '#38281c';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx * 0.65, ry * 0.65, 0, 0, Math.PI * 2);
  ctx.stroke();

  // 5. Props on Table (Coffee Cups & Pastry Plate)
  ctx.fillStyle = '#f8fafc';
  ctx.beginPath();
  ctx.ellipse(cx, cy, 7, 5, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#b45309';
  ctx.beginPath();
  ctx.arc(cx - 1, cy, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#ec4899';
  ctx.fillRect(cx - 2, cy - 1, 3, 2);

  // Coffee Mug 1 (Left)
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(cx - 14, cy - 4, 4, 5);
  ctx.fillStyle = '#bae6fd';
  ctx.fillRect(cx - 14, cy - 4, 1, 5);
  ctx.fillStyle = '#451a03';
  ctx.fillRect(cx - 13, cy - 4, 2, 1);

  // Coffee Mug 2 (Right)
  ctx.fillStyle = '#f59e0b';
  ctx.fillRect(cx + 10, cy - 3, 4, 5);
  ctx.fillStyle = '#fef08a';
  ctx.fillRect(cx + 10, cy - 3, 1, 5);
  ctx.fillStyle = '#451a03';
  ctx.fillRect(cx + 11, cy - 3, 2, 1);

  ctx.restore();
}

export function drawZenBench(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.fillRect(-2, height - 4, width + 4, 8);

  // Cast Iron Armrests & Frame
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(0, 2, 3, height - 2);
  ctx.fillRect(width - 3, 2, 3, height - 2);
  ctx.fillStyle = '#475569';
  ctx.fillRect(0, 2, 1, height - 2); // left highlight

  // Teak Wood Slats with 2-Tone Shading
  const slatH = 3;
  for (let sy = 2; sy < height - 2; sy += 5) {
    ctx.fillStyle = '#78350f';
    ctx.fillRect(3, sy, width - 6, slatH);
    ctx.fillStyle = '#b45309';
    ctx.fillRect(3, sy, width - 6, 1);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
    ctx.fillRect(3, sy, 1, slatH); // left highlight
  }

  ctx.restore();
}

// ==========================================
// 7. ZEN PATIO & FOUNTAIN (3D REBUILD)
// ==========================================

export function drawZenFountain(ctx: CanvasRenderingContext2D, poi: InteractivePOI, now: number) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;
  const cx = width / 2;
  const cy = height / 2;
  const outerR = width / 2;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.beginPath();
  ctx.ellipse(cx, cy + 6, outerR + 2, outerR * 0.6, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#1e293b';
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Top-left stone rim highlight
  ctx.strokeStyle = '#f8fafc';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, outerR - 1, Math.PI * 0.8, Math.PI * 1.8);
  ctx.stroke();

  ctx.fillStyle = '#0284c7';
  ctx.beginPath();
  ctx.arc(cx, cy, outerR - 4, 0, Math.PI * 2);
  ctx.fill();

  const maxR = outerR - 6;
  const rip1 = (now / 40) % maxR;
  const rip2 = ((now / 40) + maxR / 2) % maxR;

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(cx, cy, rip1, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
  ctx.beginPath();
  ctx.arc(cx, cy, rip2, 0, Math.PI * 2);
  ctx.stroke();

  const innerR = outerR * 0.45;
  ctx.fillStyle = '#0f172a';
  ctx.beginPath();
  ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = '#ca8a04';
  ctx.beginPath();
  ctx.arc(cx, cy, 4, 0, Math.PI * 2);
  ctx.fill();

  const sprayH = (Math.sin(now / 150) + 1) * 2;
  ctx.fillStyle = '#e0f2fe';
  ctx.beginPath();
  ctx.arc(cx, cy - 2 - sprayH, 2, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

// ==========================================
// 8. POTTED PLANTS, WHITEBOARD & BOOKSHELF (3D REBUILD)
// ==========================================

export function drawPottedPlant(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const cx = width / 2;

  // Contact Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.beginPath();
  ctx.ellipse(cx, height - 2, width / 2, 4, 0, 0, Math.PI * 2);
  ctx.fill();

  // Ceramic Terracotta Pot (2-tone shading with left highlight & right shadow)
  const potW = width * 0.65;
  const potH = height * 0.45;
  const potX = cx - potW / 2;
  const potY = height - potH - 2;

  // Dark right base tone
  ctx.fillStyle = '#7c2d12';
  ctx.beginPath();
  ctx.roundRect(potX, potY, potW, potH, 2);
  ctx.fill();

  // Lighter front terracotta tone
  ctx.fillStyle = '#c2410c';
  ctx.fillRect(potX + 1, potY + 1, potW - 3, potH - 2);

  // Top-left pot highlight
  ctx.fillStyle = '#fb923c';
  ctx.fillRect(potX + 1, potY + 1, 2, potH - 2);

  // Pot Rim Collar with specular glint
  ctx.fillStyle = '#ea580c';
  ctx.fillRect(potX - 1, potY, potW + 2, 2);
  ctx.fillStyle = '#fdba74';
  ctx.fillRect(potX - 1, potY, 3, 1);

  // Dark Rich Soil & Moss
  ctx.fillStyle = '#1c1917';
  ctx.fillRect(potX + 1, potY + 1, potW - 2, 2);

  // Layered Pixel Foliage / Monstera Leaves (3-tone depth)
  // Deep background leaves
  ctx.fillStyle = '#14532d';
  ctx.beginPath();
  ctx.arc(cx - 4, potY - 4, 8, 0, Math.PI * 2);
  ctx.arc(cx + 5, potY - 3, 7, 0, Math.PI * 2);
  ctx.fill();

  // Midground vibrant leaves
  ctx.fillStyle = '#16a34a';
  ctx.beginPath();
  ctx.arc(cx, potY - 6, 7, 0, Math.PI * 2);
  ctx.fill();

  // Foreground top-left highlight leaves
  ctx.fillStyle = '#4ade80';
  ctx.beginPath();
  ctx.arc(cx - 2, potY - 7, 5, 0, Math.PI * 2);
  ctx.fill();

  // Specular leaf rim highlight
  ctx.fillStyle = '#bbf7d0';
  ctx.fillRect(cx - 3, potY - 9, 3, 1.5);

  ctx.restore();
}

export function drawWhiteboard(ctx: CanvasRenderingContext2D, poi: InteractivePOI) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Rolling Caster Stand Base
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.fillRect(-2, height - 3, width + 4, 6);

  ctx.fillStyle = '#334155';
  ctx.fillRect(4, height - 5, 4, 5);
  ctx.fillRect(width - 8, height - 5, 4, 5);
  ctx.fillStyle = '#64748b';
  ctx.fillRect(4, height - 5, 1, 5); // left stand highlight
  ctx.fillRect(width - 8, height - 5, 1, 5);

  // Aluminum Frame Board Body (2-tone bevel)
  ctx.fillStyle = '#475569';
  ctx.fillRect(0, 0, width, height - 5);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(0, 0, width, 1); // top rim
  ctx.fillRect(0, 0, 1, height - 5); // left rim

  // Porcelain Magnetic White Surface
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(2, 2, width - 4, height - 9);

  // Dry Erase Marker Tray at bottom
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(4, height - 7, width - 8, 2);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(4, height - 7, width - 8, 1);

  // Red, Blue & Black dry-erase markers
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(8, height - 8, 4, 1);
  ctx.fillStyle = '#3b82f6';
  ctx.fillRect(14, height - 8, 4, 1);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(20, height - 8, 4, 1);

  // Colorful Sprint Sticky Notes with mini drop shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.2)';
  ctx.fillRect(7, 5, 8, 7);
  ctx.fillRect(17, 5, 8, 7);
  ctx.fillRect(27, 5, 8, 7);

  ctx.fillStyle = '#fef08a';
  ctx.fillRect(6, 4, 8, 7);
  ctx.fillStyle = '#f43f5e';
  ctx.fillRect(16, 4, 8, 7);
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(26, 4, 8, 7);

  // Architecture Diagram Flow Nodes
  const startX = 40;
  const nodeW = 22;
  const nodeH = 9;

  ctx.fillStyle = '#1e293b';
  ctx.fillRect(startX, 4, nodeW, nodeH);
  ctx.fillStyle = '#334155';
  ctx.fillRect(startX, 4, nodeW, 1);

  ctx.fillStyle = '#10b981';
  ctx.fillRect(startX + 30, 4, nodeW, nodeH);
  ctx.fillStyle = '#34d399';
  ctx.fillRect(startX + 30, 4, nodeW, 1);

  ctx.fillStyle = '#8b5cf6';
  ctx.fillRect(startX + 60, 4, nodeW, nodeH);
  ctx.fillStyle = '#a78bfa';
  ctx.fillRect(startX + 60, 4, nodeW, 1);

  // Arrow lines connecting nodes
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(startX + nodeW, 8);
  ctx.lineTo(startX + 30, 8);
  ctx.moveTo(startX + 30 + nodeW, 8);
  ctx.lineTo(startX + 60, 8);
  ctx.stroke();

  ctx.restore();
}

export function drawBookshelf(ctx: CanvasRenderingContext2D, poi: InteractivePOI) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;
  const mat = PALETTES.wood.dark_mahogany;

  // Base Shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.fillRect(-2, height - 4, width + 4, 8);

  // Heavy Wood Outer Frame (2-tone bevel with Top-Left Highlight)
  ctx.fillStyle = mat.side;
  ctx.fillRect(0, 0, width, height);

  // Top-left highlight edge
  ctx.fillStyle = mat.bevel;
  ctx.fillRect(0, 0, width, 1);
  ctx.fillRect(0, 0, 1, height);

  // Dark Recessed Interior
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(2, 2, width - 4, height - 4);

  // Shelves & Colorful Book Spines
  const numShelves = 2;
  const shelfH = Math.floor((height - 4) / numShelves);

  for (let s = 0; s < numShelves; s++) {
    const sy = 2 + s * shelfH;
    // Wood shelf plank with highlight
    ctx.fillStyle = mat.front;
    ctx.fillRect(2, sy + shelfH - 2, width - 4, 2);
    ctx.fillStyle = mat.bevel;
    ctx.fillRect(2, sy + shelfH - 2, width - 4, 1);

    // Books with colorful spines
    const bookColors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#e2e8f0', '#d946ef'];
    let bx = 4;
    let bIdx = s * 4;
    while (bx < width - 6) {
      const bw = 2 + (bIdx % 3);
      ctx.fillStyle = bookColors[bIdx % bookColors.length] || '#ef4444';
      ctx.fillRect(bx, sy + 2, bw, shelfH - 4);
      // Gold foil title line on spine
      ctx.fillStyle = '#fef08a';
      ctx.fillRect(bx, sy + 4, bw, 1);
      // Spine highlight
      ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
      ctx.fillRect(bx, sy + 2, 1, shelfH - 4);
      bx += bw + 1;
      bIdx++;
    }
  }

  ctx.restore();
}

// ==========================================
// 9. ENVIRONMENTAL PROPS (3D REBUILD)
// ==========================================

export function drawEnvironmentalProp(
  ctx: CanvasRenderingContext2D,
  prop: EnvironmentalProp2D,
  now: number
) {
  ctx.save();
  ctx.translate(prop.x, prop.y);

  const { width, height, type } = prop;

  if (type === 'printer') {
    // Heavy Office Laser Copier
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fillRect(-2, height - 3, width + 4, 6);

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(1, 1, width - 2, 4);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(3, 8, width - 6, 6);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(4, 9, width - 8, 2);

    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(width - 7, 2, 5, 3);
    ctx.fillStyle = Math.sin(now / 200) > 0 ? '#22c55e' : '#15803d';
    ctx.fillRect(width - 7, 6, 2, 1);
  } else if (type === 'filing_cabinet') {
    // 3-Drawer Metal Filing Cabinet
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fillRect(-1, height - 2, width + 2, 5);

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#334155';
    ctx.fillRect(1, 1, width - 2, height - 2);

    const drawerH = Math.floor((height - 2) / 3);
    for (let d = 0; d < 3; d++) {
      const dy = 1 + d * drawerH;
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(2, dy + 1, width - 4, drawerH - 2);
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(width / 2 - 3, dy + Math.floor(drawerH / 2), 6, 1.5);
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(width / 2 - 2, dy + 2, 4, 1.5);
    }
  } else if (type === 'wall_clock') {
    // Wall Clock with moving hands
    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#f8fafc';
    ctx.beginPath();
    ctx.arc(width / 2, height / 2, width / 2 - 1.5, 0, Math.PI * 2);
    ctx.fill();

    const secAngle = (now / 1000) * (Math.PI * 2 / 60);
    const minAngle = (now / 60000) * (Math.PI * 2 / 60);

    ctx.strokeStyle = '#090a0f';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(width / 2, height / 2);
    ctx.lineTo(width / 2 + Math.sin(minAngle) * 4, height / 2 - Math.cos(minAngle) * 4);
    ctx.stroke();

    ctx.strokeStyle = '#ef4444';
    ctx.beginPath();
    ctx.moveTo(width / 2, height / 2);
    ctx.lineTo(width / 2 + Math.sin(secAngle) * 5, height / 2 - Math.cos(secAngle) * 5);
    ctx.stroke();
  } else if (type === 'fire_extinguisher') {
    // Industrial Red Extinguisher
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fillRect(1, height - 2, width - 2, 4);

    ctx.fillStyle = '#dc2626';
    ctx.beginPath();
    ctx.roundRect(2, 3, width - 4, height - 4, 2);
    ctx.fill();
    ctx.fillStyle = '#ef4444';
    ctx.fillRect(3, 3, 2, height - 5);

    ctx.fillStyle = '#090a0f';
    ctx.fillRect(width / 2 - 1, 0, 2, 3);
    ctx.fillStyle = '#eab308';
    ctx.fillRect(width / 2 + 1, 1, 2, 2);
  } else if (type === 'trash_bin' || type === 'recycle_bin') {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.beginPath();
    ctx.ellipse(width / 2, height - 1, width / 2, 2, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = type === 'recycle_bin' ? '#2563eb' : '#475569';
    ctx.fillRect(1, 1, width - 2, height - 2);
    ctx.fillStyle = type === 'recycle_bin' ? '#3b82f6' : '#64748b';
    ctx.fillRect(1, 1, 2, height - 2);
  } else if (type === 'poster' || type === 'banner') {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(2, 2, width - 4, height - 4);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(4, 4, width - 8, 3);
  } else if (type === 'bonsai') {
    // Japanese Bonsai in Ceramic Pot
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.beginPath();
    ctx.ellipse(width / 2, height - 2, width / 2, 3, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#1e293b';
    ctx.beginPath();
    ctx.roundRect(2, height - 8, width - 4, 6, 2);
    ctx.fill();

    // Gnarled wood trunk
    ctx.strokeStyle = '#78350f';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(width / 2, height - 8);
    ctx.lineTo(width / 2 - 3, height - 14);
    ctx.lineTo(width / 2 + 2, height - 18);
    ctx.stroke();

    // Cloud foliage pads
    ctx.fillStyle = '#15803d';
    ctx.beginPath();
    ctx.arc(width / 2 - 4, height - 14, 5, 0, Math.PI * 2);
    ctx.arc(width / 2 + 3, height - 18, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#4ade80';
    ctx.fillRect(width / 2 + 2, height - 20, 3, 2);
  } else if (type === 'exit_sign') {
    // Illuminated Green Exit Sign
    ctx.fillStyle = '#022c22';
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
    ctx.font = 'bold 6px monospace';
    ctx.fillStyle = '#34d399';
    ctx.textAlign = 'center';
    ctx.fillText('EXIT', width / 2, height - 3);
  } else if (type === 'floor_lamp') {
    // Modern Arc Floor Lamp
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.beginPath();
    ctx.ellipse(width / 2, height - 2, 5, 2, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#ca8a04';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(width / 2, height - 2);
    ctx.lineTo(width / 2, 8);
    ctx.lineTo(width / 2 + 4, 4);
    ctx.stroke();

    ctx.fillStyle = '#f59e0b';
    ctx.beginPath();
    ctx.roundRect(width / 2 + 2, 2, 6, 4, 1);
    ctx.fill();
  }

  ctx.restore();
}

export { PixelAssets } from './PixelAssets';

