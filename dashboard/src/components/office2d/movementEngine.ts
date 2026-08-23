import type { Agent2D, Direction, SimSpeed } from './types';
import { ROAM_WAYPOINTS, DESKS_2D, INTERACTIVE_POIS } from './office2DMap';
import { findPath, findNearestWalkable, isPointBlocked } from './pathfinding';
import { retroAudio } from '@/utils/retroAudio';

const IDLE_THOUGHTS = [
  { text: 'Checking memory cache & Redis...', emoji: '⚡' },
  { text: 'Grabbing fresh dark roast espresso ☕', emoji: '☕' },
  { text: 'Refactoring AST parser in Rust...', emoji: '🦀' },
  { text: 'Stretching after 500k token stream', emoji: '🧘' },
  { text: 'Arcade high score: 98,420! 🕹️', emoji: '🕹️' },
  { text: 'Reviewing PR #204 for auth bugs...', emoji: '🔍' },
  { text: 'Looking for next task in backlog...', emoji: '📋' },
  { text: 'Pondering prompt caching efficiency...', emoji: '💡' },
  { text: 'Hydrating at the water cooler 💧', emoji: '💧' },
  { text: 'Meditating near the bamboo fountain...', emoji: '🎋' },
  { text: 'Browsing distributed systems papers...', emoji: '📚' },
  { text: 'Checking GPU temperature on H100s...', emoji: '🔥' },
];

/**
 * Updates agents' positions along calculated A* obstacle-free paths with smooth tweening,
 * acceleration/deceleration easing, continuous multi-segment transitions, and autonomous roaming
 */
