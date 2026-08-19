/**
 * 3D Office Layout Configuration
 * Defines zone positions, desk positions, agent assignments, and color theming
 * for the Three.js isometric office view.
 */

export interface Zone3D {
  id: string;
  name: string;
  position: [number, number, number];
  size: [number, number];
  color: string;
  borderColor: string;
  desks: DeskPosition[];
}

export interface DeskPosition {
  id: string;
  position: [number, number, number];
  rotation?: number;
}

export interface MockAgent3D {
  id: string;
  name: string;
  role: string;
  model: string;
  status: 'working' | 'idle' | 'review' | 'offline';
  zoneId: string;
  deskId: string;
  capabilities: string[];
  cpu: number;
  memory: number;
  taskProgress: number;
  currentTask: string;
  sparklineData: number[];
}

/** Status color mapping for 3D agents */
export const status3DColors: Record<string, string> = {
  working: '#10b981',
  idle: '#f59e0b',
  review: '#a855f7',
  offline: '#9ca3af',
};

/** Status labels */
export const statusLabels: Record<string, string> = {
  working: 'Working',
  idle: 'Idle',
  review: 'Review',
  offline: 'Offline',
};

/** Zone definitions with 3D coordinates */
export const zones3D: Zone3D[] = [
  {
    id: 'planning',
    name: 'Planning Zone',
    position: [-12, 0, -8],
    size: [7, 5],
    color: '#1e3a5f',
    borderColor: '#3b82f6',
    desks: [
      { id: 'planning-d1', position: [-13, 0.5, -9] },
      { id: 'planning-d2', position: [-11, 0.5, -9] },
    ],
  },
  {
    id: 'development',
    name: 'Development Zone',
    position: [-4, 0, -8],
    size: [8, 5],
    color: '#1a3d2e',
    borderColor: '#10b981',
    desks: [
      { id: 'dev-d1', position: [-6, 0.5, -9] },
      { id: 'dev-d2', position: [-4, 0.5, -9] },
      { id: 'dev-d3', position: [-2, 0.5, -9] },
    ],
  },
  {
    id: 'qa-security',
    name: 'QA & Security Zone',
    position: [5, 0, -8],
    size: [7, 5],
    color: '#3d2e1a',
    borderColor: '#f59e0b',
    desks: [
      { id: 'qa-d1', position: [4, 0.5, -9] },
      { id: 'qa-d2', position: [6, 0.5, -9] },
    ],
  },
  {
    id: 'data',
    name: 'Data Zone',
    position: [-12, 0, -1],
    size: [7, 5],
    color: '#2e1a3d',
    borderColor: '#a855f7',
    desks: [
      { id: 'data-d1', position: [-13, 0.5, -2] },
      { id: 'data-d2', position: [-11, 0.5, -2] },
    ],
  },
  {
    id: 'meeting',
    name: 'Meeting Area',
    position: [-4, 0, -1],
    size: [8, 5],
    color: '#3d1a2e',
    borderColor: '#fb7185',
    desks: [
      { id: 'meeting-d1', position: [-5, 0.5, -2] },
      { id: 'meeting-d2', position: [-3, 0.5, -2] },
    ],
  },
  {
    id: 'automation',
    name: 'Automation Zone',
    position: [5, 0, -1],
    size: [7, 5],
    color: '#1a2e3d',
    borderColor: '#06b6d4',
    desks: [
      { id: 'auto-d1', position: [4, 0.5, -2] },
      { id: 'auto-d2', position: [6, 0.5, -2] },
    ],
  },
  {
    id: 'research',
    name: 'Research Zone',
    position: [-12, 0, 6],
    size: [7, 5],
    color: '#2e3d1a',
    borderColor: '#84cc16',
    desks: [
      { id: 'research-d1', position: [-13, 0.5, 5] },
      { id: 'research-d2', position: [-11, 0.5, 5] },
    ],
  },
  {
    id: 'operations',
    name: 'Operations Zone',
    position: [-4, 0, 6],
    size: [8, 5],
    color: '#3d3d1a',
    borderColor: '#eab308',
    desks: [
      { id: 'ops-d1', position: [-5, 0.5, 5] },
      { id: 'ops-d2', position: [-3, 0.5, 5] },
    ],
  },
  {
    id: 'support',
    name: 'Support Zone',
    position: [5, 0, 6],
    size: [7, 5],
    color: '#1a3d3d',
    borderColor: '#14b8a6',
    desks: [
      { id: 'support-d1', position: [4, 0.5, 5] },
      { id: 'support-d2', position: [6, 0.5, 5] },
    ],
  },
];

