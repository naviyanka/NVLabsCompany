import type { ReactNode } from 'react';
import type { Connection, Edge, Node } from 'reactflow';

export const CANVAS_MODES = ['workflow', 'network', 'context', 'organization'] as const;
export type CanvasMode = (typeof CANVAS_MODES)[number];

/** The domain row a node stands for. */
export type EntityKind =
  | 'agent'
  | 'session'
  | 'connection'
  | 'tool'
  | 'department'
  | 'team'
  | 'pipeline'
  | 'stage';

/** Tool access as the server decided it; `unscoped` = not in its answer. */
export type ToolOutcome = 'allowed' | 'would_deny' | 'denied' | 'unscoped';

export interface EntityData {
  kind: EntityKind;
  /** The domain id (agent id, binding id, …), never a presentation id. */
  entityId: string;
  label: string;
  subtitle?: string;
  /** Tool nodes only: copied verbatim from the effective-tools response. */
  outcome?: ToolOutcome;
  muted?: boolean;
}

export type EdgeKind =
  | 'reports_to'
  | 'delegation'
  | 'session_of'
  | 'member_of'
  | 'binding'
  | 'binding_disabled'
  | 'provides'
  | 'effective_allowed'
  | 'effective_would_deny'
  | 'effective_denied'
  | 'step';

export interface EdgeData {
  kind: EdgeKind;
  /** Domain id the edge stands for, where it is one row (a binding). */
  entityId?: string;
}

export type CanvasNode = Node<EntityData>;
export type CanvasEdge = Edge<EdgeData>;

/** What the canvas knows about the workspace selection (all from the URL). */
export interface ModeContext {
  agentId: string | null;
  sessionId: string | null;
  pipelineId: string | null;
  select: (next: { agent?: string | null; session?: string | null; pipeline?: string | null }) => void;
}

/** A mode's projection of server state, plus the mutations it allows. */
export interface ModeGraph {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  loading: boolean;
  error: unknown;
  /** Shown instead of the graph when the mode has nothing to draw yet. */
  empty?: string;
  toolbar?: ReactNode;
  /**
   * Label for the inspector's connect control (e.g. "Add direct report").
   * Absent = the mode is read-only.
   */
  connectLabel?: string;
  /**
   * A UX pre-check only, so obviously wrong drags are not sent. It grants
   * nothing: the server authorizes and validates every mutation again.
   */
  canConnect?: (connection: Connection) => string | null;
  connect?: (connection: Connection) => Promise<unknown>;
  removeEdge?: (edge: CanvasEdge) => Promise<unknown>;
  toggleEdge?: (edge: CanvasEdge) => Promise<unknown>;
}

export interface CanvasModeDef {
  id: CanvasMode;
  label: string;
  useGraph: (ctx: ModeContext) => ModeGraph;
}
