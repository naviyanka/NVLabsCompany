import type { Office2DLayout } from './types';

/**
 * 2.5D Architectural Office Floor Plan & 3D Wall Renderer
 * Implements high-craft textured floors, 3D perspective walls with bevel caps & drop shadows,
 * authentic glass partitions with specular mullions, Persian rugs, wooden decking, and stone pathways.
 */
export function drawOfficeFloor(
  ctx: CanvasRenderingContext2D,
  layout: Office2DLayout
) {
  // 1. Dark Structural Foundation Slab
  ctx.fillStyle = '#050608';
  ctx.fillRect(0, 0, layout.width, layout.height);

  // 2. Corridors & Main Aisle Foundation
  ctx.fillStyle = '#0b0d12';
  ctx.fillRect(28, 28, layout.width - 56, layout.height - 56);

  // Corridor Tile Seams Grid
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)';
  ctx.lineWidth = 1;
  const corridorGrid = 28;
  for (let x = 28; x < layout.width - 28; x += corridorGrid) {
    ctx.beginPath();
    ctx.moveTo(x, 28);
    ctx.lineTo(x, layout.height - 28);
    ctx.stroke();
  }
  for (let y = 28; y < layout.height - 28; y += corridorGrid) {
    ctx.beginPath();
    ctx.moveTo(28, y);
    ctx.lineTo(layout.width - 28, y);
    ctx.stroke();
  }

  // Corridor Center Carpet Runner (East-West Main Avenue: y: 282 to 318)
  ctx.fillStyle = '#12141f';
  ctx.fillRect(36, 286, 1150, 32);
  ctx.strokeStyle = 'rgba(168, 85, 247, 0.3)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(36, 286, 1150, 32);

  // South Corridor Carpet Runner (y: 628 to 648)
  ctx.fillStyle = '#12141f';
  ctx.fillRect(36, 630, 880, 20);
  ctx.strokeStyle = 'rgba(59, 130, 246, 0.25)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(36, 630, 880, 20);

  // 3. Render Room Floors & Rich Materials
  layout.rooms.forEach((room) => {
    ctx.save();

    // Dark outer border to fake recessed wall depth
    ctx.fillStyle = '#06070a';
    ctx.fillRect(room.x - 2, room.y - 2, room.width + 4, room.height + 4);

    // Floor Base Color
    ctx.fillStyle = room.floorColor;
    ctx.fillRect(room.x, room.y, room.width, room.height);

    // Floor Patterns per Zone Type
    if (room.floorPattern === 'wood') {
      // Executive Suite: Rich Herringbone Parquet Wood Flooring with Plank Grain
      const plankH = 12;
      const plankW = 28;
      for (let py = room.y; py < room.y + room.height; py += plankH) {
        const rowIdx = Math.floor((py - room.y) / plankH);
        const offsetX = (rowIdx % 2) * (plankW / 2);
        
        // Horizontal plank joint
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(room.x, py);
        ctx.lineTo(room.x + room.width, py);
        ctx.stroke();

        // Vertical plank seams and subtle wood grain
        for (let px = room.x - plankW + offsetX; px < room.x + room.width; px += plankW) {
          ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
          ctx.beginPath();
          ctx.moveTo(px, py);
          ctx.lineTo(px, py + plankH);
          ctx.stroke();

          // Subtle woodgrain line inside plank
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
          ctx.beginPath();
          ctx.moveTo(px + 4, py + 3);
          ctx.lineTo(px + plankW - 4, py + 3);
          ctx.stroke();
        }
      }

      // Executive Luxury Persian / Oriental Area Rug under desk
      const rugX = room.x + 28;
      const rugY = room.y + 36;
      const rugW = 248;
      const rugH = 158;

      // Soft blur drop shadow of rug
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.65)';
      ctx.shadowBlur = 8;
      ctx.shadowOffsetY = 4;
      ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
      ctx.fillRect(rugX + 2, rugY + 3, rugW, rugH);
      ctx.restore();

      // Gold fringe on left and right ends
      ctx.fillStyle = '#f59e0b';
      for (let fy = rugY + 4; fy < rugY + rugH - 4; fy += 4) {
        ctx.fillRect(rugX - 3, fy, 3, 2);
        ctx.fillRect(rugX + rugW, fy, 3, 2);
      }

      // Rug outer border (Burgundy red)
      ctx.fillStyle = '#45100c';
      ctx.fillRect(rugX, rugY, rugW, rugH);

      // Outer gold border band
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 2.5;
      ctx.strokeRect(rugX + 3, rugY + 3, rugW - 6, rugH - 6);

      // Inner decorative border
      ctx.fillStyle = '#5c1410';
      ctx.fillRect(rugX + 8, rugY + 8, rugW - 16, rugH - 16);

      ctx.strokeStyle = 'rgba(251, 191, 36, 0.5)';
      ctx.lineWidth = 1;
      ctx.strokeRect(rugX + 12, rugY + 12, rugW - 24, rugH - 24);

      // Center medallion core
      ctx.fillStyle = '#3a0c09';
      ctx.fillRect(rugX + 20, rugY + 20, rugW - 40, rugH - 40);

      // Medallion diamond pattern in center
      ctx.strokeStyle = '#f59e0b60';
      ctx.lineWidth = 1.2;
      const mcx = rugX + rugW / 2;
      const mcy = rugY + rugH / 2;
      ctx.beginPath();
      ctx.moveTo(mcx, mcy - 30);
      ctx.lineTo(mcx + 45, mcy);
      ctx.lineTo(mcx, mcy + 30);
      ctx.lineTo(mcx - 45, mcy);
      ctx.closePath();
      ctx.stroke();

    } else if (room.floorPattern === 'carpet') {
      // War Room: Deep Royal Purple Acoustic Carpet with Inlaid Double Border
      ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
      for (let px = room.x; px < room.x + room.width; px += 14) {
        for (let py = room.y; py < room.y + room.height; py += 14) {
          if (((px - room.x) / 14 + (py - room.y) / 14) % 2 === 0) {
            ctx.fillRect(px, py, 14, 14);
          }
        }
      }
      // Boardroom Center Inlaid Glow Border
      ctx.strokeStyle = '#8b5cf640';
      ctx.lineWidth = 2;
      ctx.strokeRect(room.x + 18, room.y + 18, room.width - 36, room.height - 36);
      ctx.strokeStyle = '#a855f720';
      ctx.lineWidth = 1;
      ctx.strokeRect(room.x + 24, room.y + 24, room.width - 48, room.height - 48);

    } else if (room.floorPattern === 'checkered') {
      // Breakroom: Warm Honey Oak & Dark Walnut Parquet Checkerboard Tiles with Grout
      const tileSize = 24;
      for (let px = room.x; px < room.x + room.width; px += tileSize) {
        for (let py = room.y; py < room.y + room.height; py += tileSize) {
          const isAlt = ((px - room.x) / tileSize + (py - room.y) / tileSize) % 2 === 0;
          ctx.fillStyle = isAlt ? '#3a2a1c' : '#221912';
          ctx.fillRect(px, py, tileSize, tileSize);

          // Specular highlight / bevel seam on each tile
          ctx.fillStyle = isAlt ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.02)';
          ctx.fillRect(px + 1, py + 1, tileSize - 2, 1);
          ctx.fillRect(px + 1, py + 1, 1, tileSize - 2);

          // Grout shadow
          ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
          ctx.fillRect(px, py + tileSize - 1, tileSize, 1);
          ctx.fillRect(px + tileSize - 1, py, 1, tileSize);
        }
      }
      // Kitchen Counter Flooring Trim
      ctx.fillStyle = '#4a3724';
      ctx.fillRect(room.x + 8, room.y + 46, 170, 4);

    } else if (room.floorPattern === 'dark_slate') {
      // Server Vault: Antistatic Raised Floor Panels & Cyan LED Underglow
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.22)';
      ctx.lineWidth = 1;
      const slateSize = 32;
      for (let px = room.x; px < room.x + room.width; px += slateSize) {
        ctx.beginPath();
        ctx.moveTo(px, room.y);
        ctx.lineTo(px, room.y + room.height);
        ctx.stroke();
      }
      for (let py = room.y; py < room.y + room.height; py += slateSize) {
        ctx.beginPath();
        ctx.moveTo(room.x, py);
        ctx.lineTo(room.x + room.width, py);
        ctx.stroke();
      }
      // Corner floor plate screws & illuminated LEDs
      ctx.fillStyle = '#0891b2';
      for (let px = room.x; px <= room.x + room.width; px += slateSize) {
        for (let py = room.y; py <= room.y + room.height; py += slateSize) {
          ctx.fillRect(px - 1.5, py - 1.5, 3, 3);
        }
      }
      // Cable Ducts / Yellow Caution Stripes
      ctx.fillStyle = '#eab30830';
      ctx.fillRect(room.x + 20, room.y + room.height - 18, room.width - 40, 6);
      for (let cx = room.x + 20; cx < room.x + room.width - 20; cx += 12) {
        ctx.fillStyle = '#00000050';
        ctx.beginPath();
        ctx.moveTo(cx, room.y + room.height - 12);
        ctx.lineTo(cx + 6, room.y + room.height - 18);
        ctx.lineTo(cx + 9, room.y + room.height - 18);
        ctx.lineTo(cx + 3, room.y + room.height - 12);
        ctx.fill();
      }

    } else if (room.floorPattern === 'zen_stone') {
      // Zen Garden: Split Teak Decking + Lush Green Grass & Stone Stepping Path
      ctx.fillStyle = '#0b1610';
      ctx.fillRect(room.x, room.y, room.width, room.height);

      // Grass Texture / Moss Specks
      ctx.fillStyle = '#13281b';
      for (let gx = room.x; gx < room.x + room.width; gx += 16) {
        for (let gy = room.y; gy < room.y + room.height; gy += 16) {
          if ((gx + gy) % 32 === 0) {
            ctx.fillRect(gx + 4, gy + 4, 3, 2);
          }
        }
      }

      // Wooden Deck Platform (Western side)
      const deckX = room.x + 30;
      const deckY = room.y + 60;
      const deckW = 160;
      const deckH = room.height - 100;

      // Deck drop shadow
      ctx.save();
      ctx.shadowColor = 'rgba(0, 0, 0, 0.7)';
      ctx.shadowBlur = 10;
      ctx.shadowOffsetY = 4;
      ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
      ctx.fillRect(deckX + 4, deckY + 4, deckW, deckH);
      ctx.restore();

      // Deck planks
      ctx.fillStyle = '#3a271a';
      ctx.fillRect(deckX, deckY, deckW, deckH);

      ctx.strokeStyle = '#23170e';
      ctx.lineWidth = 1.5;
      for (let dy = deckY; dy < deckY + deckH; dy += 14) {
        ctx.beginPath();
        ctx.moveTo(deckX, dy);
        ctx.lineTo(deckX + deckW, dy);
        ctx.stroke();

        // Plank top highlight
        ctx.fillStyle = '#4d3524';
        ctx.fillRect(deckX, dy + 1, deckW, 1);
      }

      // Deck outer perimeter border
      ctx.strokeStyle = '#573c29';
      ctx.lineWidth = 2;
      ctx.strokeRect(deckX, deckY, deckW, deckH);

      // Winding Natural Stone Stepping Tiles
      const stoneCoords = [
        { x: room.x + 220, y: room.y + 80, rx: 18, ry: 13 },
        { x: room.x + 250, y: room.y + 130, rx: 17, ry: 12 },
        { x: room.x + 275, y: room.y + 185, rx: 19, ry: 14 },
        { x: room.x + 265, y: room.y + 245, rx: 16, ry: 12 },
        { x: room.x + 235, y: room.y + 300, rx: 18, ry: 13 },
        { x: room.x + 215, y: room.y + 360, rx: 17, ry: 13 },
        { x: room.x + 260, y: room.y + 405, rx: 19, ry: 14 },
        { x: room.x + 320, y: room.y + 420, rx: 18, ry: 12 },
        { x: room.x + 380, y: room.y + 415, rx: 17, ry: 13 },
      ];

      stoneCoords.forEach((st) => {
        // Stone shadow
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.beginPath();
        ctx.ellipse(st.x + 2, st.y + 3, st.rx, st.ry, 0.15, 0, Math.PI * 2);
        ctx.fill();

        // Stone body
        ctx.fillStyle = '#2f3d35';
        ctx.beginPath();
        ctx.ellipse(st.x, st.y, st.rx, st.ry, 0.15, 0, Math.PI * 2);
        ctx.fill();

        // Stone highlight
        ctx.fillStyle = '#425349';
        ctx.beginPath();
        ctx.ellipse(st.x - 2, st.y - 2, st.rx - 4, st.ry - 3, 0.15, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = '#232e27';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.ellipse(st.x, st.y, st.rx, st.ry, 0.15, 0, Math.PI * 2);
        ctx.stroke();
      });

    } else {
      // Standard Dev / QA / Analytics Carpet Grid
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
      ctx.lineWidth = 1;
      for (let px = room.x; px < room.x + room.width; px += 24) {
        ctx.beginPath();
        ctx.moveTo(px, room.y);
        ctx.lineTo(px, room.y + room.height);
        ctx.stroke();
      }
      for (let py = room.y; py < room.y + room.height; py += 24) {
        ctx.beginPath();
        ctx.moveTo(room.x, py);
        ctx.lineTo(room.x + room.width, py);
        ctx.stroke();
      }
    }

    // 3b. Material Roughness & Non-Uniform Floor Grain Noise Pass
    let rng = ((room.x * 73856093) ^ (room.y * 19349663) ^ (room.width * 83492791)) >>> 0;
    const nextRand = () => {
      rng = (rng ^ (rng << 13)) >>> 0;
      rng = (rng ^ (rng >> 17)) >>> 0;
      rng = (rng ^ (rng << 5)) >>> 0;
      return (rng >>> 0) / 4294967296;
    };

    const dotCount = Math.floor((room.width * room.height) / 340);
    for (let i = 0; i < dotCount; i++) {
      const nx = room.x + 3 + nextRand() * (room.width - 6);
      const ny = room.y + 3 + nextRand() * (room.height - 6);
      const isLight = nextRand() > 0.45;
      const size = nextRand() > 0.8 ? 2 : 1;
      
      if (isLight) {
        ctx.fillStyle = `rgba(255, 255, 255, ${(0.02 + nextRand() * 0.035).toFixed(3)})`;
      } else {
        ctx.fillStyle = `rgba(0, 0, 0, ${(0.03 + nextRand() * 0.045).toFixed(3)})`;
      }
      ctx.fillRect(Math.floor(nx), Math.floor(ny), size, size);
    }

    // 4. Room-Specific Dynamic Radial Gradient Light Overlay (Luminous Soft Glow with Screen Blend)
    const roomCenterX = room.x + room.width / 2;
    const roomCenterY = room.y + room.height / 2;
    const maxRadius = Math.max(room.width, room.height) * 0.65;
    const radGrad = ctx.createRadialGradient(
      roomCenterX,
      roomCenterY,
      8,
      roomCenterX,
      roomCenterY,
      maxRadius
    );

    if (room.type === 'server') {
      radGrad.addColorStop(0, 'rgba(6, 182, 212, 0.20)');
      radGrad.addColorStop(0.5, 'rgba(6, 182, 212, 0.05)');
      radGrad.addColorStop(1, 'rgba(6, 182, 212, 0)');
    } else if (room.type === 'breakroom') {
      radGrad.addColorStop(0, 'rgba(245, 158, 11, 0.18)');
      radGrad.addColorStop(0.5, 'rgba(245, 158, 11, 0.05)');
      radGrad.addColorStop(1, 'rgba(245, 158, 11, 0)');
    } else if (room.type === 'zen_garden') {
      radGrad.addColorStop(0, 'rgba(16, 185, 129, 0.16)');
      radGrad.addColorStop(0.5, 'rgba(16, 185, 129, 0.04)');
      radGrad.addColorStop(1, 'rgba(16, 185, 129, 0)');
    } else if (room.type === 'executive') {
      radGrad.addColorStop(0, 'rgba(251, 191, 36, 0.16)');
      radGrad.addColorStop(0.5, 'rgba(251, 191, 36, 0.04)');
      radGrad.addColorStop(1, 'rgba(251, 191, 36, 0)');
    } else if (room.type === 'meeting') {
      radGrad.addColorStop(0, 'rgba(168, 85, 247, 0.18)');
      radGrad.addColorStop(0.5, 'rgba(168, 85, 247, 0.05)');
      radGrad.addColorStop(1, 'rgba(168, 85, 247, 0)');
    } else if (room.type === 'qa') {
      radGrad.addColorStop(0, 'rgba(239, 68, 68, 0.18)');
      radGrad.addColorStop(0.5, 'rgba(239, 68, 68, 0.05)');
      radGrad.addColorStop(1, 'rgba(239, 68, 68, 0)');
    } else {
      radGrad.addColorStop(0, 'rgba(59, 130, 246, 0.15)');
      radGrad.addColorStop(0.5, 'rgba(59, 130, 246, 0.04)');
      radGrad.addColorStop(1, 'rgba(59, 130, 246, 0)');
    }

    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    ctx.fillStyle = radGrad;
    ctx.fillRect(room.x, room.y, room.width, room.height);
    ctx.restore();

    // 5. Architectural Wall Bevel Lip Around Room Perimeter (Outer 2px shadow line, 3-4px wall body lip, 1px top-left highlight)
    // Outer shadow line
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.7)';
    ctx.lineWidth = 2;
    ctx.strokeRect(room.x - 1, room.y - 1, room.width + 2, room.height + 2);

    // Midtone wall body lip border
    ctx.strokeStyle = room.wallColor || '#334155';
    ctx.lineWidth = 3;
    ctx.strokeRect(room.x + 0.5, room.y + 0.5, room.width - 1, room.height - 1);

    // Top & Left facing edges 1px lighter highlight line (Top-left illumination)
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(room.x, room.y + room.height);
    ctx.lineTo(room.x, room.y);
    ctx.lineTo(room.x + room.width, room.y);
    ctx.stroke();

    // Bottom & Right facing edges recessed dark shadow line
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(room.x + room.width, room.y);
    ctx.lineTo(room.x + room.width, room.y + room.height);
    ctx.lineTo(room.x, room.y + room.height);
    ctx.stroke();

    // Room Label Header Banner with luminous glow and accent border
    ctx.font = 'bold 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const text = room.label;
    const textWidth = ctx.measureText(text).width;
    const bannerW = textWidth + 24;
    const bannerH = 18;
    const bannerX = room.x + 10;
    const bannerY = room.y + 10;

    // Banner drop shadow
    ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
    ctx.beginPath();
    ctx.roundRect(bannerX + 1, bannerY + 2, bannerW, bannerH, 4);
    ctx.fill();

    // Banner background
    ctx.fillStyle = '#0a0d14f0';
    ctx.beginPath();
    ctx.roundRect(bannerX, bannerY, bannerW, bannerH, 4);
    ctx.fill();

    // Glowing border in room accent color
    ctx.strokeStyle = `${room.accentColor}80`;
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // Glowing status indicator dot
    ctx.fillStyle = room.accentColor;
    ctx.beginPath();
    ctx.arc(bannerX + 8, bannerY + bannerH / 2, 2.5, 0, Math.PI * 2);
    ctx.fill();

    // Label text
    ctx.fillStyle = '#f8fafc';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, bannerX + 16, bannerY + bannerH / 2);

    ctx.restore();
  });

  // 4. Render Doorways & Thresholds
  layout.doorways.forEach((door) => {
    ctx.save();
    ctx.fillStyle = '#1e2129';
    ctx.fillRect(door.x, door.y, door.width, door.height);

    ctx.strokeStyle = '#eab30870';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(door.x + 1, door.y + 1, door.width - 2, door.height - 2);

    // Grip lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.lineWidth = 1;
    if (door.width > door.height) {
      for (let lx = door.x + 6; lx < door.x + door.width - 6; lx += 8) {
        ctx.beginPath();
        ctx.moveTo(lx, door.y + 2);
        ctx.lineTo(lx, door.y + door.height - 2);
        ctx.stroke();
      }
    } else {
      for (let ly = door.y + 6; ly < door.y + door.height - 6; ly += 8) {
        ctx.beginPath();
        ctx.moveTo(door.x + 2, ly);
        ctx.lineTo(door.x + door.width - 2, ly);
        ctx.stroke();
      }
    }

    ctx.restore();
  });

  // 5. Render Architectural Walls (with 3D Isometric Volume, Bevel Caps & Soft Drop Shadows)
  layout.walls.forEach((wall) => {
    ctx.save();

    if (wall.type === 'glass') {
      // Glass Partition Wall with Specular Sheen and Mullions
      // Drop shadow
      ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
      ctx.fillRect(wall.x + 2, wall.y + wall.height, wall.width, 6);

      // Glass tint body
      ctx.fillStyle = 'rgba(6, 182, 212, 0.25)';
      ctx.fillRect(wall.x, wall.y, wall.width, wall.height);

      // Specular top highlight
      ctx.fillStyle = '#7dd3fc';
      ctx.fillRect(wall.x, wall.y, wall.width, 2);

      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(wall.x, wall.y, wall.width, wall.height);

      // Vertical steel mullions
      ctx.fillStyle = '#0284c7';
      for (let mx = wall.x + 24; mx < wall.x + wall.width - 10; mx += 28) {
        ctx.fillRect(mx, wall.y, 3, wall.height);
        ctx.fillStyle = '#bae6fd';
        ctx.fillRect(mx, wall.y, 1, wall.height);
        ctx.fillStyle = '#0284c7';
      }

      // Specular sheen diagonal stripes
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)';
      ctx.lineWidth = 1.2;
      for (let sx = wall.x + 10; sx < wall.x + wall.width - 10; sx += 40) {
        ctx.beginPath();
        ctx.moveTo(sx, wall.y + wall.height);
        ctx.lineTo(sx + 10, wall.y);
        ctx.stroke();
      }
    } else if (wall.type === 'partition') {
      // Acoustic Pod Partition (with 3D depth)
      ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
      ctx.fillRect(wall.x + 2, wall.y + wall.height, wall.width, 7);

      ctx.fillStyle = '#1c222e';
      ctx.fillRect(wall.x, wall.y, wall.width, wall.height);

      // Bevel top rail
      ctx.fillStyle = '#3b82f6';
      ctx.fillRect(wall.x, wall.y, wall.width, 2);

      ctx.strokeStyle = '#2a374d';
      ctx.lineWidth = 1;
      ctx.strokeRect(wall.x, wall.y, wall.width, wall.height);
    } else if (wall.type === 'exterior') {
      // Exterior Heavy Building Wall
      ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
      ctx.fillRect(wall.x + 3, wall.y + wall.height, wall.width, 10);

      ctx.fillStyle = '#14161d';
      ctx.fillRect(wall.x, wall.y, wall.width, wall.height);

      // Top bevel cap
      ctx.fillStyle = '#363a48';
      ctx.fillRect(wall.x, wall.y, wall.width, 3);
      ctx.fillStyle = '#4c5264';
      ctx.fillRect(wall.x, wall.y, wall.width, 1);

      // Exterior Window Insets
      if (wall.width > 200) {
        ctx.fillStyle = '#06b6d445';
        for (let wx = wall.x + 60; wx < wall.x + wall.width - 60; wx += 120) {
          ctx.fillRect(wx, wall.y + 2, 40, wall.height - 4);
          ctx.strokeStyle = '#38bdf8';
          ctx.lineWidth = 1;
          ctx.strokeRect(wx, wall.y + 2, 40, wall.height - 4);
        }
      }
    } else {
      // Standard Solid Architectural Wall with 3D Bevel Top, Gradient Face & Drop Shadow
      // 1. Deep 3D Drop Shadow cast downward onto floor (Outer 2px shadow line + soft spread)
      ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
      ctx.fillRect(wall.x, wall.y + wall.height, wall.width, 8);
      ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
      ctx.fillRect(wall.x - 2, wall.y + wall.height + 8, wall.width + 4, 3);

      // 2. Wall Vertical Face & Base Skirting
      ctx.fillStyle = '#161922';
      ctx.fillRect(wall.x, wall.y, wall.width, wall.height);

      // 3. Wall Midtone Body Lip (3-4px thickness)
      ctx.fillStyle = '#343b4d';
      ctx.fillRect(wall.x + 1, wall.y + 1, wall.width - 2, wall.height - 2);

      // 4. Wall Top Face / Cap
      ctx.fillStyle = '#47536d';
      ctx.fillRect(wall.x + 1, wall.y + 1, wall.width - 2, 4);

      // 5. 1px Lighter Highlight Line along the Top-Left-Facing Edges
      ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
      ctx.fillRect(wall.x, wall.y, wall.width, 1); // Top edge specular line
      ctx.fillRect(wall.x, wall.y, 1, wall.height); // Left edge specular line

      // 6. Outer 2px Dark Shadow Outline on Bottom & Right Edges
      ctx.fillStyle = '#090a0f';
      ctx.fillRect(wall.x, wall.y + wall.height - 1, wall.width, 1);
      ctx.fillRect(wall.x + wall.width - 1, wall.y, 1, wall.height);
    }

    ctx.restore();
  });
}
