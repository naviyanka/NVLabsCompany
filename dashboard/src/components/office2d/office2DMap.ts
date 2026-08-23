import type {
  Office2DLayout,
  Room2D,
  Desk2D,
  InteractivePOI,
  Furniture2D,
  EnvironmentalProp2D,
  WallRect2D,
  Doorway2D,
} from './types';
import { initCollisionGrid } from './pathfinding';

/**
 * 2D OpenOffice Architectural Floor Plan & Wall Geometry
 * Dimensions: 1500 x 950 px world canvas
 */

export const ROOMS_2D: Room2D[] = [
  // 1. Executive / Architect Cabin (Top Left)
  {
    id: 'executive',
    name: 'Architect Strategy Suite',
    label: 'ARCHITECT',
    type: 'executive',
    x: 40,
    y: 40,
    width: 320,
    height: 236,
    floorColor: '#28201a',
    floorPattern: 'wood',
    wallColor: '#6e5644',
    accentColor: '#34D399',
  },
  // 2. Room / Sync - Conference & Meeting Hall (Top Center)
  {
    id: 'meeting',
    name: 'Conference & Sync Hall',
    label: 'ROOM / SYNC',
    type: 'meeting',
    x: 376,
    y: 40,
    width: 440,
    height: 236,
    floorColor: '#221b38',
    floorPattern: 'carpet',
    wallColor: '#584f78',
    accentColor: '#A855F7',
  },
  // 3. AI Cluster Racks - Supercomputer & Server Vault (Top Right)
  {
    id: 'server',
    name: 'AI Cluster Server Vault',
    label: 'AI CLUSTER RACKS',
    type: 'server',
    x: 832,
    y: 40,
    width: 348,
    height: 236,
    floorColor: '#12202e',
    floorPattern: 'dark_slate',
    wallColor: '#2b6385',
    accentColor: '#06B6D4',
  },
  // 4. Coffee & Retro Arcade - Breakroom Lounge (Top Far Right)
  {
    id: 'breakroom',
    name: 'Coffee & Retro Arcade',
    label: 'COFFEE & RETRO ARCADE',
    type: 'breakroom',
    x: 1196,
    y: 40,
    width: 264,
    height: 380,
    floorColor: '#2a221a',
    floorPattern: 'checkered',
    wallColor: '#695e4d',
    accentColor: '#F59E0B',
  },
  // 5. Engineering & Systems Pod (Center Left)
  {
    id: 'development',
    name: 'Engineering & Systems',
    label: 'ENGINEERING & SYSTEMS',
    type: 'dev',
    x: 40,
    y: 330,
    width: 460,
    height: 290,
    floorColor: '#17222b',
    floorPattern: 'grid',
    wallColor: '#3b516e',
    accentColor: '#38BDF8',
  },
  // 6. Pipelines & Automation Hub (Center Middle)
  {
    id: 'data-automation',
    name: 'Pipelines & Automation',
    label: 'PIPELINES & AUTOMATION',
    type: 'analytics',
    x: 516,
    y: 330,
    width: 384,
    height: 290,
    floorColor: '#201d38',
    floorPattern: 'grid',
    wallColor: '#5a4382',
    accentColor: '#8B5CF6',
  },
  // 7. Security & Gateway Watchtower (Center Far Right)
  {
    id: 'qa-security',
    name: 'Security & Gateway',
    label: 'SECURITY & GATEWAY',
    type: 'qa',
    x: 916,
    y: 330,
    width: 264,
    height: 290,
    floorColor: '#281b1d',
    floorPattern: 'grid',
    wallColor: '#73483d',
    accentColor: '#EF4444',
  },
  // 8. Synthetic Benchmark & Lab (Bottom Left)
  {
    id: 'research',
    name: 'Synthetic Benchmark & Lab',
    label: 'SYNTHETIC BENCHMARK & LAB',
    type: 'dev',
    x: 40,
    y: 656,
    width: 420,
    height: 254,
    floorColor: '#172622',
    floorPattern: 'grid',
    wallColor: '#3b6652',
    accentColor: '#10B981',
  },
  // 9. Operations & Sprawl Control (Bottom Center)
  {
    id: 'operations',
    name: 'Operations & Sprawl Control',
    label: 'OPERATIONS & SPRAWL CONTROL',
    type: 'dev',
    x: 476,
    y: 656,
    width: 440,
    height: 254,
    floorColor: '#26221a',
    floorPattern: 'grid',
    wallColor: '#635e3c',
    accentColor: '#EAB308',
  },
  // 10. Zen Patio & Fountain (Bottom Right)
  {
    id: 'zen-garden',
    name: 'Zen Patio & Fountain',
    label: 'ZEN PATIO & FOUNTAIN',
    type: 'zen_garden',
    x: 932,
    y: 436,
    width: 528,
    height: 474,
    floorColor: '#14221b',
    floorPattern: 'zen_stone',
    wallColor: '#395745',
    accentColor: '#34D399',
  },
];