export function updateAgentsSimulation(
  agents: Agent2D[],
  deltaMs: number,
  simSpeed: SimSpeed
): Agent2D[] {
  if (simSpeed === 0) return agents; // Paused

  const speedMultiplier = simSpeed;
  const now = Date.now();
  const dtFactor = Math.min(deltaMs / 16.667, 3.0); // normalized to 60fps

  return agents.map((agent) => {
    let updated = { ...agent };

    // 1. Continuous Sub-Pixel Tweening along multi-segment A* path
    const hasActiveMovement =
      updated.isMoving ||
      (updated.path && updated.path.length > 0) ||
      (Math.hypot(updated.targetX - updated.x, updated.targetY - updated.y) > 0.5);

    if (hasActiveMovement && updated.isMoving) {
      // Calculate total remaining distance across all remaining waypoints for smooth deceleration
      const distToCurrent = Math.hypot(updated.targetX - updated.x, updated.targetY - updated.y);
      let totalRemainingDist = distToCurrent;
      if (updated.path && updated.path.length > 0) {
        let prevPt = { x: updated.targetX, y: updated.targetY };
        for (const wp of updated.path) {
          totalRemainingDist += Math.hypot(wp.x - prevPt.x, wp.y - prevPt.y);
          prevPt = wp;
        }
      }

      // Smooth Easing: Ease-In (acceleration) and Ease-Out (gentle deceleration near destination)
      const baseMaxSpeed = updated.speed * speedMultiplier;
      
      // Deceleration curve when nearing final destination (within 22px)
      const decelFactor = totalRemainingDist < 22 
        ? Math.max(0.35, Math.sin((totalRemainingDist / 22) * (Math.PI / 2))) 
        : 1.0;
      const targetSpeed = baseMaxSpeed * decelFactor;

      // Acceleration rate
      const accelRate = 0.18 * speedMultiplier * dtFactor;
      const curSpeed = updated.currentSpeed ?? (updated.isMoving ? baseMaxSpeed * 0.4 : 0);
      updated.currentSpeed = curSpeed + (targetSpeed - curSpeed) * Math.min(1, accelRate);

      // Distance the agent should move in this frame
      let remainingDistToMove = Math.max(0.02, updated.currentSpeed) * dtFactor;

      // Multi-segment traversal loop: seamlessly cross waypoints without pausing or snapping
      let maxSegmentSteps = 8;
      while (remainingDistToMove > 0.0001 && maxSegmentSteps-- > 0) {
        const dx = updated.targetX - updated.x;
        const dy = updated.targetY - updated.y;
        const segDist = Math.hypot(dx, dy);

        if (segDist <= 0.001) {
          // Already on current waypoint
          if (updated.path && updated.path.length > 0) {
            const nextWp = updated.path[0]!;
            updated.targetX = nextWp.x;
            updated.targetY = nextWp.y;
            updated.path = updated.path.slice(1);
            continue;
          } else {
            // Reached final destination
            updated.isMoving = false;
            updated.currentSpeed = 0;
            remainingDistToMove = 0;
            break;
          }
        }

        // Update continuous heading vector for smooth turning
        const unitX = dx / segDist;
        const unitY = dy / segDist;
        const headingSmooth = Math.min(1, 0.28 * dtFactor);
        updated.headingX = (updated.headingX ?? unitX) + (unitX - (updated.headingX ?? unitX)) * headingSmooth;
        updated.headingY = (updated.headingY ?? unitY) + (unitY - (updated.headingY ?? unitY)) * headingSmooth;

        // Facing direction with hysteresis to prevent rapid flickering
        const hx = updated.headingX;
        const hy = updated.headingY;
        if (Math.abs(hx) > Math.abs(hy) * 1.15) {
          updated.facing = hx > 0 ? 'right' : 'left';
        } else if (Math.abs(hy) > Math.abs(hx) * 1.15) {
          updated.facing = hy > 0 ? 'down' : 'up';
        }

        if (segDist <= remainingDistToMove) {
          // Arrives at waypoint during this step: smoothly transfer leftover distance to next segment
          const oldX = updated.x;
          const oldY = updated.y;
          updated.x = updated.targetX;
          updated.y = updated.targetY;
          const distCovered = Math.hypot(updated.x - oldX, updated.y - oldY);
          updated.distanceTraveled = (updated.distanceTraveled || 0) + distCovered;
          remainingDistToMove -= segDist;

          if (updated.path && updated.path.length > 0) {
            const nextWp = updated.path[0]!;
            updated.targetX = nextWp.x;
            updated.targetY = nextWp.y;
            updated.path = updated.path.slice(1);
            // Continues next segment in the while loop without snapping!
          } else {
            // Reached final destination!
            updated.isMoving = false;
            updated.currentSpeed = 0;
            remainingDistToMove = 0;
            updated.stuckFrames = 0;

            if (updated.state2D === 'walking_to_desk') {
              updated.state2D = 'working_at_desk';
              const desk = DESKS_2D.find((d) => d.id === updated.deskId);
              if (desk) {
                updated.facing = desk.facing;
              }
            } else if (updated.state2D === 'walking_to_breakroom') {
              updated.state2D = 'at_breakroom';
            } else if (updated.state2D === 'walking_to_poi') {
              updated.state2D = 'idle_roaming';
            }
            break;
          }
        } else {
          // Partial step along current segment
          const moveRatio = remainingDistToMove / segDist;
          const moveX = dx * moveRatio;
          const moveY = dy * moveRatio;

          let moved = false;
          if (!isPointBlocked(updated.x + moveX, updated.y + moveY, 3.0)) {
            updated.x += moveX;
            updated.y += moveY;
            moved = true;
          } else {
            // Smooth wall sliding
            if (Math.abs(moveX) > 0.01 && !isPointBlocked(updated.x + moveX, updated.y, 3.0)) {
              updated.x += moveX;
              moved = true;
            } else if (Math.abs(moveY) > 0.01 && !isPointBlocked(updated.x, updated.y + moveY, 3.0)) {
              updated.y += moveY;
              moved = true;
            } else {
              // Smooth corner deflection
              const cos45 = 0.7071;
              const sin45 = 0.7071;
              const def1X = moveX * cos45 - moveY * sin45;
              const def1Y = moveX * sin45 + moveY * cos45;
              const def2X = moveX * cos45 + moveY * sin45;
              const def2Y = -moveX * sin45 + moveY * cos45;

              if (!isPointBlocked(updated.x + def1X, updated.y + def1Y, 2.5)) {
                updated.x += def1X;
                updated.y += def1Y;
                moved = true;
              } else if (!isPointBlocked(updated.x + def2X, updated.y + def2Y, 2.5)) {
                updated.x += def2X;
                updated.y += def2Y;
                moved = true;
              }
            }
          }

          if (moved) {
            updated.stuckFrames = 0;
            updated.distanceTraveled = (updated.distanceTraveled || 0) + remainingDistToMove;
          } else {
            updated.stuckFrames = (updated.stuckFrames || 0) + 1;
            // Auto recovery if stuck
            if (updated.stuckFrames >= 4 && updated.path && updated.path.length > 0) {
              const nextWp = updated.path[0]!;
              updated.targetX = nextWp.x;
              updated.targetY = nextWp.y;
              updated.path = updated.path.slice(1);
              updated.stuckFrames = 0;
            } else if (updated.stuckFrames >= 8) {
              const freePos = findNearestWalkable(updated.x, updated.y);
              updated.x = freePos.x;
              updated.y = freePos.y;
            }
            if (updated.stuckFrames >= 14) {
              const finalX = updated.finalTargetX ?? updated.targetX;
              const finalY = updated.finalTargetY ?? updated.targetY;
              const freshPath = findPath(updated.x, updated.y, finalX, finalY);
              if (freshPath && freshPath.length > 0) {
                const firstWp = freshPath[0]!;
                updated.targetX = firstWp.x;
                updated.targetY = firstWp.y;
                updated.path = freshPath.slice(1);
              }
              updated.stuckFrames = 0;
            }
          }

          remainingDistToMove = 0;
        }
      }

      // Gait & Footstep synchronization driven by physical distance traversed
      const stepCycleDist = 9; // pixels per footstep cycle
      updated.walkFrame = Math.floor(((updated.distanceTraveled || 0) / stepCycleDist) % 4);

      // Play soft footstep sound at rhythmic distance intervals
      const curFootDist = updated.distanceTraveled || 0;
      const prevFootDist = updated.prevFootstepDistance ?? 0;
      if (curFootDist - prevFootDist >= 20) {
        updated.prevFootstepDistance = curFootDist;
        if (Math.random() < 0.6) {
          retroAudio.playFootstep();
        }
      }
    } else {
      updated.currentSpeed = 0;
    }

    // 2. Typing sound / work progress when working at desk
    if (updated.state2D === 'working_at_desk' && updated.status === 'working') {
      if (Math.random() < 0.04 * speedMultiplier) {
        retroAudio.playKeyboardClack();
      }
      // Advance task progress smoothly
      if (updated.taskProgress < 100) {
        updated.taskProgress = Math.min(
          100,
          updated.taskProgress + 0.02 * speedMultiplier * (deltaMs / 16.6)
        );
      }
    }

    // 3. Autonomous Roaming Decisions for Idle Agents (no task or idle status)
    const isIdle = updated.status === 'idle' || updated.state2D === 'idle_roaming';
    if (isIdle && now >= updated.nextRoamDecisionTime && !updated.isMoving) {
      // Time to make a new roaming decision!
      const roll = Math.random();

      if (roll < 0.35 && INTERACTIVE_POIS.length > 0) {
        // Walk to a point of interest (Coffee, Arcade, Water cooler, Zen fountain, Whiteboard)
        const randomPoi = INTERACTIVE_POIS[Math.floor(Math.random() * INTERACTIVE_POIS.length)] || INTERACTIVE_POIS[0];
        if (randomPoi) {
          updated = navigateToPoint(updated, randomPoi.interactX, randomPoi.interactY);
          updated.state2D = 'idle_roaming';
        }

        // Trigger contextual thought
        const thought = IDLE_THOUGHTS[Math.floor(Math.random() * IDLE_THOUGHTS.length)] || IDLE_THOUGHTS[0];
        if (thought) {
          updated.bubble = {
            text: thought.text,
            emoji: thought.emoji,
            expiresAt: now + 6000,
            type: 'thought',
          };
        }
      } else if (roll < 0.75 && ROAM_WAYPOINTS.length > 0) {
        // Wander to a random office waypoint (within corridor network)
        const randomWp = ROAM_WAYPOINTS[Math.floor(Math.random() * ROAM_WAYPOINTS.length)] || ROAM_WAYPOINTS[0];
        if (randomWp) {
          updated = navigateToPoint(
            updated,
            randomWp.x + (Math.random() * 16 - 8),
            randomWp.y + (Math.random() * 16 - 8)
          );
          updated.state2D = 'idle_roaming';
        }
      } else {
        // Look around
        const facings: Direction[] = ['down', 'up', 'left', 'right'];
        const chosenFacing = facings[Math.floor(Math.random() * facings.length)] || 'down';
        updated.facing = chosenFacing;
      }

      // Schedule next roaming decision
      updated.nextRoamDecisionTime = now + (5000 + Math.random() * 7000) / speedMultiplier;
    }

    // 4. Bubble expiration cleanup
    if (updated.bubble && updated.bubble.expiresAt <= now) {
      updated.bubble = null;
    }

    return updated;
  });
}

