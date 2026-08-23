import type { LightingMode, Office2DLayout, Agent2D } from './types';

/**
 * Atmospheric & Radial Lighting Engine for 2D Office
 * Handles ceiling downlights, monitor screen glows, ambient room filters,
 * and time-of-day/cyberpunk lighting composites.
 */

interface LightSource {
  x: number;
  y: number;
  radius: number;
  color: string;
  intensity: number;
}

export function drawOfficeLighting(
  ctx: CanvasRenderingContext2D,
  layout: Office2DLayout,
  agents: Agent2D[],
  lighting: LightingMode,
  now: number
) {
  ctx.save();

  // 1. Collect Active Dynamic Light Sources
  const lights: LightSource[] = [];

  // Working agents cast subtle task illumination on their desks
  agents.forEach((agent) => {
    if (agent.status === 'working') {
      lights.push({
        x: agent.x,
        y: agent.y - 6,
        radius: 28,
        color: 'rgba(56, 189, 248, 0.08)',
        intensity: 0.1,
      });
    }
  });

  // Ceiling Downlights & Ambient Area Illumination per Room Zone
  layout.rooms.forEach((room) => {
    // 1. Base Ambient Zone Fill (ensures every zone is legibly illuminated)
    lights.push({
      x: room.x + room.width / 2,
      y: room.y + room.height / 2,
      radius: Math.max(room.width, room.height) * 0.75,
      color: 'rgba(255, 255, 255, 0.055)', // Crisp clean daylight ambient base
      intensity: 0.1,
    });

    if (room.type === 'executive') {
      // Warm Executive Sconce
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 200,
        color: 'rgba(251, 191, 36, 0.16)', // Amber warm
        intensity: 0.18,
      });
    } else if (room.type === 'server') {
      // Cool Cyan Server Cooling Light (Subtle breathing pulse)
      const pulse = Math.sin(now / 800) * 0.03;
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 240,
        color: `rgba(6, 182, 212, ${0.22 + pulse})`,
        intensity: 0.22,
      });
    } else if (room.type === 'meeting') {
      // Focused Boardroom Downlight
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 220,
        color: 'rgba(168, 85, 247, 0.16)',
        intensity: 0.18,
      });
    } else if (room.type === 'breakroom') {
      // Warm Café Chandelier
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 260,
        color: 'rgba(245, 158, 11, 0.18)',
        intensity: 0.18,
      });
    } else if (room.type === 'zen_garden') {
      // Soft Emerald Glow
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 280,
        color: 'rgba(52, 211, 153, 0.14)',
        intensity: 0.15,
      });
    } else if (room.type === 'analytics') {
      // Pipelines Violet Luminescence
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 220,
        color: 'rgba(139, 92, 246, 0.16)',
        intensity: 0.16,
      });
    } else if (room.type === 'qa') {
      // Security Warm Crimson Glow
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 200,
        color: 'rgba(239, 68, 68, 0.16)',
        intensity: 0.16,
      });
    } else {
      // Engineering & Synthetic Benchmark Azure Downlight
      lights.push({
        x: room.x + room.width / 2,
        y: room.y + room.height / 2,
        radius: 220,
        color: 'rgba(56, 189, 248, 0.15)',
        intensity: 0.15,
      });
    }
  });

  // Desk Lamps & Monitor Screen Light Cones
  layout.desks.forEach((desk) => {
    if (desk.lampOn) {
      lights.push({
        x: desk.x + 16,
        y: desk.y + 14,
        radius: 45,
        color: 'rgba(251, 191, 36, 0.25)',
        intensity: 0.3,
      });
    }
    if (desk.hasComputer) {
      lights.push({
        x: desk.x + desk.width / 2,
        y: desk.y + 16,
        radius: 35,
        color: desk.screenColor + '20',
        intensity: 0.15,
      });
    }
  });

  // Server Racks Pulsing Cyan Light
  layout.pois.forEach((poi) => {
    if (poi.type === 'server_rack') {
      lights.push({
        x: poi.x + poi.width / 2,
        y: poi.y + poi.height / 2,
        radius: 90,
        color: 'rgba(6, 182, 212, 0.22)',
        intensity: 0.25,
      });
    } else if (poi.type === 'arcade') {
      lights.push({
        x: poi.x + poi.width / 2,
        y: poi.y + poi.height / 2,
        radius: 60,
        color: 'rgba(236, 72, 153, 0.25)',
        intensity: 0.25,
      });
    }
  });

  // 2. Render Light Cones / Blooms (Screen blend mode)
  ctx.globalCompositeOperation = 'screen';
  lights.forEach((light) => {
    const grad = ctx.createRadialGradient(light.x, light.y, 0, light.x, light.y, light.radius);
    grad.addColorStop(0, light.color);
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(light.x, light.y, light.radius, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.restore();

  // 3. Render Atmospheric Overlays based on Lighting Mode
  ctx.save();
  if (lighting === 'night') {
    // Deep Midnight Blue Overlay with Ambient Contrast
    ctx.fillStyle = 'rgba(3, 7, 18, 0.58)';
    ctx.fillRect(0, 0, layout.width, layout.height);

    // Warm Window Light Casts
    ctx.globalCompositeOperation = 'lighter';
    lights.forEach((light) => {
      const grad = ctx.createRadialGradient(light.x, light.y, 0, light.x, light.y, light.radius * 1.3);
      grad.addColorStop(0, light.color);
      grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(light.x, light.y, light.radius * 1.3, 0, Math.PI * 2);
      ctx.fill();
    });
  } else if (lighting === 'cyberpunk') {
    // Neon Violet/Magenta & Teal Atmospheric Grade
    ctx.fillStyle = 'rgba(88, 28, 135, 0.22)';
    ctx.fillRect(0, 0, layout.width, layout.height);

    const grad = ctx.createLinearGradient(0, 0, layout.width, layout.height);
    grad.addColorStop(0, 'rgba(6, 182, 212, 0.12)');
    grad.addColorStop(0.5, 'rgba(217, 70, 239, 0.08)');
    grad.addColorStop(1, 'rgba(59, 130, 246, 0.12)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, layout.width, layout.height);
  } else {
    // Crisp Modern Architectural Day Soft Grade
    ctx.fillStyle = 'rgba(255, 255, 255, 0.015)';
    ctx.fillRect(0, 0, layout.width, layout.height);
  }
  ctx.restore();
}
