import type { Desk2D, Direction, EnvironmentalProp2D, Furniture2D, InteractivePOI } from './types';

/**
 * 3/4 Isometric Projection & Multi-Planar Sprite Asset Library
 * 
 * High-craft dimensional sprite renderer for office furniture, compute clusters,
 * appliances, and architectural fixtures.
 * 
 * Every asset features:
 * 1. Illuminated Top Horizontal Plane (direct overhead light reception, material texture, bevel highlights)
 * 2. Front Facing Vertical Plane (thickness, recessed paneling, drawers, hardware, seams)
 * 3. Side Perspective Elevation (ambient occlusion, trim rails, depth shading)
 * 4. Ground Contact Occlusion & Directional Drop Shadows
 * 5. Dynamic Animated Elements (blinking blade LEDs, CRT games, steam vapor, water ripples, RGB lighting)
 */

// ============================================================================
// 1. MATERIAL PALETTES & COLOR SCIENCE
// ============================================================================

export const ISO_PALETTES = {
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
// 2. SHADOW HELPERS (MULTI-LAYERED AMBIENT OCCLUSION & DROP SHADOWS)
// ============================================================================

export function renderSpriteContactShadow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  blurRadius: number = 4
) {
  ctx.save();
  ctx.translate(x, y);

  // Layer 1: Tight deep contact occlusion directly underneath ground touching points
  ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
  ctx.beginPath();
  ctx.roundRect(-2, h - 4, w + 4, 8, blurRadius);
  ctx.fill();

  // Layer 2: Soft directional downward shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.28)';
  ctx.beginPath();
  ctx.roundRect(-4, h - 1, w + 8, 12, blurRadius + 2);
  ctx.fill();

  ctx.restore();
}