/**
 * Solid Architectural Walls with 2.5D Depth
 * Agents can NEVER pass through these and must walk around them
 */
export const WALLS_2D: WallRect2D[] = [
  // 1. Outer Perimeter Walls (surrounding the entire office floor)
  { id: 'outer-top', x: 28, y: 28, width: 1444, height: 12, type: 'exterior' },
  { id: 'outer-bottom', x: 28, y: 910, width: 1444, height: 12, type: 'exterior' },
  { id: 'outer-left', x: 28, y: 28, width: 12, height: 894, type: 'exterior' },
  { id: 'outer-right', x: 1460, y: 28, width: 12, height: 894, type: 'exterior' },

  // 2. Executive Strategy Suite Walls
  // Divider between Executive and War Room
  { id: 'exec-east', x: 360, y: 36, width: 14, height: 240, type: 'solid' },
  // South wall of Executive Suite (leaves open doorway on right at x: 260 to 360)
  { id: 'exec-south-left', x: 36, y: 272, width: 224, height: 14, type: 'solid' },

  // 3. War Room / Conference Walls
  // Divider between War Room and Server Vault
  { id: 'war-east', x: 818, y: 36, width: 14, height: 240, type: 'solid' },
  // Glass partition on South of War Room (with double doors in the middle: x: 540 to 640)
  { id: 'war-south-left', x: 374, y: 272, width: 166, height: 14, type: 'glass' },
  { id: 'war-south-right', x: 640, y: 272, width: 180, height: 14, type: 'glass' },

  // 4. Server Vault Walls
  // Divider between Server Vault and Breakroom
  { id: 'server-east', x: 1180, y: 36, width: 14, height: 240, type: 'solid' },
  // South wall of Server Vault (doorway at x: 1040 to 1120)
  { id: 'server-south-left', x: 830, y: 272, width: 210, height: 14, type: 'solid' },
  { id: 'server-south-right', x: 1120, y: 272, width: 62, height: 14, type: 'solid' },

  // 5. Breakroom & Lounge Walls
  // West wall of Breakroom (open archway at y: 220 to 310)
  { id: 'break-west-top', x: 1192, y: 36, width: 14, height: 184, type: 'solid' },
  { id: 'break-west-bot', x: 1192, y: 310, width: 14, height: 112, type: 'solid' },
  // South wall of Breakroom
  { id: 'break-south', x: 1192, y: 418, width: 274, height: 14, type: 'solid' },

  // 6. Center Open Office Partition Dividers (Engineering, Data, QA Pods)
  // North partition rail between corridor and Engineering
  { id: 'dev-north-rail', x: 36, y: 324, width: 340, height: 10, type: 'partition' },
  // North partition rail between corridor and Data Pod
  { id: 'data-north-rail', x: 512, y: 324, width: 280, height: 10, type: 'partition' },
  // North partition rail between corridor and QA Watchtower
  { id: 'qa-north-rail', x: 912, y: 324, width: 180, height: 10, type: 'partition' },

  // Vertical Acoustic Baffles between pods
  { id: 'pod-divider-1', x: 500, y: 360, width: 12, height: 180, type: 'partition' },
  { id: 'pod-divider-2', x: 900, y: 360, width: 12, height: 180, type: 'partition' },
  { id: 'pod-divider-3', x: 1178, y: 324, width: 12, height: 100, type: 'partition' },

  // South partitions of central pods (leaving walkway openings to south corridor)
  { id: 'dev-south-rail', x: 36, y: 620, width: 340, height: 10, type: 'partition' },
  { id: 'data-south-rail', x: 512, y: 620, width: 280, height: 10, type: 'partition' },
  { id: 'qa-south-rail', x: 912, y: 620, width: 180, height: 10, type: 'partition' },

  // 7. Research Lab & Operations Walls (Bottom Wing)
  // North wall of Research Lab (doorway at x: 340 to 420)
  { id: 'research-north-left', x: 36, y: 650, width: 304, height: 14, type: 'solid' },
  // Divider between Research Lab and Operations
  { id: 'research-east', x: 460, y: 650, width: 14, height: 262, type: 'solid' },

  // North wall of Operations Hub (doorway at x: 780 to 860)
  { id: 'ops-north-left', x: 472, y: 650, width: 308, height: 14, type: 'solid' },
  // Divider between Operations and Zen Courtyard
  { id: 'ops-east', x: 916, y: 650, width: 14, height: 262, type: 'solid' },

  // 8. Zen Courtyard Stone Border Walls
  // North stone wall (Torii archway entrance at x: 924 to 1010)
  { id: 'zen-north-wall', x: 1010, y: 430, width: 454, height: 14, type: 'solid' },
  // West stone wall separating Zen Courtyard from QA Watchtower
  { id: 'zen-west-wall', x: 924, y: 430, width: 14, height: 222, type: 'solid' },
];