/**
 * Navigates an agent directly to a specific desk's seat via A* pathfinding
 */
export function navigateToDesk(
  agent: Agent2D,
  targetDeskId: string,
  customMessage?: string
): Agent2D {
  const desk = DESKS_2D.find((d) => d.id === targetDeskId) || DESKS_2D[0] || { seatX: 200, seatY: 100 };
  const routed = navigateToPoint(agent, desk.seatX, desk.seatY);
  const isOwnDesk = agent.deskId === targetDeskId;

  return {
    ...routed,
    status: 'working',
    state2D: 'walking_to_desk',
    bubble: {
      text: customMessage || (isOwnDesk ? 'Returning to workstation 💻' : `Heading to ${targetDeskId} to collaborate 🤝`),
      emoji: isOwnDesk ? '💻' : '🤝',
      expiresAt: Date.now() + 5000,
      type: 'action',
    },
  };
}

/**
 * Navigates an agent from their current location to a colleague's desk for pair programming
 */
export function navigateAgentBetweenDesks(
  agent: Agent2D,
  colleagueAgent: Agent2D
): Agent2D {
  const targetDesk = DESKS_2D.find((d) => d.id === colleagueAgent.deskId);
  if (!targetDesk) {
    return navigateToPoint(agent, colleagueAgent.x, colleagueAgent.y);
  }

  return navigateToDesk(
    agent,
    targetDesk.id,
    `Pair programming with ${colleagueAgent.name} 👥`
  );
}