export function renderCircularContactShadow(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  rx: number,
  ry: number
) {
  ctx.save();
  ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
  ctx.beginPath();
  ctx.ellipse(cx, cy + 2, rx + 3, ry + 2, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// ============================================================================
// 3. WORKSTATION SPRITES (3/4 ISOMETRIC PERSPECTIVE)
// ============================================================================

export function renderIsometricDesk(ctx: CanvasRenderingContext2D, desk: Desk2D, now: number) {
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

  const mat = ISO_PALETTES.wood[woodTone] || ISO_PALETTES.wood.carbon;

  const topThickness = 5;
  const desktopH = height - 4;
  const legInset = 4;
  const hasPedestal = width >= 60;

  // 1. BACK MODESTY PANEL & KNEEWELL CAVITY (Deep recessed plane)
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(legInset + 2, 8, width - (legInset * 2 + 4), desktopH - 6);

  ctx.fillStyle = mat.front;
  ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), desktopH - 12);
  // Modesty drop shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
  ctx.fillRect(legInset + 4, 10, width - (legInset * 2 + 8), 3);

  // Cable management spine
  if (accessories.includes('cables')) {
    ctx.fillStyle = '#050608';
    ctx.fillRect(width / 2 - 6, 8, 12, desktopH - 8);
    // Colorful routing lines
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

  // 2. UNDER-DESK DRAWER PEDESTAL UNIT (Right side)
  if (hasPedestal) {
    const drawerW = 16;
    const drawerX = width - drawerW - legInset;
    const drawerY = 8;
    const drawerH = desktopH - 6;

    // Dark side return
    ctx.fillStyle = mat.side;
    ctx.fillRect(drawerX, drawerY, drawerW, drawerH);

    // Front face
    ctx.fillStyle = mat.front;
    ctx.fillRect(drawerX + 1, drawerY, drawerW - 1, drawerH);

    // 3 Drawers with handles and gaps
    const tierH = Math.floor(drawerH / 3);
    for (let i = 0; i < 3; i++) {
      const ty = drawerY + i * tierH;
      // Seam gap
      ctx.fillStyle = '#050608';
      ctx.fillRect(drawerX + 1, ty, drawerW - 1, 1);

      // Drawer panel
      ctx.fillStyle = mat.bevel;
      ctx.fillRect(drawerX + 2, ty + 1, drawerW - 3, tierH - 2);

      // Chrome handle with specular highlight
      ctx.fillStyle = '#94a3b8';
      ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 2);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 1);
    }
  }

  // 3. STEEL LEGS WITH FOOT LEVELERS
  const legW = 3;
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(legInset, 8, legW, desktopH + 2);
  ctx.fillStyle = '#475569';
  ctx.fillRect(legInset, 8, 1, desktopH + 2); // left leg highlight
  ctx.fillStyle = '#64748b';
  ctx.fillRect(legInset - 1, desktopH + 1, legW + 2, 2); // foot leveler

  if (!hasPedestal) {
    ctx.fillStyle = '#090a0f';
    ctx.fillRect(width - legInset - legW, 8, legW, desktopH + 2);
    ctx.fillStyle = '#475569';
    ctx.fillRect(width - legInset - legW, 8, 1, desktopH + 2);
    ctx.fillStyle = '#64748b';
    ctx.fillRect(width - legInset - legW - 1, desktopH + 1, legW + 2, 2);
  }

  // 4. UNDER-DESK PC TOWER / COMPUTE BLADE
  if (deskType === 'developer' || deskType === 'systems' || deskType === 'data') {
    const pcX = legInset + 3;
    const pcY = desktopH - 16;
    const pcW = 10;
    const pcH = 16;

    ctx.fillStyle = '#0f172a';
    ctx.fillRect(pcX, pcY, pcW, pcH);
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(pcX + 1, pcY + 1, pcW - 2, pcH - 2);

    // Front intake mesh
    ctx.fillStyle = '#020617';
    ctx.fillRect(pcX + 2, pcY + 4, pcW - 4, pcH - 6);

    // RGB Fan illumination
    const fanColor = Math.sin(now / 200) > 0 ? '#06b6d4' : '#0284c7';
    ctx.fillStyle = fanColor;
    ctx.fillRect(pcX + 3, pcY + 6, 4, 4);

    // Power LED & ports
    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(pcX + 3, pcY + 2, 2, 1);
    ctx.fillStyle = '#38bdf8';
    ctx.fillRect(pcX + 6, pcY + 2, 1, 1);
  }

  // 5. MAIN DESKTOP SLAB (MULTI-PLANAR 3D PERSPECTIVE)
  // Front vertical face thickness
  ctx.fillStyle = mat.front;
  ctx.fillRect(0, desktopH - topThickness, width, topThickness);
  // Bottom shadow rim
  ctx.fillStyle = mat.shadow;
  ctx.fillRect(0, desktopH - 1, width, 1);

  // Left & Right side elevation edge planes
  ctx.fillStyle = mat.side;
  ctx.fillRect(0, 0, 1, desktopH);
  ctx.fillRect(width - 1, 0, 1, desktopH);

  // Illuminated top horizontal plane
  ctx.fillStyle = mat.top;
  ctx.fillRect(1, 1, width - 2, desktopH - topThickness);

  // Subtle material grain
  ctx.strokeStyle = mat.grain;
  ctx.lineWidth = 1;
  for (let gx = 6; gx < width - 6; gx += 14) {
    ctx.beginPath();
    ctx.moveTo(gx, 2);
    ctx.lineTo(gx + 4, desktopH - topThickness - 1);
    ctx.stroke();
  }

  // Perimeter bevel highlight lines
  ctx.fillStyle = mat.bevel;
  ctx.fillRect(1, 1, width - 2, 1); // back bevel
  ctx.fillRect(1, desktopH - topThickness - 1, width - 2, 1); // front edge highlight
  ctx.fillRect(1, 1, 1, desktopH - topThickness); // left bevel
  ctx.fillRect(width - 2, 1, 1, desktopH - topThickness); // right bevel

  // 6. ERGONOMIC DESK MAT WITH STITCHED BORDER
  const matInsetX = Math.floor(width * 0.12);
  const matW = width - matInsetX * 2;
  const matH = desktopH - topThickness - 4;
  const matY = 3;

  ctx.fillStyle = '#090a0f';
  ctx.fillRect(matInsetX, matY, matW, matH);
  ctx.strokeStyle = deskType === 'manager' ? '#ca8a04' : '#38bdf840';
  ctx.lineWidth = 1;
  ctx.strokeRect(matInsetX + 0.5, matY + 0.5, matW - 1, matH - 1);

  // 7. MECHANICAL KEYBOARD & MOUSE
  const kbW = Math.min(22, matW - 14);
  const kbH = 8;
  const kbX = matInsetX + 4;
  const kbY = matY + matH - kbH - 2;

  // Keyboard chassis
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(kbX, kbY, kbW, kbH);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(kbX, kbY, kbW, kbH - 1);
  ctx.fillStyle = '#334155';
  ctx.fillRect(kbX + 1, kbY, kbW - 2, 1);

  // Keycap Matrix with RGB underglow
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

  // 8. MULTI-MONITOR DISPLAY RIG (Curved / Triple / Dual / Vertical)
  renderIsometricMonitors(ctx, width, monitorSetup, screenColor, deskType, now);

  // 9. WORKSTATION ACCESSORIES & LIGHTING
  renderWorkstationAccessories(ctx, width, desktopH, accessories, lampOn, deskType, now);

  ctx.restore();
}