/**
 * Designated Doorways & Entryways with Thresholds & Directional Clearance
 */
export const DOORWAYS_2D: Doorway2D[] = [
  {
    id: 'door-exec',
    x: 264,
    y: 270,
    width: 92,
    height: 20,
    roomFrom: 'development',
    roomTo: 'executive',
    label: 'EXECUTIVE SUITE',
  },
  {
    id: 'door-war-room',
    x: 544,
    y: 270,
    width: 92,
    height: 20,
    roomFrom: 'corridor',
    roomTo: 'meeting',
    label: 'WAR ROOM MAIN',
  },
  {
    id: 'door-server-vault',
    x: 1044,
    y: 270,
    width: 72,
    height: 20,
    roomFrom: 'corridor',
    roomTo: 'server',
    label: 'SERVER VAULT',
  },
  {
    id: 'door-breakroom',
    x: 1188,
    y: 224,
    width: 20,
    height: 82,
    roomFrom: 'corridor',
    roomTo: 'breakroom',
    label: 'CAFE ARCHWAY',
  },
  {
    id: 'door-dev-pod',
    x: 380,
    y: 320,
    width: 80,
    height: 16,
    roomFrom: 'corridor',
    roomTo: 'development',
    label: 'ENGINEERING ENTRY',
  },
  {
    id: 'door-data-pod',
    x: 796,
    y: 320,
    width: 80,
    height: 16,
    roomFrom: 'corridor',
    roomTo: 'data-automation',
    label: 'DATA LAB ENTRY',
  },
  {
    id: 'door-qa-pod',
    x: 1096,
    y: 320,
    width: 76,
    height: 16,
    roomFrom: 'corridor',
    roomTo: 'qa-security',
    label: 'SECURITY WATCH',
  },
  {
    id: 'door-research',
    x: 344,
    y: 646,
    width: 80,
    height: 20,
    roomFrom: 'south-corridor',
    roomTo: 'research',
    label: 'RESEARCH LAB',
  },
  {
    id: 'door-ops',
    x: 784,
    y: 646,
    width: 80,
    height: 20,
    roomFrom: 'south-corridor',
    roomTo: 'operations',
    label: 'OPS COMMAND',
  },
  {
    id: 'door-zen-gate',
    x: 938,
    y: 426,
    width: 72,
    height: 22,
    roomFrom: 'corridor',
    roomTo: 'zen-garden',
    label: 'TORII GATE',
  },
];

