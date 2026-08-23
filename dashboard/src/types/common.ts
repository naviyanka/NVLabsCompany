export type UUID = string;
export type DateTimeString = string;

export type AgentStatus =
  | 'idle'
  | 'active'
  | 'busy'
  | 'running'
  | 'paused'
  | 'error'
  | 'terminated'
  | 'working'
  | 'review'
  | 'offline';

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'blocked' | 'cancelled';
export type TaskPriority = 1 | 2 | 3 | 4 | 5; // 1 = Critical, 5 = Lowest