/**
 * Renders high-fidelity monitor rigs with stands, bezel chassis, glowing displays, and reflections
 */
function renderIsometricMonitors(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  setup: string,
  screenColor: string,
  _deskType: string,
  now: number
) {
  const centerX = deskW / 2;
  const baseY = 3;

  // Mount clamp & pole
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

    // Curved stand
    ctx.fillStyle = '#475569';
    ctx.fillRect(centerX - 5, my + mh, 10, 2);
    ctx.fillRect(centerX - 1, my + mh - 3, 2, 3);

    // Bezel
    ctx.fillStyle = '#090a0f';
    ctx.beginPath();
    ctx.roundRect(mx, my, mw, mh, 2);
    ctx.fill();

    ctx.fillStyle = '#1e293b';
    ctx.fillRect(mx + 1, my + 1, mw - 2, mh - 2);

    // Active screen
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(mx + 2, my + 2, mw - 4, mh - 4);

    // UI elements
    ctx.fillStyle = '#ec4899';
    ctx.fillRect(mx + 4, my + 4, 8, 5);
    ctx.fillStyle = '#8b5cf6';
    ctx.fillRect(mx + 14, my + 4, 10, 3);
    ctx.fillStyle = '#06b6d4';
    ctx.fillRect(mx + 26, my + 4, 6, 6);

    // Glass glare
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

  // Screen panel
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

function renderWorkstationAccessories(
  ctx: CanvasRenderingContext2D,
  deskW: number,
  desktopH: number,
  accessories: string[],
  lampOn: boolean | undefined,
  deskType: string,
  now: number
) {
  // A. Gooseneck Lamp
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

  // B. Coffee Mug with Steam
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

  // C. Potted Succulent
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

  // D. Studio Headphones
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

  // E. Open Paper Notebook & Pen
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

  // F. Sticky Notes
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
// 4. ERGONOMIC 3D OFFICE CHAIR SPRITE
// ============================================================================

export function renderIsometricChair(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  facing: Direction,
  isExecutive: boolean
) {
  ctx.save();
  ctx.translate(x, y);

  const mat = isExecutive ? ISO_PALETTES.fabric.executive_leather : ISO_PALETTES.fabric.mesh_black;

  // 1. 5-Spoke Caster Wheelbase
  ctx.strokeStyle = isExecutive ? '#ca8a04' : '#64748b';
  ctx.lineWidth = 1.2;
  const cx = 10;
  const cy = 12;

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

  // 2. Gas Cylinder
  ctx.fillStyle = '#e2e8f0';
  ctx.fillRect(cx - 1, cy - 4, 2, 4);

  // 3. Seat Pan
  const seatW = 14;
  const seatH = 10;
  const seatX = cx - seatW / 2;
  const seatY = cy - 8;

  ctx.fillStyle = mat.front;
  ctx.fillRect(seatX, seatY + seatH - 2, seatW, 2);

  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(seatX, seatY, seatW, seatH - 2, 2);
  ctx.fill();

  ctx.fillStyle = mat.bevel;
  ctx.fillRect(seatX + 2, seatY + 1, seatW - 4, 1);

  // 4. Armrests
  ctx.fillStyle = '#334155';
  ctx.fillRect(seatX - 2, seatY + 1, 2, 5);
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(seatX - 3, seatY, 3, 2);

  ctx.fillStyle = '#334155';
  ctx.fillRect(seatX + seatW, seatY + 1, 2, 5);
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(seatX + seatW, seatY, 3, 2);

  // 5. Backrest
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
    ctx.fillRect(backX + 1, backY, backW - 2, 1);
  } else {
    ctx.fillStyle = mat.front;
    ctx.fillRect(seatX, seatY - 6, 3, 10);
  }

  ctx.restore();
}

// ============================================================================
// 5. 42U DATACENTER SERVER RACK CLUSTER SPRITE
// ============================================================================

export function renderIsometricServerRack(
  ctx: CanvasRenderingContext2D,
  f: Furniture2D | InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // Outer frame
  ctx.fillStyle = '#06070a';
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = '#1e222d';
  ctx.fillRect(1, 1, width - 2, 5);
  ctx.fillStyle = '#333a4c';
  ctx.fillRect(1, 1, width - 2, 1);

  // Top Exhaust Fans
  ctx.fillStyle = '#0a0d14';
  ctx.beginPath();
  ctx.arc(width * 0.3, 3.5, 2, 0, Math.PI * 2);
  ctx.arc(width * 0.7, 3.5, 2, 0, Math.PI * 2);
  ctx.fill();

  // Recessed 19" rack rails
  const railX = 3;
  const railY = 6;
  const railW = width - 6;
  const railH = height - 10;

  ctx.fillStyle = '#0b0e14';
  ctx.fillRect(railX, railY, railW, railH);

  // Server blade tiers
  const tierHeight = 5;
  const numTiers = Math.floor(railH / tierHeight);

  for (let i = 0; i < numTiers; i++) {
    const ty = railY + i * tierHeight;

    ctx.fillStyle = i % 2 === 0 ? '#141822' : '#1c2230';
    ctx.fillRect(railX + 1, ty, railW - 2, tierHeight - 1);

    ctx.fillStyle = '#2b3345';
    ctx.fillRect(railX + 1, ty, railW - 2, 1);

    ctx.fillStyle = '#080a0f';
    ctx.fillRect(railX + 3, ty + 1, railW - 14, tierHeight - 2);

    const ledSeed = (i * 137 + now / 180);
    const led1 = Math.sin(ledSeed) > 0.2;
    const led2 = Math.cos(ledSeed * 1.3) > -0.1;
    const isAlert = i === 3 && Math.sin(now / 150) > 0.5;

    ctx.fillStyle = isAlert ? '#ef4444' : led1 ? '#10b981' : '#047857';
    ctx.fillRect(railW - 7, ty + 1, 2, 1);

    ctx.fillStyle = led2 ? '#06b6d4' : '#0e7490';
    ctx.fillRect(railW - 4, ty + 1, 2, 1);

    if (i % 3 === 0) {
      ctx.strokeStyle = i % 6 === 0 ? '#38bdf8' : '#eab308';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(railX + 7, ty + 3, 2, 0, Math.PI);
      ctx.stroke();
    }
  }

  // Mesh glass door frame
  ctx.strokeStyle = '#38bdf830';
  ctx.lineWidth = 1;
  ctx.strokeRect(railX, railY, railW, railH);

  ctx.fillStyle = 'rgba(6, 182, 212, 0.08)';
  ctx.beginPath();
  ctx.moveTo(railX + 2, railY);
  ctx.lineTo(railX + 8, railY);
  ctx.lineTo(railX + 2, railY + railH);
  ctx.fill();

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(1, height - 4, width - 2, 4);

  ctx.restore();
}

// ============================================================================
// 6. BOARDROOM CONFERENCE TABLE SPRITE
// ============================================================================

export function renderIsometricConferenceTable(
  ctx: CanvasRenderingContext2D,
  f: Furniture2D,
  now: number
) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const mat = ISO_PALETTES.wood.dark_mahogany;

  // Dual pedestal columns
  ctx.fillStyle = '#0a0d14';
  ctx.fillRect(width * 0.22 - 6, 8, 12, height - 10);
  ctx.fillRect(width * 0.78 - 6, 12, 12, height - 10);
  ctx.fillStyle = '#334155';
  ctx.fillRect(width * 0.22 - 6, 8, 2, height - 10);
  ctx.fillRect(width * 0.78 - 6, 8, 2, height - 10);

  // Table thickness
  const topThickness = 6;
  ctx.fillStyle = mat.front;
  ctx.beginPath();
  ctx.roundRect(0, height - topThickness, width, topThickness, 4);
  ctx.fill();

  // Top surface
  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(1, 1, width - 2, height - topThickness, 4);
  ctx.fill();

  ctx.strokeStyle = mat.bevel;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(3, 3, width - 6, height - topThickness - 4);

  // Central power well
  const wellW = width * 0.45;
  const wellH = 10;
  const wellX = (width - wellW) / 2;
  const wellY = (height - topThickness - wellH) / 2;

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(wellX, wellY, wellW, wellH);
  ctx.fillStyle = '#475569';
  ctx.fillRect(wellX + 1, wellY + 1, wellW - 2, wellH - 2);
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(wellX + 1, wellY + 1, wellW - 2, 1);

  // Polycom conference phone
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

  // Attendee laptops & tumblers
  const attendeeXOffsets = [width * 0.18, width * 0.35, width * 0.65, width * 0.82];
  attendeeXOffsets.forEach((ax, idx) => {
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(ax - 5, wellY - 4, 10, 2);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(ax - 5, wellY - 9, 10, 5);
    ctx.fillStyle = idx % 2 === 0 ? '#38bdf8' : '#a855f7';
    ctx.fillRect(ax - 4, wellY - 8, 8, 3);

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

// ============================================================================
// 7. APPLIANCES & BREAKROOM SPRITES
// ============================================================================

export function renderIsometricEspressoMachine(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  ctx.fillStyle = '#334155';
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = '#64748b';
  ctx.fillRect(1, 1, width - 2, 4);
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(1, 1, width - 2, 1);

  // Cup warming rack
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(3, 0, 3, 2);
  ctx.fillRect(8, 0, 3, 2);
  ctx.fillRect(13, 0, 3, 2);

  ctx.fillStyle = '#475569';
  ctx.fillRect(2, 5, width - 4, height - 10);

  // Pressure gauges
  ctx.fillStyle = '#eab308';
  ctx.beginPath();
  ctx.arc(6, 8, 2, 0, Math.PI * 2);
  ctx.arc(width - 6, 8, 2, 0, Math.PI * 2);
  ctx.fill();

  // Dual group heads
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(width * 0.3 - 2, 10, 4, 3);
  ctx.fillRect(width * 0.7 - 2, 10, 4, 3);
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(width * 0.3 - 1, 13, 2, 4);
  ctx.fillRect(width * 0.7 - 1, 13, 2, 4);

  // Drip tray grill
  ctx.fillStyle = '#1e293b';
  ctx.fillRect(1, height - 5, width - 2, 5);
  ctx.fillStyle = '#94a3b8';
  for (let gx = 3; gx < width - 3; gx += 3) {
    ctx.fillRect(gx, height - 4, 1, 3);
  }

  // Steam animation
  if (Math.sin(now / 300) > 0.3) {
    const steamY = (now / 120) % 8;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
    ctx.fillRect(width * 0.3, 7 - steamY, 1.5, 2.5);
    ctx.fillRect(width * 0.7, 6 - steamY, 1.5, 2.5);
  }

  ctx.restore();
}

export function renderIsometricArcade(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#ec4899';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);

  // Marquee
  ctx.fillStyle = '#d946ef';
  ctx.fillRect(2, 2, width - 4, 7);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(2, 2, width - 4, 1);
  ctx.font = 'bold 5px monospace';
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.fillText('NEXUS', width / 2, 7);

  // CRT Screen
  const crtX = 3;
  const crtY = 10;
  const crtW = width - 6;
  const crtH = 12;

  ctx.fillStyle = '#020617';
  ctx.fillRect(crtX, crtY, crtW, crtH);

  const starOffset = (now / 80) % crtH;
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(crtX + 2, crtY + ((starOffset + 3) % crtH), 1, 1);
  ctx.fillRect(crtX + 8, crtY + ((starOffset + 7) % crtH), 1, 1);

  const shipX = crtX + crtW / 2 + Math.sin(now / 350) * 3;
  ctx.fillStyle = '#22c55e';
  ctx.fillRect(shipX - 2, crtY + crtH - 3, 4, 2);
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(shipX - 1, crtY + crtH - 4, 2, 1);

  // CRT Scanlines
  ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
  for (let sy = crtY; sy < crtY + crtH; sy += 2) {
    ctx.fillRect(crtX, sy, crtW, 1);
  }

  // Control Deck
  const deckY = crtY + crtH;
  ctx.fillStyle = '#1e1b4b';
  ctx.fillRect(2, deckY, width - 4, 6);

  // Joystick & buttons
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.arc(6, deckY + 2, 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(5.5, deckY + 3, 1, 2);

  ctx.fillStyle = '#06b6d4';
  ctx.fillRect(10, deckY + 1, 2, 2);
  ctx.fillRect(13, deckY + 1, 2, 2);
  ctx.fillStyle = '#eab308';
  ctx.fillRect(10, deckY + 3.5, 2, 2);
  ctx.fillRect(13, deckY + 3.5, 2, 2);

  // Coin door
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(4, deckY + 7, width - 8, height - (deckY + 9));
  ctx.fillStyle = '#f97316';
  ctx.fillRect(6, deckY + 9, 2, 4);
  ctx.fillRect(width - 8, deckY + 9, 2, 4);

  ctx.restore();
}

export function renderIsometricVending(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  ctx.fillStyle = '#1e1b4b';
  ctx.fillRect(0, 0, width, height);

  const winX = 2;
  const winY = 4;
  const winW = width - 14;
  const winH = height - 14;

  ctx.fillStyle = '#090d16';
  ctx.fillRect(winX, winY, winW, winH);

  const numShelves = 3;
  const shelfH = Math.floor(winH / numShelves);

  for (let s = 0; s < numShelves; s++) {
    const sy = winY + s * shelfH;
    ctx.fillStyle = '#475569';
    ctx.fillRect(winX + 1, sy + shelfH - 1, winW - 2, 1);

    const colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#ec4899'];
    for (let ix = winX + 2; ix < winX + winW - 4; ix += 4) {
      const c = colors[(s * 3 + Math.floor(ix / 4)) % colors.length] || '#ef4444';
      ctx.fillStyle = c;
      ctx.fillRect(ix, sy + 3, 3, shelfH - 4);
    }
  }

  // Specular sheen on glass
  ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
  ctx.beginPath();
  ctx.moveTo(winX + 2, winY);
  ctx.lineTo(winX + 8, winY);
  ctx.lineTo(winX + 2, winY + winH);
  ctx.fill();

  // Control column
  const colX = width - 11;
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(colX, 4, 9, winH);

  ctx.fillStyle = '#22c55e';
  ctx.fillRect(colX + 1, 6, 7, 3);

  ctx.fillStyle = '#94a3b8';
  for (let ky = 11; ky < 19; ky += 3) {
    ctx.fillRect(colX + 1.5, ky, 2, 2);
    ctx.fillRect(colX + 4.5, ky, 2, 2);
  }

  ctx.fillStyle = Math.sin(now / 300) > 0 ? '#22c55e' : '#15803d';
  ctx.fillRect(colX + 2, 21, 5, 2);

  // Dispenser flap
  ctx.fillStyle = '#020617';
  ctx.fillRect(2, height - 8, width - 4, 6);
  ctx.fillStyle = '#334155';
  ctx.fillRect(3, height - 7, width - 6, 4);

  ctx.restore();
}

export function renderIsometricWaterCooler(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  const bodyY = 12;
  const bodyH = height - bodyY;
  ctx.fillStyle = '#f8fafc';
  ctx.beginPath();
  ctx.roundRect(2, bodyY, width - 4, bodyH, 2);
  ctx.fill();
  ctx.fillStyle = '#cbd5e1';
  ctx.fillRect(width - 4, bodyY, 2, bodyH);

  // Recessed tap alcove
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(4, bodyY + 4, width - 8, 8);
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(5, bodyY + 5, 2, 3); // hot tap
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(width - 7, bodyY + 5, 2, 3); // cold tap

  // Clear water bottle
  ctx.fillStyle = 'rgba(6, 182, 212, 0.55)';
  ctx.beginPath();
  ctx.roundRect(3, 2, width - 6, 10, 3);
  ctx.fill();

  ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
  ctx.fillRect(4, 3, 2, 8);

  const bubbleY = (now / 200) % 8;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(width / 2, 10 - bubbleY, 1, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

// ============================================================================
// 8. LOUNGE, TABLES, SEATING & FOUNTAIN SPRITES
// ============================================================================

export function renderIsometricPlushSofa(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const mat = ISO_PALETTES.fabric.fabric_amber;

  // Legs
  ctx.fillStyle = '#3e2723';
  ctx.fillRect(3, height - 3, 2, 4);
  ctx.fillRect(width - 5, height - 3, 2, 4);

  // Backrest
  const backH = 8;
  ctx.fillStyle = mat.side;
  ctx.beginPath();
  ctx.roundRect(0, 0, width, backH, 3);
  ctx.fill();
  ctx.fillStyle = mat.top;
  ctx.fillRect(2, 1, width - 4, backH - 2);

  // Tufting buttons
  ctx.fillStyle = mat.bevel;
  for (let bx = 6; bx < width - 6; bx += 8) {
    ctx.fillRect(bx, 3, 2, 2);
  }

  // Seat
  const seatY = backH - 2;
  const seatH = height - seatY - 2;

  ctx.fillStyle = mat.front;
  ctx.fillRect(0, seatY + seatH - 3, width, 3);

  ctx.fillStyle = mat.top;
  ctx.beginPath();
  ctx.roundRect(0, seatY, width, seatH - 3, 2);
  ctx.fill();

  // Armrest cushions
  ctx.fillStyle = mat.cushion;
  ctx.beginPath();
  ctx.roundRect(0, seatY - 1, 5, seatH, 2);
  ctx.roundRect(width - 5, seatY - 1, 5, seatH, 2);
  ctx.fill();

  ctx.restore();
}

export function renderIsometricCoffeeTable(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // Brass hairpin legs
  ctx.strokeStyle = '#ca8a04';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(3, 4);
  ctx.lineTo(3, height);
  ctx.moveTo(width - 3, 4);
  ctx.lineTo(width - 3, height);
  ctx.stroke();

  // Smoked glass tabletop
  ctx.fillStyle = 'rgba(30, 41, 59, 0.85)';
  ctx.beginPath();
  ctx.roundRect(0, 0, width, height - 4, 3);
  ctx.fill();
  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Magazine / tech papers on table
  ctx.fillStyle = '#f43f5e';
  ctx.fillRect(width * 0.3, 4, 8, 6);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(width * 0.65, 5, 4, 8);

  ctx.restore();
}

export function renderIsometricZenBench(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;

  // Cast iron frame
  ctx.fillStyle = '#090a0f';
  ctx.fillRect(0, 2, 3, height - 2);
  ctx.fillRect(width - 3, 2, 3, height - 2);

  // Teak wood slats
  const slatH = 3;
  for (let sy = 2; sy < height - 2; sy += 5) {
    ctx.fillStyle = '#78350f';
    ctx.fillRect(3, sy, width - 6, slatH);
    ctx.fillStyle = '#b45309';
    ctx.fillRect(3, sy, width - 6, 1);
  }

  ctx.restore();
}

export function renderIsometricZenFountain(
  ctx: CanvasRenderingContext2D,
  poi: InteractivePOI,
  now: number
) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;
  const cx = width / 2;
  const cy = height / 2;
  const outerR = width / 2;

  // Granite basin
  ctx.fillStyle = '#1e293b';
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 3;
  ctx.stroke();

  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, outerR - 1, Math.PI * 0.8, Math.PI * 1.8);
  ctx.stroke();

  // Water pool
  ctx.fillStyle = '#0284c7';
  ctx.beginPath();
  ctx.arc(cx, cy, outerR - 4, 0, Math.PI * 2);
  ctx.fill();

  // Animated ripples
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

  // Center pedestal
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

// ============================================================================
// 9. WHITEBOARDS, BOOKSHELVES, PLANTERS & PROPS
// ============================================================================

export function renderIsometricWhiteboard(ctx: CanvasRenderingContext2D, poi: InteractivePOI) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;

  // Caster feet
  ctx.fillStyle = '#334155';
  ctx.fillRect(4, height - 5, 4, 5);
  ctx.fillRect(width - 8, height - 5, 4, 5);

  // Frame
  ctx.fillStyle = '#64748b';
  ctx.fillRect(0, 0, width, height - 5);

  // White porcelain surface
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(2, 2, width - 4, height - 9);

  // Marker tray & markers
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(4, height - 7, width - 8, 2);
  ctx.fillStyle = '#ef4444';
  ctx.fillRect(8, height - 8, 4, 1);
  ctx.fillStyle = '#3b82f6';
  ctx.fillRect(14, height - 8, 4, 1);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(20, height - 8, 4, 1);

  // Sticky notes
  ctx.fillStyle = '#fef08a';
  ctx.fillRect(6, 4, 8, 7);
  ctx.fillStyle = '#f43f5e';
  ctx.fillRect(16, 4, 8, 7);
  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(26, 4, 8, 7);

  // Flowchart diagram nodes & arrows
  const startX = 40;
  const nodeW = 22;
  const nodeH = 9;

  ctx.fillStyle = '#1e293b';
  ctx.fillRect(startX, 4, nodeW, nodeH);
  ctx.fillStyle = '#10b981';
  ctx.fillRect(startX + 30, 4, nodeW, nodeH);
  ctx.fillStyle = '#8b5cf6';
  ctx.fillRect(startX + 60, 4, nodeW, nodeH);

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

export function renderIsometricBookshelf(ctx: CanvasRenderingContext2D, poi: InteractivePOI) {
  ctx.save();
  ctx.translate(poi.x, poi.y);

  const { width, height } = poi;
  const mat = ISO_PALETTES.wood.dark_mahogany;

  // Outer frame
  ctx.fillStyle = mat.side;
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = mat.top;
  ctx.fillRect(1, 1, width - 2, height - 2);

  // Shelves and books
  const numShelves = 2;
  const shelfH = Math.floor((height - 4) / numShelves);

  for (let s = 0; s < numShelves; s++) {
    const sy = 2 + s * shelfH;
    ctx.fillStyle = mat.bevel;
    ctx.fillRect(2, sy + shelfH - 2, width - 4, 2);

    const bookColors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4', '#e2e8f0', '#d946ef'];
    let bx = 4;
    let bIdx = s * 4;
    while (bx < width - 6) {
      const bw = 2 + (bIdx % 3);
      ctx.fillStyle = bookColors[bIdx % bookColors.length] || '#ef4444';
      ctx.fillRect(bx, sy + 2, bw, shelfH - 4);
      ctx.fillStyle = '#fef08a';
      ctx.fillRect(bx, sy + 4, bw, 1);
      bx += bw + 1;
      bIdx++;
    }
  }

  ctx.restore();
}

export function renderIsometricPottedPlant(ctx: CanvasRenderingContext2D, f: Furniture2D) {
  ctx.save();
  ctx.translate(f.x, f.y);

  const { width, height } = f;
  const cx = width / 2;

  // Terracotta pot
  const potW = width * 0.65;
  const potH = height * 0.45;
  const potX = cx - potW / 2;
  const potY = height - potH - 2;

  ctx.fillStyle = '#9a3412';
  ctx.beginPath();
  ctx.roundRect(potX, potY, potW, potH, 2);
  ctx.fill();
  ctx.fillStyle = '#c2410c';
  ctx.fillRect(potX + 1, potY + 1, potW - 3, potH - 2);

  ctx.fillStyle = '#ea580c';
  ctx.fillRect(potX - 1, potY, potW + 2, 2);

  ctx.fillStyle = '#1c1917';
  ctx.fillRect(potX + 1, potY, potW - 2, 2);

  // Foliage
  ctx.fillStyle = '#14532d';
  ctx.beginPath();
  ctx.arc(cx - 3, potY - 4, 8, 0, Math.PI * 2);
  ctx.arc(cx + 4, potY - 3, 7, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#16a34a';
  ctx.beginPath();
  ctx.arc(cx, potY - 6, 7, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#4ade80';
  ctx.beginPath();
  ctx.arc(cx + 2, potY - 7, 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

export function renderIsometricEnvironmentalProp(
  ctx: CanvasRenderingContext2D,
  prop: EnvironmentalProp2D,
  now: number
) {
  ctx.save();
  ctx.translate(prop.x, prop.y);

  const { width, height, type } = prop;

  if (type === 'printer') {
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
    ctx.fillStyle = '#1e293b';
    ctx.beginPath();
    ctx.roundRect(2, height - 8, width - 4, 6, 2);
    ctx.fill();

    ctx.strokeStyle = '#78350f';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(width / 2, height - 8);
    ctx.lineTo(width / 2 - 3, height - 14);
    ctx.lineTo(width / 2 + 2, height - 18);
    ctx.stroke();

    ctx.fillStyle = '#15803d';
    ctx.beginPath();
    ctx.arc(width / 2 - 4, height - 16, 5, 0, Math.PI * 2);
    ctx.arc(width / 2 + 4, height - 19, 6, 0, Math.PI * 2);
    ctx.fill();
  } else if (type === 'storage_box') {
    ctx.fillStyle = '#d97706';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#b45309';
    ctx.fillRect(0, 0, width, 3);
    ctx.fillStyle = '#78350f';
    ctx.fillRect(width / 2 - 1, 0, 2, height);
  } else if (type === 'exit_sign') {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#22c55e';
    ctx.fillRect(1, 1, width - 2, height - 2);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 6px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('EXIT →', width / 2, height - 3);
  } else if (type === 'floor_lamp' || type === 'wall_sconce') {
    ctx.fillStyle = '#ca8a04';
    ctx.fillRect(width / 2 - 1, 0, 2, height);
    ctx.fillStyle = '#fef08a';
    ctx.beginPath();
    ctx.arc(width / 2, 4, 4, 0, Math.PI * 2);
    ctx.fill();
  } else {
    ctx.fillStyle = '#334155';
    ctx.fillRect(0, 0, width, height);
  }

  ctx.restore();
}

export { PixelAssets } from './PixelAssets';