export const DESKS_2D: Desk2D[] = [
  // Executive Desk (Manager) - Large Dark Mahogany with Brass Lamp, Organizer & Documents
  {
    id: 'manager-desk',
    name: "Architect's Executive Desk",
    zoneId: 'executive',
    x: 150,
    y: 110,
    width: 110,
    height: 48,
    seatX: 205,
    seatY: 86,
    facing: 'down',
    hasComputer: true,
    screenColor: '#FFB020',
    assignedAgentId: 'agent-manager',
    deskType: 'architect',
    monitorSetup: 'executive',
    accessories: ['lamp', 'phone', 'notes', 'espresso', 'notebook', 'papers', 'cert_plaque', 'pen_holder'],
    woodTone: 'dark_mahogany',
    lampOn: true,
  },

  // Engineering Pod Desks (4 distinct workstations)
  {
    id: 'dev-d1',
    name: 'Alpha Workstation (Backend Lead)',
    zoneId: 'development',
    x: 90,
    y: 400,
    width: 76,
    height: 38,
    seatX: 128,
    seatY: 378,
    facing: 'down',
    hasComputer: true,
    screenColor: '#3B82F6',
    assignedAgentId: 'agent-001',
    deskType: 'developer',
    monitorSetup: 'dual',
    accessories: ['headphones', 'coffee', 'cables', 'sticky_notes'],
    woodTone: 'carbon',
  },
  {
    id: 'dev-d2',
    name: 'Beta Workstation (Frontend Lead)',
    zoneId: 'development',
    x: 230,
    y: 400,
    width: 76,
    height: 38,
    seatX: 268,
    seatY: 378,
    facing: 'down',
    hasComputer: true,
    screenColor: '#06B6D4',
    assignedAgentId: 'agent-002',
    deskType: 'designer',
    monitorSetup: 'curved',
    accessories: ['tablet', 'coffee', 'plant', 'pen_holder'],
    woodTone: 'light_birch',
  },
  {
    id: 'dev-d3',
    name: 'Hash Workstation (Systems / Rust)',
    zoneId: 'development',
    x: 90,
    y: 520,
    width: 76,
    height: 38,
    seatX: 128,
    seatY: 498,
    facing: 'down',
    hasComputer: true,
    screenColor: '#10B981',
    assignedAgentId: 'agent-008',
    deskType: 'systems',
    monitorSetup: 'vertical_dual',
    accessories: ['can', 'headphones', 'notes', 'energy_drink'],
    woodTone: 'carbon',
  },
  {
    id: 'dev-d4',
    name: 'Bolt Workstation (Speed Coder)',
    zoneId: 'development',
    x: 230,
    y: 520,
    width: 76,
    height: 38,
    seatX: 268,
    seatY: 498,
    facing: 'down',
    hasComputer: true,
    screenColor: '#F59E0B',
    assignedAgentId: 'agent-bolt',
    deskType: 'developer',
    monitorSetup: 'triple',
    accessories: ['coffee', 'energy_drink', 'cables', 'sticky_notes'],
    woodTone: 'walnut',
  },

  // Data & Automation Pod Desks
  {
    id: 'data-d1',
    name: 'Omega Workstation (Data Scientist)',
    zoneId: 'data-automation',
    x: 570,
    y: 400,
    width: 76,
    height: 38,
    seatX: 608,
    seatY: 378,
    facing: 'down',
    hasComputer: true,
    screenColor: '#A855F7',
    assignedAgentId: 'agent-005',
    deskType: 'data',
    monitorSetup: 'laptop_monitor',
    accessories: ['lamp', 'notebook', 'coffee', 'water_bottle'],
    woodTone: 'oak',
    lampOn: true,
  },
  {
    id: 'auto-d1',
    name: 'Pulse Workstation (Automation Lead)',
    zoneId: 'data-automation',
    x: 710,
    y: 400,
    width: 76,
    height: 38,
    seatX: 748,
    seatY: 378,
    facing: 'down',
    hasComputer: true,
    screenColor: '#06B6D4',
    assignedAgentId: 'agent-010',
    deskType: 'ops',
    monitorSetup: 'dual',
    accessories: ['headphones', 'cables', 'notes', 'can'],
    woodTone: 'carbon',
  },
  {
    id: 'auto-d2',
    name: 'Forge Workstation (Full Stack Automator)',
    zoneId: 'data-automation',
    x: 640,
    y: 520,
    width: 76,
    height: 38,
    seatX: 678,
    seatY: 498,
    facing: 'down',
    hasComputer: true,
    screenColor: '#F97316',
    assignedAgentId: 'agent-012',
    deskType: 'developer',
    monitorSetup: 'triple',
    accessories: ['coffee', 'phone', 'plant', 'papers'],
    woodTone: 'walnut',
  },

  // QA & Security Watchtower
  {
    id: 'qa-d1',
    name: 'Gamma Workstation (QA & Regression)',
    zoneId: 'qa-security',
    x: 970,
    y: 400,
    width: 76,
    height: 38,
    seatX: 1008,
    seatY: 378,
    facing: 'down',
    hasComputer: true,
    screenColor: '#F59E0B',
    assignedAgentId: 'agent-003',
    deskType: 'qa',
    monitorSetup: 'dual',
    accessories: ['notes', 'coffee', 'notebook', 'sticky_notes'],
    woodTone: 'oak',
  },
  {
    id: 'qa-d2',
    name: 'Cipher Workstation (Threat Auditor)',
    zoneId: 'qa-security',
    x: 970,
    y: 520,
    width: 76,
    height: 38,
    seatX: 1008,
    seatY: 498,
    facing: 'down',
    hasComputer: true,
    screenColor: '#EF4444',
    assignedAgentId: 'agent-007',
    deskType: 'qa',
    monitorSetup: 'triple',
    accessories: ['lamp', 'headphones', 'can', 'water_bottle'],
    woodTone: 'carbon',
    lampOn: true,
  },

  // Research Lab Desks
  {
    id: 'research-d1',
    name: 'Nova Workstation (Research Scientist)',
    zoneId: 'research',
    x: 90,
    y: 740,
    width: 76,
    height: 38,
    seatX: 128,
    seatY: 718,
    facing: 'down',
    hasComputer: true,
    screenColor: '#10B981',
    assignedAgentId: 'agent-006',
    deskType: 'research',
    monitorSetup: 'vertical_dual',
    accessories: ['notebook', 'coffee', 'plant', 'papers'],
    woodTone: 'light_birch',
  },
  {
    id: 'research-d2',
    name: 'Sage Workstation (Grounding & Reasoning)',
    zoneId: 'research',
    x: 220,
    y: 740,
    width: 76,
    height: 38,
    seatX: 258,
    seatY: 718,
    facing: 'down',
    hasComputer: true,
    screenColor: '#34D399',
    assignedAgentId: 'agent-sage',
    deskType: 'research',
    monitorSetup: 'curved',
    accessories: ['lamp', 'notebook', 'notes', 'espresso'],
    woodTone: 'walnut',
    lampOn: true,
  },

  // Operations & Support Desks
  {
    id: 'ops-d1',
    name: 'Delta Workstation (DevOps & Deploy)',
    zoneId: 'operations',
    x: 540,
    y: 740,
    width: 76,
    height: 38,
    seatX: 578,
    seatY: 718,
    facing: 'down',
    hasComputer: true,
    screenColor: '#EAB308',
    assignedAgentId: 'agent-004',
    deskType: 'ops',
    monitorSetup: 'dual',
    accessories: ['headphones', 'coffee', 'can', 'cables'],
    woodTone: 'carbon',
  },
  {
    id: 'support-d1',
    name: 'Echo Workstation (Customer Support)',
    zoneId: 'operations',
    x: 670,
    y: 740,
    width: 76,
    height: 38,
    seatX: 708,
    seatY: 718,
    facing: 'down',
    hasComputer: true,
    screenColor: '#38BDF8',
    assignedAgentId: 'agent-009',
    deskType: 'support',
    monitorSetup: 'laptop_monitor',
    accessories: ['headphones', 'phone', 'coffee', 'sticky_notes'],
    woodTone: 'oak',
  },
  {
    id: 'planning-d1',
    name: 'Nexus Workstation (Sprint Ops)',
    zoneId: 'operations',
    x: 800,
    y: 740,
    width: 76,
    height: 38,
    seatX: 838,
    seatY: 718,
    facing: 'down',
    hasComputer: true,
    screenColor: '#A855F7',
    assignedAgentId: 'agent-011',
    deskType: 'manager',
    monitorSetup: 'dual',
    accessories: ['notes', 'tablet', 'coffee', 'papers'],
    woodTone: 'walnut',
  },
];