/**
 * Real A* Pathfinding Navigation around Walls, Obstacles, and Doorways with smooth path initialization
 */
export function navigateToPoint(agent: Agent2D, targetX: number, targetY: number): Agent2D {
  // 1. Ensure start position is walkable without snapping if already in clear territory
  const isStartBlocked = isPointBlocked(agent.x, agent.y, 2.5);
  const validStart = isStartBlocked ? findNearestWalkable(agent.x, agent.y) : { x: agent.x, y: agent.y };

  // 2. Ensure target is in walkable space (if clicked inside a wall, pick nearest free spot)
  const validTarget = findNearestWalkable(targetX, targetY);

  // 3. Compute full obstacle-avoiding A* path
  const path = findPath(validStart.x, validStart.y, validTarget.x, validTarget.y);

  if (!path || path.length === 0) {
    return {
      ...agent,
      x: validStart.x,
      y: validStart.y,
      targetX: validTarget.x,
      targetY: validTarget.y,
      finalTargetX: validTarget.x,
      finalTargetY: validTarget.y,
      path: [],
      isMoving: false,
      stuckFrames: 0,
      currentSpeed: 0,
    };
  }

  const firstTarget = path[0] || { x: validTarget.x, y: validTarget.y };

  return {
    ...agent,
    x: validStart.x,
    y: validStart.y,
    targetX: firstTarget.x,
    targetY: firstTarget.y,
    finalTargetX: validTarget.x,
    finalTargetY: validTarget.y,
    path: path.slice(1),
    isMoving: true,
    stuckFrames: 0,
    currentSpeed: agent.currentSpeed ?? (agent.speed * 0.3),
  };
}

/**
 * Sends all agents to the War Room for an All-Hands Meeting
 */
