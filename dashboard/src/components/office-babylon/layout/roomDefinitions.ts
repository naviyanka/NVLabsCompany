/**
 * Room layout definitions — scaled to human proportions.
 * Building: 60 wide (X: -30 to +30), 40 deep (Z: -20 to +20).
 * 1 unit ≈ 1 meter. Z+20 = front (gate), Z-20 = back.
 */

export interface RoomDefinition {
  id: string;
  name: string;
  type: 'team' | 'manager' | 'meeting' | 'discussion' | 'rest' | 'server' | 'storage' | 'utility' | 'reception' | 'waiting' | 'workspace' | 'hallway';
  x: number;
  z: number;
  width: number;
  depth: number;
  wallHeight: number;
  color: string;
  access: 'public' | 'team' | 'manager' | 'restricted';
  doors: ('north' | 'south' | 'east' | 'west')[];
}

export const WALL_HEIGHT = 3.2;

export const rooms: RoomDefinition[] = [
  // ─── Back row (Z ~ -15 to -20) ───
  {
    id: 'team-cabin-1',
    name: 'Team Cabin 1',
    type: 'team',
    x: -22, z: -16,
    width: 9, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['south'],
  },
  {
    id: 'team-cabin-2',
    name: 'Team Cabin 2',
    type: 'team',
    x: -12, z: -16,
    width: 9, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['south'],
  },
  {
    id: 'utility-room',
    name: 'Utility Room',
    type: 'utility',
    x: -2, z: -16,
    width: 7, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#06B6D4',
    access: 'restricted',
    doors: ['south'],
  },
  {
    id: 'team-cabin-3',
    name: 'Team Cabin 3',
    type: 'team',
    x: 9, z: -16,
    width: 9, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['south'],
  },
  {
    id: 'team-cabin-4',
    name: 'Team Cabin 4',
    type: 'team',
    x: 21, z: -16,
    width: 9, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['south'],
  },

  // ─── Left column ───
  {
    id: 'server-room',
    name: 'Server Room',
    type: 'server',
    x: -25, z: -7,
    width: 8, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#06B6D4',
    access: 'restricted',
    doors: ['east'],
  },
  {
    id: 'storage-room',
    name: 'Storage Room',
    type: 'storage',
    x: -25, z: 0,
    width: 8, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#64748B',
    access: 'restricted',
    doors: ['east'],
  },
  {
    id: 'team-cabin-5',
    name: 'Team Cabin 5',
    type: 'team',
    x: -25, z: 7,
    width: 8, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['east'],
  },

  // ─── Right column ───
  {
    id: 'manager-cabin',
    name: 'Manager Cabin',
    type: 'manager',
    x: 25, z: -7,
    width: 8, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#A78BFA',
    access: 'manager',
    doors: ['west'],
  },
  {
    id: 'rest-area',
    name: 'Rest Area',
    type: 'rest',
    x: 25, z: 0,
    width: 8, depth: 6,
    wallHeight: WALL_HEIGHT,
    color: '#F97316',
    access: 'public',
    doors: ['west'],
  },
  {
    id: 'team-cabin-6',
    name: 'Team Cabin 6',
    type: 'team',
    x: 25, z: 7,
    width: 8, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'team',
    doors: ['west'],
  },

  // ─── Center rooms ───
  {
    id: 'open-workspace',
    name: 'Open Workspace',
    type: 'workspace',
    x: 0, z: -8,
    width: 25, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#22C55E',
    access: 'public',
    doors: ['south', 'north'],
  },
  {
    id: 'discussion-room-1',
    name: 'Discussion Room 1',
    type: 'discussion',
    x: -7, z: -1,
    width: 8, depth: 5,
    wallHeight: WALL_HEIGHT,
    color: '#EC4899',
    access: 'public',
    doors: ['south'],
  },
  {
    id: 'discussion-room-2',
    name: 'Discussion Room 2',
    type: 'discussion',
    x: 7, z: -1,
    width: 8, depth: 5,
    wallHeight: WALL_HEIGHT,
    color: '#EC4899',
    access: 'public',
    doors: ['south'],
  },
  {
    id: 'meeting-hall',
    name: 'Meeting Hall',
    type: 'meeting',
    x: 0, z: 6,
    width: 18, depth: 8,
    wallHeight: WALL_HEIGHT,
    color: '#8B5CF6',
    access: 'public',
    doors: ['north', 'south'],
  },

  // ─── Front row (Z ~ +12 to +19) ───
  {
    id: 'reception',
    name: 'Reception',
    type: 'reception',
    x: -10, z: 16,
    width: 15, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#3B82F6',
    access: 'public',
    doors: ['south', 'north'],
  },
  {
    id: 'waiting-area',
    name: 'Waiting Area',
    type: 'waiting',
    x: 10, z: 16,
    width: 15, depth: 7,
    wallHeight: WALL_HEIGHT,
    color: '#EAB308',
    access: 'public',
    doors: ['south', 'north'],
  },
];