/**
 * Environmental Props & Atmospheric Storytelling Objects
 * Positioned cleanly along wall perimeters, corners, and alcoves
 */
export const ENVIRONMENTAL_PROPS_2D: EnvironmentalProp2D[] = [
  // 1. Executive Suite Decor
  { id: 'prop-exec-clock', type: 'wall_clock', x: 195, y: 44, width: 20, height: 20, label: 'EST' },
  { id: 'prop-exec-filing', type: 'filing_cabinet', x: 290, y: 60, width: 34, height: 38, color: '#3b2f24' },
  { id: 'prop-exec-plant', type: 'bonsai', x: 60, y: 190, width: 28, height: 28 },
  { id: 'prop-exec-poster', type: 'poster', x: 100, y: 44, width: 32, height: 20, label: 'VISION' },

  // 2. War Room / Conference Decor
  { id: 'prop-conf-screen', type: 'banner', x: 550, y: 44, width: 90, height: 22, label: 'SPRINT BURNDOWN' },
  { id: 'prop-conf-clock', type: 'wall_clock', x: 720, y: 44, width: 20, height: 20, label: 'UTC' },
  { id: 'prop-conf-extinguisher', type: 'fire_extinguisher', x: 385, y: 55, width: 14, height: 24 },
  { id: 'prop-conf-recycle', type: 'recycle_bin', x: 770, y: 220, width: 18, height: 22 },

  // 3. Server Vault Decor
  { id: 'prop-serv-cooler', type: 'storage_box', x: 845, y: 60, width: 26, height: 30, label: 'FIBER' },
  { id: 'prop-serv-exting', type: 'fire_extinguisher', x: 1155, y: 55, width: 14, height: 24 },
  { id: 'prop-serv-sign', type: 'exit_sign', x: 1060, y: 268, width: 28, height: 12 },

  // 4. Breakroom / Kitchen Decor
  { id: 'prop-brk-clock', type: 'wall_clock', x: 1320, y: 44, width: 20, height: 20 },
  { id: 'prop-brk-notice', type: 'notice_board', x: 1205, y: 50, width: 28, height: 34, label: 'EVENTS' },
  { id: 'prop-brk-trash', type: 'trash_bin', x: 1205, y: 140, width: 18, height: 22 },
  { id: 'prop-brk-recycle', type: 'recycle_bin', x: 1205, y: 168, width: 18, height: 22 },
  { id: 'prop-brk-lamp', type: 'floor_lamp', x: 1345, y: 275, width: 16, height: 38, glowColor: '#f59e0b' },

  // 5. Engineering Pod Decor
  { id: 'prop-eng-printer', type: 'printer', x: 420, y: 390, width: 34, height: 32, label: 'LASER-01' },
  { id: 'prop-eng-filing', type: 'filing_cabinet', x: 420, y: 440, width: 34, height: 38 },
  { id: 'prop-eng-trash1', type: 'trash_bin', x: 180, y: 425, width: 16, height: 18 },
  { id: 'prop-eng-trash2', type: 'recycle_bin', x: 180, y: 545, width: 16, height: 18 },
  { id: 'prop-eng-whiteboard', type: 'whiteboard_small', x: 50, y: 450, width: 28, height: 44 },
  { id: 'prop-eng-poster', type: 'poster', x: 260, y: 324, width: 32, height: 16, label: 'SHIP IT' },

  // 6. Data Hub Decor
  { id: 'prop-data-filing', type: 'filing_cabinet', x: 840, y: 390, width: 34, height: 38 },
  { id: 'prop-data-printer', type: 'printer', x: 840, y: 440, width: 34, height: 32, label: 'DATA-PR' },
  { id: 'prop-data-trash', type: 'trash_bin', x: 650, y: 425, width: 16, height: 18 },
  { id: 'prop-data-water', type: 'water_cooler', x: 525, y: 560, width: 20, height: 34 },

  // 7. QA Watchtower Decor
  { id: 'prop-qa-filing', type: 'filing_cabinet', x: 1120, y: 520, width: 34, height: 38 },
  { id: 'prop-qa-sign', type: 'exit_sign', x: 1115, y: 320, width: 26, height: 12 },
  { id: 'prop-qa-exting', type: 'fire_extinguisher', x: 928, y: 350, width: 14, height: 24 },

  // 8. Research Lab Decor
  { id: 'prop-res-filing', type: 'filing_cabinet', x: 380, y: 730, width: 34, height: 38 },
  { id: 'prop-res-boxes', type: 'storage_box', x: 380, y: 780, width: 30, height: 34, label: 'BENCH' },
  { id: 'prop-res-poster', type: 'poster', x: 150, y: 652, width: 34, height: 16, label: 'TRANSFORMER' },

  // 9. Operations Hub Decor
  { id: 'prop-ops-whiteboard', type: 'whiteboard_small', x: 485, y: 730, width: 28, height: 44 },
  { id: 'prop-ops-filing', type: 'filing_cabinet', x: 865, y: 730, width: 34, height: 38 },
  { id: 'prop-ops-clock', type: 'wall_clock', x: 640, y: 652, width: 20, height: 20, label: 'OPS' },
  { id: 'prop-ops-trash', type: 'trash_bin', x: 625, y: 765, width: 16, height: 18 },

  // 10. Zen Courtyard Decor
  { id: 'prop-zen-lamp1', type: 'wall_sconce', x: 940, y: 490, width: 14, height: 14, glowColor: '#34d399' },
  { id: 'prop-zen-lamp2', type: 'wall_sconce', x: 1390, y: 490, width: 14, height: 14, glowColor: '#34d399' },
  { id: 'prop-zen-bonsai', type: 'bonsai', x: 1220, y: 530, width: 30, height: 30 },
];