/** Manager cabin definition */
export const managerCabin = {
  position: [-4, 0, -14] as [number, number, number],
  size: [6, 4] as [number, number],
  deskPosition: [-4, 0.5, -14.5] as [number, number, number],
  color: '#1e2035',
  borderColor: '#6366f1',
};

/** Mock agents for the 3D office demo */
export const mockAgents3D: MockAgent3D[] = [
  {
    id: 'agent-001',
    name: 'Alpha',
    role: 'Backend Dev',
    model: 'GPT-4o',
    status: 'working',
    zoneId: 'development',
    deskId: 'dev-d1',
    capabilities: ['API Design', 'Database', 'Microservices'],
    cpu: 72,
    memory: 65,
    taskProgress: 78,
    currentTask: 'Building REST API endpoints',
    sparklineData: [45, 52, 48, 61, 72, 68, 75, 72],
  },
  {
    id: 'agent-002',
    name: 'Beta',
    role: 'Frontend Dev',
    model: 'Claude 3.5',
    status: 'working',
    zoneId: 'development',
    deskId: 'dev-d2',
    capabilities: ['React', 'TypeScript', 'CSS', 'UI/UX'],
    cpu: 58,
    memory: 45,
    taskProgress: 45,
    currentTask: 'Implementing dashboard components',
    sparklineData: [30, 42, 55, 48, 52, 58, 54, 58],
  },
  {
    id: 'agent-003',
    name: 'Gamma',
    role: 'QA Engineer',
    model: 'Gemini 1.5 Pro',
    status: 'review',
    zoneId: 'qa-security',
    deskId: 'qa-d1',
    capabilities: ['Testing', 'Security Audit', 'CI/CD'],
    cpu: 34,
    memory: 28,
    taskProgress: 92,
    currentTask: 'Reviewing pull request #142',
    sparklineData: [20, 25, 34, 30, 28, 34, 32, 34],
  },
  {
    id: 'agent-004',
    name: 'Delta',
    role: 'DevOps',
    model: 'GPT-4o',
    status: 'working',
    zoneId: 'operations',
    deskId: 'ops-d1',
    capabilities: ['Docker', 'Kubernetes', 'AWS', 'Terraform'],
    cpu: 85,
    memory: 72,
    taskProgress: 60,
    currentTask: 'Deploying v2.3 to staging',
    sparklineData: [65, 70, 78, 82, 85, 80, 83, 85],
  },
  {
    id: 'agent-005',
    name: 'Omega',
    role: 'Data Analyst',
    model: 'Claude 3.5',
    status: 'idle',
    zoneId: 'data',
    deskId: 'data-d1',
    capabilities: ['Python', 'SQL', 'ML', 'Visualization'],
    cpu: 12,
    memory: 20,
    taskProgress: 0,
    currentTask: 'Awaiting new data pipeline task',
    sparklineData: [40, 35, 28, 20, 15, 12, 10, 12],
  },
  {
    id: 'agent-006',
    name: 'Nova',
    role: 'Research Scientist',
    model: 'Gemini 1.5 Pro',
    status: 'working',
    zoneId: 'research',
    deskId: 'research-d1',
    capabilities: ['NLP', 'Deep Learning', 'Papers', 'Experiments'],
    cpu: 90,
    memory: 88,
    taskProgress: 35,
    currentTask: 'Training new language model',
    sparklineData: [75, 80, 85, 88, 90, 92, 89, 90],
  },
  {
    id: 'agent-007',
    name: 'Cipher',
    role: 'Security Analyst',
    model: 'GPT-4o',
    status: 'review',
    zoneId: 'qa-security',
    deskId: 'qa-d2',
    capabilities: ['Pentesting', 'Threat Detection', 'Encryption'],
    cpu: 45,
    memory: 38,
    taskProgress: 88,
    currentTask: 'Security audit for auth module',
    sparklineData: [35, 40, 42, 45, 43, 45, 44, 45],
  },
  {
    id: 'agent-008',
    name: 'Hash',
    role: 'Backend Dev',
    model: 'Claude 3.5',
    status: 'offline',
    zoneId: 'development',
    deskId: 'dev-d3',
    capabilities: ['Rust', 'Go', 'Systems Programming'],
    cpu: 0,
    memory: 0,
    taskProgress: 0,
    currentTask: 'Agent offline - scheduled maintenance',
    sparklineData: [50, 45, 30, 15, 5, 0, 0, 0],
  },
  {
    id: 'agent-009',
    name: 'Echo',
    role: 'Support Engineer',
    model: 'GPT-4o',
    status: 'working',
    zoneId: 'support',
    deskId: 'support-d1',
    capabilities: ['Debugging', 'Documentation', 'Customer Support'],
    cpu: 42,
    memory: 35,
    taskProgress: 55,
    currentTask: 'Resolving ticket #8823',
    sparklineData: [30, 35, 38, 42, 40, 42, 41, 42],
  },
  {
    id: 'agent-010',
    name: 'Pulse',
    role: 'Automation Engineer',
    model: 'Gemini 1.5 Pro',
    status: 'idle',
    zoneId: 'automation',
    deskId: 'auto-d1',
    capabilities: ['Workflows', 'Scripting', 'Integration'],
    cpu: 8,
    memory: 15,
    taskProgress: 0,
    currentTask: 'Standby - monitoring automation pipelines',
    sparklineData: [25, 20, 15, 10, 8, 10, 8, 8],
  },
  {
    id: 'agent-011',
    name: 'Nexus',
    role: 'Project Manager',
    model: 'GPT-4o',
    status: 'working',
    zoneId: 'planning',
    deskId: 'planning-d1',
    capabilities: ['Planning', 'Coordination', 'Sprint Management'],
    cpu: 55,
    memory: 48,
    taskProgress: 70,
    currentTask: 'Coordinating Sprint 14 tasks',
    sparklineData: [40, 45, 50, 55, 52, 55, 53, 55],
  },
  {
    id: 'agent-012',
    name: 'Forge',
    role: 'Full Stack Dev',
    model: 'Claude 3.5',
    status: 'working',
    zoneId: 'automation',
    deskId: 'auto-d2',
    capabilities: ['Node.js', 'React', 'PostgreSQL', 'Redis'],
    cpu: 68,
    memory: 55,
    taskProgress: 82,
    currentTask: 'Building real-time notification system',
    sparklineData: [50, 55, 60, 65, 68, 70, 67, 68],
  },
];

/** Manager agent (special - sits in manager cabin) */
export const managerAgent: MockAgent3D = {
  id: 'agent-manager',
  name: 'Architect',
  role: 'Engineering Manager',
  model: 'GPT-4o',
  status: 'working',
  zoneId: 'manager',
  deskId: 'manager-desk',
  capabilities: ['Architecture', 'Code Review', 'Team Management', 'Strategy'],
  cpu: 62,
  memory: 50,
  taskProgress: 45,
  currentTask: 'Delegating sprint tasks to team',
  sparklineData: [50, 55, 58, 60, 62, 60, 61, 62],
};
