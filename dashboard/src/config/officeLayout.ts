import type { OfficeRoom } from '@/types/office';

/** Color palette per department/room type */
export const roomColors = {
  ceo: { bg: '#eef2ff', border: '#6366f1' },
  engineering: { bg: '#eff6ff', border: '#3b82f6' },
  marketing: { bg: '#faf5ff', border: '#a855f7' },
  qa: { bg: '#fffbeb', border: '#f59e0b' },
  operations: { bg: '#ecfdf5', border: '#10b981' },
  common: { bg: '#f9fafb', border: '#9ca3af' },
  meeting: { bg: '#fff1f2', border: '#fb7185' },
  server: { bg: '#f1f5f9', border: '#64748b' },
} as const;

/** Agent status ring colors (matches AgentStatus union: 'active'|'idle'|'busy'|'offline'|'error') */
export const statusColors: Record<string, string> = {
  active: '#10b981',
  busy: '#10b981',
  idle: '#3b82f6',
  error: '#f43f5e',
  offline: '#9ca3af',
};

/** Default floor plan - rooms positioned according to the office layout spec */
export const defaultRooms: OfficeRoom[] = [
  {
    id: 'ceo-office',
    name: 'CEO Office',
    type: 'office',
    x: 60,
    y: 20,
    width: 180,
    height: 120,
    color: roomColors.ceo.bg,
    borderColor: roomColors.ceo.border,
    departmentId: 'executive',
  },
  {
    id: 'meeting-room-1',
    name: 'Meeting Room 1',
    type: 'meeting_room',
    x: 280,
    y: 20,
    width: 220,
    height: 120,
    color: roomColors.meeting.bg,
    borderColor: roomColors.meeting.border,
  },
  {
    id: 'marketing',
    name: 'Marketing',
    type: 'office',
    x: 540,
    y: 20,
    width: 180,
    height: 120,
    color: roomColors.marketing.bg,
    borderColor: roomColors.marketing.border,
    departmentId: 'marketing',
  },
  {
    id: 'engineering',
    name: 'Engineering',
    type: 'lab',
    x: 60,
    y: 180,
    width: 280,
    height: 200,
    color: roomColors.engineering.bg,
    borderColor: roomColors.engineering.border,
    departmentId: 'engineering',
  },
  {
    id: 'meeting-room-2',
    name: 'Meeting Room 2',
    type: 'meeting_room',
    x: 380,
    y: 180,
    width: 220,
    height: 120,
    color: roomColors.meeting.bg,
    borderColor: roomColors.meeting.border,
  },
  {
    id: 'operations',
    name: 'Operations',
    type: 'office',
    x: 380,
    y: 340,
    width: 240,
    height: 140,
    color: roomColors.operations.bg,
    borderColor: roomColors.operations.border,
    departmentId: 'operations',
  },
  {
    id: 'qa',
    name: 'QA',
    type: 'lab',
    x: 60,
    y: 420,
    width: 180,
    height: 140,
    color: roomColors.qa.bg,
    borderColor: roomColors.qa.border,
    departmentId: 'qa',
  },
  {
    id: 'common-area',
    name: 'Common Area',
    type: 'common_area',
    x: 280,
    y: 520,
    width: 340,
    height: 100,
    color: roomColors.common.bg,
    borderColor: roomColors.common.border,
  },
  {
    id: 'server-room',
    name: 'Server Room',
    type: 'server_room',
    x: 60,
    y: 600,
    width: 180,
    height: 100,
    color: roomColors.server.bg,
    borderColor: roomColors.server.border,
    departmentId: 'infrastructure',
  },
];

/** Layout presets for different team sizes */
export const layoutPresets = {
  small: {
    name: 'Small Team',
    maxAgents: 10,
    canvasWidth: 780,
    canvasHeight: 500,
    rooms: defaultRooms.slice(0, 5),
  },
  medium: {
    name: 'Medium Team',
    maxAgents: 30,
    canvasWidth: 780,
    canvasHeight: 740,
    rooms: defaultRooms,
  },
  large: {
    name: 'Large Team',
    maxAgents: 50,
    canvasWidth: 780,
    canvasHeight: 740,
    rooms: defaultRooms,
  },
} as const;

/** Default canvas dimensions */
export const CANVAS_WIDTH = 780;
export const CANVAS_HEIGHT = 740;

/** Grid size for spatial reference */
export const GRID_SIZE = 20;

/** Department to room mapping (maps department keywords to room IDs) */
export const departmentRoomMap: Record<string, string> = {
  executive: 'ceo-office',
  ceo: 'ceo-office',
  cto: 'engineering',
  engineering: 'engineering',
  development: 'engineering',
  marketing: 'marketing',
  sales: 'marketing',
  qa: 'qa',
  quality: 'qa',
  testing: 'qa',
  operations: 'operations',
  ops: 'operations',
  infrastructure: 'server-room',
  devops: 'server-room',
};