export const INTERACTIVE_POIS: InteractivePOI[] = [
  // 1. Espresso Coffee Machine (Breakroom)
  {
    id: 'poi-coffee',
    name: 'Nexus Barista Espresso Machine',
    type: 'coffee_machine',
    x: 1240,
    y: 70,
    width: 44,
    height: 36,
    interactX: 1262,
    interactY: 120,
    interactionName: 'Brew Double Espresso',
    icon: '☕',
    description: 'Freshly roasted dark blend. Boosts agent energy & reasoning focus by +40%.',
  },
  // 2. Retro 8-bit Arcade Cabinet (Breakroom)
  {
    id: 'poi-arcade',
    name: 'NEXUS-84 Pixel Arcade Cabinet',
    type: 'arcade',
    x: 1360,
    y: 70,
    width: 46,
    height: 52,
    interactX: 1383,
    interactY: 135,
    interactionName: 'Play Pixel Asteroids',
    icon: '🕹️',
    description: 'Classic retro arcade game. Agents blow off steam and challenge high scores!',
  },
  // 3. Pure Water Cooler (Breakroom)
  {
    id: 'poi-cooler',
    name: 'Zero-Sodium Water Dispenser',
    type: 'water_cooler',
    x: 1230,
    y: 190,
    width: 32,
    height: 42,
    interactX: 1260,
    interactY: 235,
    interactionName: 'Grab Ice Cold Water',
    icon: '💧',
    description: 'Hot spot for office gossip, sprint rumors, and hydration.',
  },
  // 4. Whiteboard (Meeting Room)
  {
    id: 'poi-whiteboard',
    name: 'Architecture & Sprint Whiteboard',
    type: 'whiteboard',
    x: 420,
    y: 60,
    width: 140,
    height: 24,
    interactX: 490,
    interactY: 95,
    interactionName: 'Inspect Architecture Flow',
    icon: '📋',
    description: 'Real-time sprint architecture, microservice diagram, and milestone checklist.',
  },
  // 5. Blinking Supercomputer Rack (Server Room)
  {
    id: 'poi-server-cluster',
    name: 'NVIDIA H100 GPU Server Cluster',
    type: 'server_rack',
    x: 880,
    y: 70,
    width: 140,
    height: 44,
    interactX: 950,
    interactY: 130,
    interactionName: 'Inspect Cluster Telemetry',
    icon: '⚡',
    description: '8x H100 NVLink Cluster running 120 TFLOPS inference with 99.98% uptime.',
  },
  // 6. Zen Fountain & Stepping Stones (Courtyard)
  {
    id: 'poi-fountain',
    name: 'Zen Bamboo Water Fountain',
    type: 'fountain',
    x: 1140,
    y: 620,
    width: 70,
    height: 70,
    interactX: 1175,
    interactY: 705,
    interactionName: 'Meditate by Fountain',
    icon: '🎋',
    description: 'Calming trickling water surrounded by bonsai and smooth river stones.',
  },
  // 7. Technical Knowledge Library (Executive Cabin)
  {
    id: 'poi-bookshelf',
    name: 'Executive Technical Library',
    type: 'bookshelf',
    x: 60,
    y: 60,
    width: 80,
    height: 24,
    interactX: 100,
    interactY: 95,
    interactionName: 'Browse System Architecture Papers',
    icon: '📚',
    description: 'Seminal papers on Transformer attention, Paxos consensus, and distributed locks.',
  },
  // 8. Snack Vending Machine (Breakroom)
  {
    id: 'poi-vending',
    name: 'Healthy Snack Vending Matrix',
    type: 'vending_machine',
    x: 1380,
    y: 200,
    width: 44,
    height: 54,
    interactX: 1360,
    interactY: 260,
    interactionName: 'Dispense Protein Snack',
    icon: '🍫',
    description: 'Energy snacks, green tea, matcha bars, and dark chocolate almonds.',
  },
];

