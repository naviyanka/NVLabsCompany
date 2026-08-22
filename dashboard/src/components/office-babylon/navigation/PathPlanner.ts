import { Vector3 } from '@babylonjs/core';
import { rooms, type RoomDefinition } from '../layout/roomDefinitions';

/**
 * Simple grid-based pathfinding for agents.
 * Uses hallway waypoints to route between rooms without going through walls.
 * 
 * Architecture: rooms connect through a central hallway graph.
 * Agents walk: room center → room door → nearest hallway node → destination hallway node → destination door → room center.
 */

interface WaypointNode {
  id: string;
  position: Vector3;
  connections: string[];
}

// Hallway waypoint graph — nodes at key corridor intersections
const HALLWAY_NODES: WaypointNode[] = [
  // Main horizontal hallway (Z = -12, connects back rooms to center)
  { id: 'h_back_l', position: new Vector3(-22, 0, -12), connections: ['h_back_cl', 'h_left_top'] },
  { id: 'h_back_cl', position: new Vector3(-12, 0, -12), connections: ['h_back_l', 'h_back_c'] },
  { id: 'h_back_c', position: new Vector3(0, 0, -12), connections: ['h_back_cl', 'h_back_cr', 'h_center'] },
  { id: 'h_back_cr', position: new Vector3(12, 0, -12), connections: ['h_back_c', 'h_back_r'] },
  { id: 'h_back_r', position: new Vector3(22, 0, -12), connections: ['h_back_cr', 'h_right_top'] },

  // Center vertical corridor
  { id: 'h_center', position: new Vector3(0, 0, -4), connections: ['h_back_c', 'h_mid'] },
  { id: 'h_mid', position: new Vector3(0, 0, 0), connections: ['h_center', 'h_front'] },
  { id: 'h_front', position: new Vector3(0, 0, 10), connections: ['h_mid', 'h_gate'] },
  { id: 'h_gate', position: new Vector3(0, 0, 16), connections: ['h_front'] },

  // Left vertical corridor (X = -20)
  { id: 'h_left_top', position: new Vector3(-20, 0, -12), connections: ['h_back_l', 'h_left_mid'] },
  { id: 'h_left_mid', position: new Vector3(-20, 0, 0), connections: ['h_left_top', 'h_left_bot', 'h_mid'] },
  { id: 'h_left_bot', position: new Vector3(-20, 0, 10), connections: ['h_left_mid', 'h_front'] },

  // Right vertical corridor (X = 20)
  { id: 'h_right_top', position: new Vector3(20, 0, -12), connections: ['h_back_r', 'h_right_mid'] },
  { id: 'h_right_mid', position: new Vector3(20, 0, 0), connections: ['h_right_top', 'h_right_bot', 'h_mid'] },
  { id: 'h_right_bot', position: new Vector3(20, 0, 10), connections: ['h_right_mid', 'h_front'] },
];

/**
 * Find the nearest hallway node to a given position.
 */
function findNearestNode(pos: Vector3): WaypointNode {
  let best = HALLWAY_NODES[0];
  let bestDist = Infinity;
  for (const node of HALLWAY_NODES) {
    const d = Vector3.Distance(pos, node.position);
    if (d < bestDist) {
      bestDist = d;
      best = node;
    }
  }
  return best;
}

/**
 * BFS shortest path through hallway graph.
 */
function bfsPath(startId: string, endId: string): string[] {
  const queue: string[][] = [[startId]];
  const visited = new Set<string>([startId]);

  while (queue.length > 0) {
    const path = queue.shift()!;
    const current = path[path.length - 1];

    if (current === endId) return path;

    const node = HALLWAY_NODES.find((n) => n.id === current);
    if (!node) continue;

    for (const neighbor of node.connections) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push([...path, neighbor]);
      }
    }
  }

  return [startId, endId]; // Fallback: direct
}

/**
 * Get door position for a room (where agent enters/exits hallway).
 */
function getRoomDoorPosition(room: RoomDefinition): Vector3 {
  const hw = room.width / 2;
  const hd = room.depth / 2;
  const dir = room.doors[0];

  switch (dir) {
    case 'south': return new Vector3(room.x, 0, room.z + hd + 0.5);
    case 'north': return new Vector3(room.x, 0, room.z - hd - 0.5);
    case 'east': return new Vector3(room.x + hw + 0.5, 0, room.z);
    case 'west': return new Vector3(room.x - hw - 0.5, 0, room.z);
    default: return new Vector3(room.x, 0, room.z + hd + 0.5);
  }
}

/**
 * Plan a path from one room to another.
 * Returns array of Vector3 waypoints the agent should walk through.
 */
export function planPath(fromRoomId: string, toRoomId: string): Vector3[] {
  const fromRoom = rooms.find((r) => r.id === fromRoomId);
  const toRoom = rooms.find((r) => r.id === toRoomId);
  if (!fromRoom || !toRoom) return [];
  if (fromRoomId === toRoomId) return [];

  const fromCenter = new Vector3(fromRoom.x, 0, fromRoom.z);
  const fromDoor = getRoomDoorPosition(fromRoom);
  const toDoor = getRoomDoorPosition(toRoom);
  const toCenter = new Vector3(toRoom.x, 0, toRoom.z);

  // Find nearest hallway nodes
  const startNode = findNearestNode(fromDoor);
  const endNode = findNearestNode(toDoor);

  // If same node (adjacent rooms), direct path
  if (startNode.id === endNode.id) {
    return [fromCenter, fromDoor, toDoor, toCenter];
  }

  // BFS through hallway graph
  const nodeIds = bfsPath(startNode.id, endNode.id);
  const hallwayPoints = nodeIds.map((id) => {
    const node = HALLWAY_NODES.find((n) => n.id === id)!;
    return node.position.clone();
  });

  return [fromCenter, fromDoor, ...hallwayPoints, toDoor, toCenter];
}

/**
 * Plan path from a position to a room.
 */
export function planPathToRoom(fromPos: Vector3, toRoomId: string): Vector3[] {
  const toRoom = rooms.find((r) => r.id === toRoomId);
  if (!toRoom) return [];

  const toDoor = getRoomDoorPosition(toRoom);
  const toCenter = new Vector3(toRoom.x, 0, toRoom.z);

  const startNode = findNearestNode(fromPos);
  const endNode = findNearestNode(toDoor);

  if (startNode.id === endNode.id) {
    return [fromPos, toDoor, toCenter];
  }

  const nodeIds = bfsPath(startNode.id, endNode.id);
  const hallwayPoints = nodeIds.map((id) => {
    const node = HALLWAY_NODES.find((n) => n.id === id)!;
    return node.position.clone();
  });

  return [fromPos, ...hallwayPoints, toDoor, toCenter];
}
