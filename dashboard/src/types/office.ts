import type { UUID } from './common';

export type RoomType = 'office' | 'meeting_room' | 'lab' | 'common_area' | 'server_room';

export type AgentPositionStatus = 'working' | 'idle' | 'meeting' | 'away';

export type DelegationStatus = 'active' | 'completed' | 'failed';

export interface OfficeRoom {
  id: string;
  name: string;
  type: RoomType;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  borderColor: string;
  departmentId?: UUID;
}

export interface AgentPosition {
  agentId: UUID;
  roomId: string;
  x: number;
  y: number;
  status: AgentPositionStatus;
}

export interface DelegationArrow {
  id: string;
  fromAgentId: UUID;
  toAgentId: UUID;
  taskTitle: string;
  status: DelegationStatus;
}

export interface ActiveMeeting {
  id: string;
  roomId: string;
  title: string;
  type: string;
  participantIds: UUID[];
}

export interface OfficeState {
  rooms: OfficeRoom[];
  agents: AgentPosition[];
  delegations: DelegationArrow[];
  meetings: ActiveMeeting[];
}

export interface OfficeEvent {
  id: string;
  timestamp: string;
  type: 'task_completed' | 'delegation' | 'issue' | 'meeting' | 'status_change';
  message: string;
  agentName?: string;
}

export interface OfficeControls {
  zoom: number;
  panX: number;
  panY: number;
  showLabels: boolean;
  showDelegations: boolean;
  departmentFilter: string | null;
  nightMode: boolean;
}