export const FURNITURE_2D: Furniture2D[] = [
  // Meeting Room Conference Table & Chairs
  {
    id: 'conf-table',
    type: 'table',
    x: 520,
    y: 120,
    width: 180,
    height: 80,
    color: '#2a243d',
  },
  // Conference Chairs (Surrounding the table)
  { id: 'conf-c1', type: 'chair', x: 550, y: 95, width: 20, height: 20 },
  { id: 'conf-c2', type: 'chair', x: 600, y: 95, width: 20, height: 20 },
  { id: 'conf-c3', type: 'chair', x: 650, y: 95, width: 20, height: 20 },
  { id: 'conf-c4', type: 'chair', x: 550, y: 205, width: 20, height: 20 },
  { id: 'conf-c5', type: 'chair', x: 600, y: 205, width: 20, height: 20 },
  { id: 'conf-c6', type: 'chair', x: 650, y: 205, width: 20, height: 20 },
  { id: 'conf-c7', type: 'chair', x: 495, y: 150, width: 20, height: 20 },
  { id: 'conf-c8', type: 'chair', x: 705, y: 150, width: 20, height: 20 },

  // Breakroom Round Cafe Dining Table & Chairs
  {
    id: 'cafe-round-table',
    type: 'table',
    x: 1280,
    y: 195,
    width: 56,
    height: 56,
    color: '#4a3525',
  },
  { id: 'cafe-c1', type: 'chair', x: 1298, y: 175, width: 20, height: 20 },
  { id: 'cafe-c2', type: 'chair', x: 1298, y: 255, width: 20, height: 20 },
  { id: 'cafe-c3', type: 'chair', x: 1255, y: 213, width: 20, height: 20 },
  { id: 'cafe-c4', type: 'chair', x: 1342, y: 213, width: 20, height: 20 },

  // Breakroom Lounge Sofas & Coffee Table
  {
    id: 'sofa-1',
    type: 'sofa',
    x: 1235,
    y: 320,
    width: 90,
    height: 36,
    color: '#473c2a',
  },
  {
    id: 'sofa-table',
    type: 'table',
    x: 1255,
    y: 365,
    width: 50,
    height: 25,
    color: '#2b2419',
  },

  // Server Room Additional Racks
  {
    id: 'rack-2',
    type: 'server_rack',
    x: 1040,
    y: 70,
    width: 100,
    height: 44,
    color: '#0d2230',
  },
  {
    id: 'rack-3',
    type: 'server_rack',
    x: 880,
    y: 160,
    width: 260,
    height: 40,
    color: '#0d2230',
  },

  // Plants across the office for natural ambiance
  { id: 'p1', type: 'plant', x: 330, y: 55, width: 24, height: 24 },
  { id: 'p2', type: 'plant', x: 395, y: 55, width: 24, height: 24 },
  { id: 'p3', type: 'plant', x: 805, y: 55, width: 24, height: 24 },
  { id: 'p4', type: 'plant', x: 855, y: 55, width: 24, height: 24 },
  { id: 'p5', type: 'plant', x: 55, y: 345, width: 24, height: 24 },
  { id: 'p6', type: 'plant', x: 465, y: 345, width: 24, height: 24 },
  { id: 'p7', type: 'plant', x: 535, y: 345, width: 24, height: 24 },
  { id: 'p8', type: 'plant', x: 865, y: 345, width: 24, height: 24 },
  { id: 'p9', type: 'plant', x: 935, y: 345, width: 24, height: 24 },
  { id: 'p10', type: 'plant', x: 1145, y: 345, width: 24, height: 24 },

  // Zen Garden Benches
  {
    id: 'bench-1',
    type: 'sofa',
    x: 1000,
    y: 520,
    width: 60,
    height: 24,
    color: '#36473b',
  },
  {
    id: 'bench-2',
    type: 'sofa',
    x: 1300,
    y: 520,
    width: 60,
    height: 24,
    color: '#36473b',
  },
  {
    id: 'bench-3',
    type: 'sofa',
    x: 1050,
    y: 800,
    width: 60,
    height: 24,
    color: '#36473b',
  },
  {
    id: 'bench-4',
    type: 'sofa',
    x: 1280,
    y: 800,
    width: 60,
    height: 24,
    color: '#36473b',
  },
];

