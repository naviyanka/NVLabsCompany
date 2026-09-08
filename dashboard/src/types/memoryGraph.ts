export type MemoryNodeType =
  | 'agent'
  | 'goal'
  | 'task'
  | 'knowledge'
  | 'fact'
  | 'observation'
  | 'experience'
  | 'decision'
  | 'tool_result'
  | 'derived'
  | 'contradiction';

export type MemoryEdgeType =
  | 'depends_on'
  | 'produced_by'
  | 'supports'
  | 'contradicts'
  | 'derived_from'
  | 'informs'
  | 'part_of'
  | 'temporal_precedes'
  /** A `[[wikilink]]` between two vault notes, read from the vault itself. */
  | 'wikilink';

/** Cluster ids are derived from memory scopes at runtime, not a fixed enum. */
export type MemoryClusterId = string;

export interface MemoryCluster {
  id: MemoryClusterId;
  name: string;
  description: string;
  lead_agent_id: string | null;
  color: string;
  accent_color: string;
}

export interface MemoryGraphNode {
  id: string;
  label: string;
  type: MemoryNodeType;
  community: MemoryClusterId;
  agent_id?: string;
  importance: number; // 0.0 - 1.0
  confidence: number; // 0.0 - 1.0
  created_at: string;
  updated_at: string;
  summary: string;
  raw_content?: string;
  tags: string[];
  embedding_dim?: number;
  embedding_preview?: number[];
  provenance_sources?: string[]; // IDs of input nodes that created this
  contradiction_target_id?: string;
  contradiction_reason?: string;
  decay_score?: number; // 0.0 to 1.0 (1.0 = freshest)
  access_count?: number;
  /**
   * Vault-relative path of the Obsidian note behind this node.
   *
   * Present only on vault nodes, and absent on the derived
   * `obsidian:missing:*` node a dangling wikilink produces — that target has no
   * file, so it has no path. Never an absolute host path: the API deliberately
   * does not expose the vault root.
   */
  vault_path?: string;
  /** Index state of a vault note, or `"missing"` for a dangling target. */
  index_status?: string;
  // Physics coordinates (d3 simulation)
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface MemoryGraphLink {
  id: string;
  source: string | MemoryGraphNode;
  target: string | MemoryGraphNode;
  type: MemoryEdgeType;
  weight: number; // 0.1 - 1.0
  label?: string;
  is_active?: boolean;
  is_contradiction?: boolean;
  confidence?: number;
  provenance_info?: string;
}

export interface MemoryGraphData {
  nodes: MemoryGraphNode[];
  links: MemoryGraphLink[];
  clusters: MemoryCluster[];
  metrics: {
    total_nodes: number;
    total_links: number;
    contradictions_count: number;
    avg_confidence: number;
    avg_importance: number;
    modularity_score: number;
    clustering_coefficient: number;
    memory_recall_rate: number;
    hnsw_index_size_kb: number;
  };
}

export type LayoutMode = 'force' | 'radial' | 'sequential';

export interface GraphFilterState {
  searchQuery: string;
  selectedTypes: Set<MemoryNodeType>;
  selectedClusters: Set<MemoryClusterId>;
  selectedAgent: string; // 'all' or agent ID
  minConfidence: number;
  minImportance: number;
  showOnlyContradictions: boolean;
  timeDecayThreshold: number; // 0 to 100%
  focusNodeId: string | null;
  hopDistance: 1 | 2 | 3;
}