export function triggerAllHandsMeeting(agents: Agent2D[]): Agent2D[] {
  retroAudio.playChime();
  const meetingSeats = [
    { x: 550, y: 95, facing: 'down' as Direction },
    { x: 600, y: 95, facing: 'down' as Direction },
    { x: 650, y: 95, facing: 'down' as Direction },
    { x: 550, y: 205, facing: 'up' as Direction },
    { x: 600, y: 205, facing: 'up' as Direction },
    { x: 650, y: 205, facing: 'up' as Direction },
    { x: 495, y: 150, facing: 'right' as Direction },
    { x: 705, y: 150, facing: 'left' as Direction },
    { x: 500, y: 100, facing: 'down' as Direction },
    { x: 720, y: 100, facing: 'down' as Direction },
    { x: 490, y: 200, facing: 'right' as Direction },
    { x: 710, y: 200, facing: 'left' as Direction },
    { x: 600, y: 230, facing: 'up' as Direction },
    { x: 600, y: 70, facing: 'down' as Direction },
    { x: 650, y: 70, facing: 'down' as Direction },
  ];

  return agents.map((agent, idx) => {
    const seat = meetingSeats[idx % meetingSeats.length] || { x: 600, y: 150, facing: 'down' as Direction };
    const routed = navigateToPoint(agent, seat.x, seat.y);
    return {
      ...routed,
      state2D: 'in_meeting',
      bubble: {
        text: idx === 0 ? 'All-Hands Sync started! Reviewing goals...' : 'Joining standup...',
        emoji: '📢',
        expiresAt: Date.now() + 8000,
        type: 'speech',
      },
    };
  });
}

/**
 * Sends everyone to the Breakroom for Coffee / Arcade Break
 */
export function triggerCoffeeBreak(agents: Agent2D[]): Agent2D[] {
  retroAudio.playCoffeeBrew();
  const breakSpots = [
    { x: 1262, y: 120 }, // Coffee interact spot
    { x: 1383, y: 135 }, // Arcade interact spot
    { x: 1260, y: 235 }, // Cooler
    { x: 1360, y: 260 }, // Vending
    { x: 1250, y: 340 }, // Lounge floor
    { x: 1290, y: 340 }, // Lounge floor
    { x: 1300, y: 350 }, // Lounge floor
    { x: 1240, y: 350 },
    { x: 1360, y: 350 },
    { x: 1260, y: 180 },
    { x: 1320, y: 180 },
    { x: 1175, y: 705 }, // Zen fountain spillover
    { x: 1050, y: 550 },
    { x: 1320, y: 580 },
    { x: 1280, y: 800 },
  ];

  return agents.map((agent, idx) => {
    const spot = breakSpots[idx % breakSpots.length] || { x: 1262, y: 120 };
    const routed = navigateToPoint(agent, spot.x, spot.y);
    return {
      ...routed,
      state2D: 'at_breakroom',
      status: 'idle',
      bubble: {
        text: idx % 2 === 0 ? 'Coffee break time! ☕' : 'Testing retro arcade! 🕹️',
        emoji: idx % 2 === 0 ? '☕' : '🕹️',
        expiresAt: Date.now() + 7000,
        type: 'action',
      },
    };
  });
}

/**
 * Sends everyone back to their designated workstations for Sprint Rush
 */
export function triggerSprintRush(agents: Agent2D[]): Agent2D[] {
  retroAudio.playChime();
  return agents.map((agent) => {
    const desk = DESKS_2D.find((d) => d.id === agent.deskId) || DESKS_2D[0] || { seatX: 200, seatY: 100 };
    const routed = navigateToPoint(agent, desk.seatX, desk.seatY);
    return {
      ...routed,
      speed: 2.4, // Speed boost
      status: 'working',
      state2D: 'walking_to_desk',
      bubble: {
        text: 'Sprint rush! Coding at max velocity ⚡',
        emoji: '🚀',
        expiresAt: Date.now() + 6000,
        type: 'action',
      },
    };
  });
}

/**
 * Sets all agents to free roam mode
 */
export function triggerFreeRoam(agents: Agent2D[]): Agent2D[] {
  retroAudio.playChime();
  return agents.map((agent) => {
    const randomWp = ROAM_WAYPOINTS[Math.floor(Math.random() * ROAM_WAYPOINTS.length)] || ROAM_WAYPOINTS[0] || { x: 750, y: 475 };
    const routed = navigateToPoint(agent, randomWp.x, randomWp.y);
    return {
      ...routed,
      status: 'idle',
      state2D: 'idle_roaming',
      bubble: {
        text: 'Free roam enabled. Exploring office zones...',
        emoji: '🚶',
        expiresAt: Date.now() + 5000,
        type: 'thought',
      },
    };
  });
}

