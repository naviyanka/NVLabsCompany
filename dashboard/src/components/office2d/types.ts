export type Direction = 'down' | 'up' | 'left' | 'right';

export type AgentState2D =
  | 'idle_roaming'
  | 'walking_to_desk'
  | 'working_at_desk'
  | 'walking_to_breakroom'
  | 'at_breakroom'
  | 'in_meeting'
  | 'inspecting_server'
  | 'walking_to_poi'
  | 'offline_sleeping';

export interface ThoughtBubble {
  text: string;
  emoji?: string;
  expiresAt: number; // timestamp ms
  type?: 'thought' | 'speech' | 'action' | 'status';
}

export interface SpriteCustomization {
  hairColor: string;
  hairStyle: 'short' | 'spiky' | 'long' | 'bob' | 'messy' | 'ponytail' | 'curly';
  skinTone: string;
  outfitColor: string;
  pantsColor: string;
  accessory?: 'glasses' | 'headphones' | 'hoodie' | 'labcoat' | 'visor' | 'armor' | 'headband' | 'none';
  accessoryColor?: string;
  auraColor?: string;
}

export interface Agent2D {
  id: string;
  name: string;
  role: string;
  model: string;
  zoneId: string;
  deskId: string;
  status: 'working' | 'idle' | 'review' | 'offline';
  state2D: AgentState2D;
  
  // Position & Pathfinding in 2D World Space
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  finalTargetX?: number;
  finalTargetY?: number;
  stuckFrames?: number;
  path: { x: number; y: number }[];
  facing: Direction;
  walkFrame: number;
  isMoving: boolean;
  speed: number;
  
  // Smooth Tweening, Acceleration & Heading Interpolation
  currentSpeed?: number;
  distanceTraveled?: number;
  headingX?: number;
  headingY?: number;
  prevFootstepDistance?: number;
  
  // Behavior Timers
  nextRoamDecisionTime: number;
  currentActionDuration: number;
  actionStartTime: number;
  
  // Task & Stats
  currentTask: string;
  taskProgress: number;
  capabilities: string[];
  cpu: number;
  memory: number;
  tokensUsed: number;
  energy: number; // 0 - 100
  sparklineData: number[];
  
  // Visuals
  sprite: SpriteCustomization;
  bubble: ThoughtBubble | null;
}

export interface Desk2D {
  id: string;
  name: string;
  zoneId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  seatX: number;
  seatY: number;
  facing: Direction;
  hasComputer: boolean;
  screenColor: string;
  assignedAgentId?: string;
  // Enhanced 3D Pixel Art Properties
  deskType?: 'developer' | 'designer' | 'manager' | 'systems' | 'data' | 'qa' | 'research' | 'ops' | 'support' | 'architect' | 'standard';
  monitorSetup?: 'single' | 'dual' | 'triple' | 'curved' | 'vertical_dual' | 'laptop_monitor' | 'executive';
  accessories?: ('coffee' | 'espresso' | 'headphones' | 'lamp' | 'tablet' | 'notes' | 'sticky_notes' | 'plant' | 'cables' | 'notebook' | 'phone' | 'can' | 'laptop' | 'papers' | 'energy_drink' | 'water_bottle' | 'keyboard' | 'mouse' | 'cert_plaque' | 'pen_holder')[];
  woodTone?: 'walnut' | 'oak' | 'carbon' | 'light_birch' | 'dark_mahogany';
  lampOn?: boolean;
}

export interface EnvironmentalProp2D {
  id: string;
  type: 'printer' | 'filing_cabinet' | 'wall_clock' | 'poster' | 'notice_board' | 'trash_bin' | 'recycle_bin' | 'fire_extinguisher' | 'water_cooler' | 'wall_sconce' | 'floor_lamp' | 'storage_box' | 'bonsai' | 'exit_sign' | 'banner' | 'whiteboard_small';
  x: number;
  y: number;
  width: number;
  height: number;
  color?: string;
  variant?: string;
  label?: string;
  glowColor?: string;
}

export interface Room2D {
  id: string;
  name: string;
  type: 'dev' | 'meeting' | 'breakroom' | 'server' | 'executive' | 'zen_garden' | 'analytics' | 'qa';
  x: number;
  y: number;
  width: number;
  height: number;
  floorColor: string;
  floorPattern: 'grid' | 'wood' | 'tiles' | 'carpet' | 'dark_slate' | 'zen_stone' | 'checkered';
  wallColor: string;
  accentColor: string;
  label: string;
}

export interface InteractivePOI {
  id: string;
  name: string;
  type: 'coffee_machine' | 'water_cooler' | 'arcade' | 'vending_machine' | 'whiteboard' | 'server_rack' | 'bookshelf' | 'fountain' | 'plant' | 'snack_bar';
  x: number;
  y: number;
  width: number;
  height: number;
  interactX: number;
  interactY: number;
  interactionName: string;
  icon: string;
  description: string;
}

export interface Furniture2D {
  id: string;
  type: 'chair' | 'table' | 'sofa' | 'plant' | 'server_rack' | 'bookshelf' | 'arcade' | 'coffee_bar' | 'cooler' | 'fountain' | 'whiteboard' | 'rug' | 'vending';
  x: number;
  y: number;
  width: number;
  height: number;
  color?: string;
  rotation?: number;
}

export interface WallSegment2D {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  thickness?: number;
  type?: 'solid' | 'glass' | 'exterior';
  color?: string;
  doorwayIds?: string[];
}

export interface Doorway2D {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  roomFrom?: string;
  roomTo?: string;
  label?: string;
}

export interface WallRect2D {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  type?: 'solid' | 'glass' | 'exterior' | 'partition';
  label?: string;
}

export interface Office2DLayout {
  width: number;
  height: number;
  rooms: Room2D[];
  desks: Desk2D[];
  pois: InteractivePOI[];
  furniture: Furniture2D[];
  environmentalProps?: EnvironmentalProp2D[];
  walls: WallRect2D[];
  doorways: Doorway2D[];
  roamWaypoints: { x: number; y: number; name?: string; zoneId?: string }[];
}

export type LightingMode = 'day' | 'cyberpunk' | 'night';
export type SimSpeed = 0 | 1 | 2 | 4;
