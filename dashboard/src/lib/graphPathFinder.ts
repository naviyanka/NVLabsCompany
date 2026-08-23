import { MemoryGraphNode, MemoryGraphLink } from '@/types/memoryGraph';

export interface PathStep {
  node: MemoryGraphNode;
  viaLink?: MemoryGraphLink;
  direction?: 'outgoing' | 'incoming';
}

export interface ShortestPathResult {
  sourceId: string;
  targetId: string;
  found: boolean;
  nodes: MemoryGraphNode[];
  nodeIds: Set<string>;
  links: MemoryGraphLink[];
  linkKeys: Set<string>;
  totalHops: number;
  totalDistance: number;
  steps: PathStep[];
}

export function getLinkKey(sourceId: string, targetId: string, linkId?: string): string {
  if (linkId) return linkId;
  return `${sourceId}-->${targetId}`;
}

export function normalizeLinkId(link: MemoryGraphLink): { sourceId: string; targetId: string } {
  const sourceId = typeof link.source === 'object' ? (link.source as MemoryGraphNode).id : link.source;
  const targetId = typeof link.target === 'object' ? (link.target as MemoryGraphNode).id : link.target;
  return { sourceId, targetId };
}

/**
 * Finds the shortest path between startNodeId and targetNodeId using Breadth-First Search (BFS)
 * or weighted Dijkstra considering link weights. Treats edges as undirected or directed.
 * In a knowledge graph, finding connection chains often navigates bidirectional relationships
 * to uncover indirect dependencies.
 */
export function findShortestPath(
  nodes: MemoryGraphNode[],
  links: MemoryGraphLink[],
  startNodeId: string,
  targetNodeId: string,
  directed: boolean = false
): ShortestPathResult {
  const emptyResult: ShortestPathResult = {
    sourceId: startNodeId,
    targetId: targetNodeId,
    found: false,
    nodes: [],
    nodeIds: new Set(),
    links: [],
    linkKeys: new Set(),
    totalHops: 0,
    totalDistance: 0,
    steps: [],
  };

  if (!startNodeId || !targetNodeId || startNodeId === targetNodeId) {
    const singleNode = nodes.find((n) => n.id === startNodeId);
    if (singleNode) {
      return {
        sourceId: startNodeId,
        targetId: targetNodeId,
        found: true,
        nodes: [singleNode],
        nodeIds: new Set([startNodeId]),
        links: [],
        linkKeys: new Set(),
        totalHops: 0,
        totalDistance: 0,
        steps: [{ node: singleNode }],
      };
    }
    return emptyResult;
  }

  const nodeMap = new Map<string, MemoryGraphNode>();
  nodes.forEach((n) => nodeMap.set(n.id, n));

  if (!nodeMap.has(startNodeId) || !nodeMap.has(targetNodeId)) {
    return emptyResult;
  }

  // Build Adjacency List
  interface AdjEdge {
    neighborId: string;
    link: MemoryGraphLink;
    direction: 'outgoing' | 'incoming';
    weight: number;
  }

  const adj = new Map<string, AdjEdge[]>();
  nodes.forEach((n) => adj.set(n.id, []));

  links.forEach((link) => {
    const { sourceId, targetId } = normalizeLinkId(link);
    if (!adj.has(sourceId)) adj.set(sourceId, []);
    if (!adj.has(targetId)) adj.set(targetId, []);

    // Base weight is inverse of confidence or connection weight (default 1)
    const weight = link.weight ? Math.max(0.2, 1.2 - link.weight) : 1;

    adj.get(sourceId)!.push({
      neighborId: targetId,
      link,
      direction: 'outgoing',
      weight,
    });

    if (!directed) {
      adj.get(targetId)!.push({
        neighborId: sourceId,
        link,
        direction: 'incoming',
        weight,
      });
    }
  });

  // BFS with predecessor tracking
  interface QueueItem {
    nodeId: string;
    dist: number;
  }

  const visited = new Set<string>([startNodeId]);
  const parentMap = new Map<
    string,
    { parentId: string; link: MemoryGraphLink; direction: 'outgoing' | 'incoming'; cost: number }
  >();

  const queue: QueueItem[] = [{ nodeId: startNodeId, dist: 0 }];
  let found = false;

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (current.nodeId === targetNodeId) {
      found = true;
      break;
    }

    const neighbors = adj.get(current.nodeId) || [];
    for (const edge of neighbors) {
      if (!visited.has(edge.neighborId)) {
        visited.add(edge.neighborId);
        parentMap.set(edge.neighborId, {
          parentId: current.nodeId,
          link: edge.link,
          direction: edge.direction,
          cost: edge.weight,
        });
        queue.push({
          nodeId: edge.neighborId,
          dist: current.dist + 1,
        });
      }
    }
  }

  if (!found) {
    return emptyResult;
  }

  // Reconstruct path from target to start
  const pathNodeIds: string[] = [];
  const pathLinks: MemoryGraphLink[] = [];
  const pathLinkKeys = new Set<string>();
  const steps: PathStep[] = [];
  let currId = targetNodeId;
  let totalDistance = 0;

  const backtrackSteps: PathStep[] = [];

  while (currId !== startNodeId) {
    const parentInfo = parentMap.get(currId);
    if (!parentInfo) break;

    const nodeObj = nodeMap.get(currId);
    if (nodeObj) {
      backtrackSteps.unshift({
        node: nodeObj,
        viaLink: parentInfo.link,
        direction: parentInfo.direction,
      });
    }

    pathNodeIds.unshift(currId);
    pathLinks.unshift(parentInfo.link);
    const { sourceId, targetId } = normalizeLinkId(parentInfo.link);
    pathLinkKeys.add(parentInfo.link.id || getLinkKey(sourceId, targetId));
    totalDistance += parentInfo.cost;

    currId = parentInfo.parentId;
  }

  // Add start node at beginning
  pathNodeIds.unshift(startNodeId);
  const startNodeObj = nodeMap.get(startNodeId);
  if (startNodeObj) {
    steps.push({ node: startNodeObj });
  }
  steps.push(...backtrackSteps);

  const pathNodes = pathNodeIds.map((id) => nodeMap.get(id)!).filter(Boolean);

  return {
    sourceId: startNodeId,
    targetId: targetNodeId,
    found: true,
    nodes: pathNodes,
    nodeIds: new Set(pathNodeIds),
    links: pathLinks,
    linkKeys: pathLinkKeys,
    totalHops: pathLinks.length,
    totalDistance,
    steps,
  };
}