/**
 * Interconnected Roam Waypoints in walkable corridor network
 */
export const ROAM_WAYPOINTS = [
  // North Main Corridor (East-West Aisle between Top Rooms & Dev Pods)
  { x: 300, y: 295, name: 'Executive Foyer', zoneId: 'executive' },
  { x: 450, y: 295, name: 'North Central Junction', zoneId: 'development' },
  { x: 590, y: 295, name: 'War Room Portal', zoneId: 'meeting' },
  { x: 780, y: 295, name: 'Server Aisle Entry', zoneId: 'server' },
  { x: 1080, y: 295, name: 'Server South Gate', zoneId: 'server' },
  { x: 1160, y: 295, name: 'Breakroom Crossing', zoneId: 'breakroom' },

  // Central Open Floor Aisles
  { x: 380, y: 460, name: 'Dev Pod Main Aisle', zoneId: 'development' },
  { x: 510, y: 460, name: 'Center Plaza West', zoneId: 'data-automation' },
  { x: 710, y: 460, name: 'Data Hub Crossroad', zoneId: 'data-automation' },
  { x: 910, y: 460, name: 'Security Crossing West', zoneId: 'qa-security' },
  { x: 1120, y: 460, name: 'QA Watchtower Aisle', zoneId: 'qa-security' },

  // South Main Corridor (between Dev Pods and Bottom Wing)
  { x: 200, y: 636, name: 'Research Corridor West', zoneId: 'research' },
  { x: 380, y: 636, name: 'Research Lab Portal', zoneId: 'research' },
  { x: 620, y: 636, name: 'Ops Hub North Corridor', zoneId: 'operations' },
  { x: 820, y: 636, name: 'Ops Command Portal', zoneId: 'operations' },
  { x: 970, y: 460, name: 'Torii Archway Entry', zoneId: 'zen-garden' },

  // Inside Breakroom
  { x: 1260, y: 140, name: 'Coffee Bar Front', zoneId: 'breakroom' },
  { x: 1370, y: 140, name: 'Arcade Arena', zoneId: 'breakroom' },
  { x: 1300, y: 230, name: 'Water Cooler Lounge', zoneId: 'breakroom' },
  { x: 1300, y: 350, name: 'Breakroom Sofas', zoneId: 'breakroom' },

  // Inside War Room / Conference
  { x: 500, y: 150, name: 'War Room Left Wing', zoneId: 'meeting' },
  { x: 590, y: 150, name: 'War Room Center Podium', zoneId: 'meeting' },
  { x: 720, y: 150, name: 'War Room Right Wing', zoneId: 'meeting' },
  { x: 490, y: 95, name: 'Whiteboard Presentation Spot', zoneId: 'meeting' },

  // Inside Server Room
  { x: 950, y: 130, name: 'Server Aisle Alpha', zoneId: 'server' },
  { x: 1080, y: 130, name: 'Server Aisle Beta', zoneId: 'server' },

  // Inside Zen Garden
  { x: 1050, y: 550, name: 'Zen Bamboo Walk', zoneId: 'zen-garden' },
  { x: 1180, y: 560, name: 'Zen Pavilion', zoneId: 'zen-garden' },
  { x: 1320, y: 580, name: 'Zen East Bench', zoneId: 'zen-garden' },
  { x: 1175, y: 720, name: 'Zen Fountain Reflection Area', zoneId: 'zen-garden' },
  { x: 1050, y: 780, name: 'Stone Pathway South', zoneId: 'zen-garden' },
];

export const OFFICE_2D_LAYOUT: Office2DLayout = {
  width: 1500,
  height: 950,
  rooms: ROOMS_2D,
  desks: DESKS_2D,
  pois: INTERACTIVE_POIS,
  furniture: FURNITURE_2D,
  environmentalProps: ENVIRONMENTAL_PROPS_2D,
  walls: WALLS_2D,
  doorways: DOORWAYS_2D,
  roamWaypoints: ROAM_WAYPOINTS,
};

// Initialize collision grid immediately on module load
initCollisionGrid({
  walls: WALLS_2D,
  desks: DESKS_2D,
  furniture: FURNITURE_2D,
  pois: INTERACTIVE_POIS,
  doorways: DOORWAYS_2D,
  environmentalProps: ENVIRONMENTAL_PROPS_2D,
});
