import React, { useRef, useEffect, useState, useCallback } from 'react';
import * as d3 from 'd3';
import {
  MemoryGraphNode,
  MemoryGraphLink,
  MemoryNodeType,
  LayoutMode,
  GraphFilterState,
  MemoryClusterId,
} from '@/types/memoryGraph';
import { NODE_TYPE_COLORS, EDGE_TYPE_COLORS, MEMORY_CLUSTERS } from '@/lib/memoryGraphAdapter';
import { ShortestPathResult, getLinkKey, normalizeLinkId } from '@/lib/graphPathFinder';

interface MemoryGraphCanvasProps {
  nodes: MemoryGraphNode[];
  links: MemoryGraphLink[];
  layoutMode: LayoutMode;
  filterState: GraphFilterState;
  selectedNodeId: string | null;
  onSelectNode: (node: MemoryGraphNode | null) => void;
  showClusters: boolean;
  showMinimap: boolean;
  animateParticles: boolean;
  physicsStrength: number;
  shortestPath?: ShortestPathResult | null;
  pathSourceNodeId?: string | null;
  pathTargetNodeId?: string | null;
}

export function MemoryGraphCanvas({
  nodes,
  links,
  layoutMode,
  filterState,
  selectedNodeId,
  onSelectNode,
  showClusters,
  showMinimap,
  animateParticles,
  physicsStrength,
  shortestPath,
  pathSourceNodeId,
  pathTargetNodeId,
}: MemoryGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const minimapCanvasRef = useRef<HTMLCanvasElement>(null);

  // Transform state for pan & zoom
  const transformRef = useRef<{ x: number; y: number; k: number }>({ x: 0, y: 0, k: 1 });
  const [hoveredNode, setHoveredNode] = useState<MemoryGraphNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  // Drag state
  const draggingNodeRef = useRef<MemoryGraphNode | null>(null);
  const isPanningRef = useRef(false);
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Simulation ref
  const simulationRef = useRef<d3.Simulation<MemoryGraphNode, MemoryGraphLink> | null>(null);

  // Filtered nodes and links memoized
  const activeNodesRef = useRef<MemoryGraphNode[]>([]);
  const activeLinksRef = useRef<MemoryGraphLink[]>([]);
  const particleOffsetRef = useRef(0);

  // Filter logic
  useEffect(() => {
    let filteredNodes = nodes.filter((node) => {
      // Type filter
      if (filterState.selectedTypes.size > 0 && !filterState.selectedTypes.has(node.type)) {
        return false;
      }
      // Cluster filter
      if (filterState.selectedClusters.size > 0 && !filterState.selectedClusters.has(node.community)) {
        return false;
      }
      // Agent filter
      if (filterState.selectedAgent !== 'all' && node.agent_id !== filterState.selectedAgent) {
        return false;
      }
      // Contradiction filter
      if (filterState.showOnlyContradictions && node.type !== 'contradiction') {
        return false;
      }
      // Confidence & importance filter
      if (node.confidence < filterState.minConfidence) return false;
      if (node.importance < filterState.minImportance) return false;
      // Decay score
      if (node.decay_score !== undefined && node.decay_score < filterState.timeDecayThreshold / 100) {
        return false;
      }
      // Text search
      if (filterState.searchQuery.trim()) {
        const q = filterState.searchQuery.toLowerCase();
        const matchLabel = node.label.toLowerCase().includes(q);
        const matchSummary = node.summary.toLowerCase().includes(q);
        const matchTags = node.tags.some((t) => t.toLowerCase().includes(q));
        if (!matchLabel && !matchSummary && !matchTags) return false;
      }
      return true;
    });

    // If focus node with hop distance is active
    if (filterState.focusNodeId) {
      const focusId = filterState.focusNodeId;
      const hop1 = new Set<string>([focusId]);
      links.forEach((l) => {
        const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
        const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
        if (sId === focusId) hop1.add(tId);
        if (tId === focusId) hop1.add(sId);
      });

      let focusSet = hop1;
      if (filterState.hopDistance >= 2) {
        const hop2 = new Set(hop1);
        links.forEach((l) => {
          const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
          const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
          if (hop1.has(sId)) hop2.add(tId);
          if (hop1.has(tId)) hop2.add(sId);
        });
        focusSet = hop2;
      }

      filteredNodes = filteredNodes.filter((n) => focusSet.has(n.id));
    }

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredLinks = links.filter((l) => {
      const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
      const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
      return nodeIds.has(sId) && nodeIds.has(tId);
    });

    activeNodesRef.current = filteredNodes;
    activeLinksRef.current = filteredLinks;
  }, [nodes, links, filterState]);

  // Layout Computation
  const updateLayout = useCallback(() => {
    if (!containerRef.current) return;
    const width = containerRef.current.clientWidth || 800;
    const height = containerRef.current.clientHeight || 600;
    const activeNodes = activeNodesRef.current;
    const activeLinks = activeLinksRef.current;

    if (simulationRef.current) {
      simulationRef.current.stop();
    }

    if (layoutMode === 'force') {
      // Cluster centroid targets
      const clusterCenters: Record<MemoryClusterId, { x: number; y: number }> = {
        enterprise_governance: { x: width * 0.5, y: height * 0.28 },
        systems_routing: { x: width * 0.26, y: height * 0.45 },
        ai_evolution: { x: width * 0.74, y: height * 0.45 },
        security_audit: { x: width * 0.28, y: height * 0.76 },
        ui_3d_spatial: { x: width * 0.72, y: height * 0.76 },
        infrastructure_ops: { x: width * 0.5, y: height * 0.85 },
      };

      const sim = d3
        .forceSimulation<MemoryGraphNode, MemoryGraphLink>(activeNodes)
        .force(
          'link',
          d3
            .forceLink<MemoryGraphNode, MemoryGraphLink>(activeLinks)
            .id((d) => d.id)
            .distance((d) => (d.type === 'contradicts' ? 140 : 80))
            .strength(0.4 * physicsStrength)
        )
        .force('charge', d3.forceManyBody().strength(-240 * physicsStrength))
        .force('center', d3.forceCenter(width / 2, height / 2).strength(0.08))
        .force('collision', d3.forceCollide().radius(36))
        .force(
          'clusterX',
          d3.forceX<MemoryGraphNode>((d) => clusterCenters[d.community]?.x || width / 2).strength(0.22 * physicsStrength)
        )
        .force(
          'clusterY',
          d3.forceY<MemoryGraphNode>((d) => clusterCenters[d.community]?.y || height / 2).strength(0.22 * physicsStrength)
        )
        .alpha(0.8)
        .restart();

      simulationRef.current = sim;
    } else if (layoutMode === 'radial') {
      // Radial layout: concentric circles based on node type / hierarchy
      const centerX = width / 2;
      const centerY = height / 2;

      // Group nodes by tier: 0 = agent, 1 = goal/kb, 2 = task/decision/derived, 3 = observation/fact/tool/conflict
      const tierRadii: Record<MemoryNodeType, number> = {
        agent: 0,
        goal: 130,
        knowledge: 130,
        decision: 230,
        derived: 230,
        task: 230,
        fact: 330,
        observation: 330,
        tool_result: 330,
        experience: 330,
        contradiction: 380,
      };

      const tierGroups: Record<number, MemoryGraphNode[]> = {};
      activeNodes.forEach((node) => {
        const radius = tierRadii[node.type] || 250;
        if (!tierGroups[radius]) tierGroups[radius] = [];
        tierGroups[radius].push(node);
      });

      Object.entries(tierGroups).forEach(([radStr, group]) => {
        const radius = Number(radStr);
        const count = group.length;
        group.forEach((node, idx) => {
          if (radius === 0) {
            // Circle agents tightly near center
            const angle = (idx / count) * 2 * Math.PI;
            node.x = centerX + Math.cos(angle) * 55;
            node.y = centerY + Math.sin(angle) * 55;
          } else {
            const angle = (idx / count) * 2 * Math.PI - Math.PI / 2;
            node.x = centerX + Math.cos(angle) * radius;
            node.y = centerY + Math.sin(angle) * radius;
          }
          node.vx = 0;
          node.vy = 0;
        });
      });
    } else if (layoutMode === 'sequential') {
      // Sequential flow from raw inputs (left) -> execution/reasoning (middle) -> derived knowledge & strategic goals (right)
      const columnOrder: Record<MemoryNodeType, number> = {
        observation: 0,
        fact: 0,
        tool_result: 0,
        experience: 1,
        contradiction: 1,
        task: 2,
        agent: 2,
        decision: 3,
        derived: 4,
        knowledge: 4,
        goal: 5,
      };

      const columns: Record<number, MemoryGraphNode[]> = {};
      activeNodes.forEach((node) => {
        const col = columnOrder[node.type] ?? 2;
        if (!columns[col]) columns[col] = [];
        columns[col].push(node);
      });

      const colCount = 6;
      const colWidth = (width - 160) / (colCount - 1);

      Object.entries(columns).forEach(([colStr, colNodes]) => {
        const col = Number(colStr);
        const xPos = 80 + col * colWidth;
        const totalInCol = colNodes.length;
        const rowSpacing = Math.min(85, (height - 120) / Math.max(1, totalInCol));
        const startY = height / 2 - ((totalInCol - 1) * rowSpacing) / 2;

        colNodes.forEach((node, idx) => {
          node.x = xPos;
          node.y = startY + idx * rowSpacing;
          node.vx = 0;
          node.vy = 0;
        });
      });
    }
  }, [layoutMode, physicsStrength]);

  useEffect(() => {
    updateLayout();
  }, [updateLayout, nodes, links, filterState]);

  // Main Render Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animFrameId: number;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Save transform
      ctx.save();
      const { x, y, k } = transformRef.current;
      ctx.translate(x, y);
      ctx.scale(k, k);

      // 1. Draw Grid Background
      const gridSize = 40;
      const startX = -x / k - gridSize;
      const startY = -y / k - gridSize;
      const endX = (width - x) / k + gridSize;
      const endY = (height - y) / k + gridSize;

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.025)';
      ctx.lineWidth = 1 / k;
      ctx.beginPath();
      for (let gx = Math.floor(startX / gridSize) * gridSize; gx <= endX; gx += gridSize) {
        ctx.moveTo(gx, startY);
        ctx.lineTo(gx, endY);
      }
      for (let gy = Math.floor(startY / gridSize) * gridSize; gy <= endY; gy += gridSize) {
        ctx.moveTo(startX, gy);
        ctx.lineTo(endX, gy);
      }
      ctx.stroke();

      const activeNodes = activeNodesRef.current;
      const activeLinks = activeLinksRef.current;

      // 2. Draw Cluster Hull Halos if enabled
      if (showClusters && layoutMode === 'force') {
        const clusterGroups: Record<string, { x: number; y: number; count: number; color: string; name: string }> = {};
        MEMORY_CLUSTERS.forEach((c) => {
          clusterGroups[c.id] = { x: 0, y: 0, count: 0, color: c.color, name: c.name };
        });

        activeNodes.forEach((n) => {
          const grp = clusterGroups[n.community];
          if (n.x !== undefined && n.y !== undefined && grp) {
            grp.x += n.x;
            grp.y += n.y;
            grp.count++;
          }
        });

        Object.entries(clusterGroups).forEach(([, data]) => {
          if (data.count > 0) {
            const avgX = data.x / data.count;
            const avgY = data.y / data.count;
            const radius = Math.max(120, Math.sqrt(data.count) * 65);

            const grad = ctx.createRadialGradient(avgX, avgY, 10, avgX, avgY, radius);
            grad.addColorStop(0, `${data.color}18`);
            grad.addColorStop(0.7, `${data.color}06`);
            grad.addColorStop(1, 'rgba(0,0,0,0)');

            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(avgX, avgY, radius, 0, Math.PI * 2);
            ctx.fill();

            // Cluster boundary outline
            ctx.strokeStyle = `${data.color}24`;
            ctx.setLineDash([4, 4]);
            ctx.lineWidth = 1 / k;
            ctx.stroke();
            ctx.setLineDash([]);

            // Cluster Label
            ctx.font = '10px "JetBrains Mono", monospace';
            ctx.fillStyle = `${data.color}88`;
            ctx.textAlign = 'center';
            ctx.fillText(data.name.toUpperCase(), avgX, avgY - radius + 15);
          }
        });
      }

      // 3. Draw Links
      particleOffsetRef.current = (particleOffsetRef.current + 0.008) % 1;

      const hasShortestPath = Boolean(shortestPath?.found && shortestPath.links.length > 0);
      const pathNodeIds = shortestPath?.nodeIds || new Set<string>();
      const pathLinkKeys = shortestPath?.linkKeys || new Set<string>();

      activeLinks.forEach((link) => {
        const source = typeof link.source === 'object' ? link.source : activeNodes.find((n) => n.id === link.source);
        const target = typeof link.target === 'object' ? link.target : activeNodes.find((n) => n.id === link.target);

        if (!source || !target || source.x === undefined || source.y === undefined || target.x === undefined || target.y === undefined) {
          return;
        }

        const { sourceId, targetId } = normalizeLinkId(link);
        const linkKey = link.id || getLinkKey(sourceId, targetId);
        const isPathEdge = hasShortestPath && pathLinkKeys.has(linkKey);

        const isHighlighted =
          isPathEdge ||
          selectedNodeId === source.id ||
          selectedNodeId === target.id ||
          hoveredNode?.id === source.id ||
          hoveredNode?.id === target.id;

        const edgeConfig = EDGE_TYPE_COLORS[link.type] || { stroke: '#6B6B6E', style: 'solid' };
        let strokeColor = edgeConfig.stroke;

        if (link.is_contradiction) {
          strokeColor = '#EF4444';
        }

        // Shortest path link glow and styling
        if (isPathEdge) {
          // Path background glow
          ctx.strokeStyle = 'rgba(255, 176, 32, 0.35)';
          ctx.lineWidth = 8 / k;
          ctx.beginPath();
          ctx.moveTo(source.x, source.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();

          // Main path line
          ctx.strokeStyle = '#FFB020';
          ctx.lineWidth = 3.5 / k;
          ctx.setLineDash([]);
        } else if (hasShortestPath) {
          // Dim other links when shortest path is active
          ctx.strokeStyle = `${strokeColor}20`;
          ctx.lineWidth = 0.8 / k;
          if (edgeConfig.style === 'dashed' || link.is_contradiction) {
            ctx.setLineDash([4 / k, 4 / k]);
          } else {
            ctx.setLineDash([]);
          }
        } else {
          ctx.strokeStyle = isHighlighted ? strokeColor : `${strokeColor}55`;
          ctx.lineWidth = (isHighlighted ? 2.5 : link.is_contradiction ? 2 : 1.2) / k;
          if (edgeConfig.style === 'dashed' || link.is_contradiction) {
            ctx.setLineDash([6 / k, 4 / k]);
          } else {
            ctx.setLineDash([]);
          }
        }

        // Draw line
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Animated Particle Pulse along active links
        if (animateParticles && (isPathEdge || link.is_active || link.is_contradiction || isHighlighted)) {
          const t = (particleOffsetRef.current + (link.weight || 0.5)) % 1;
          const px = source.x + (target.x - source.x) * t;
          const py = source.y + (target.y - source.y) * t;

          ctx.fillStyle = isPathEdge ? '#38BDF8' : link.is_contradiction ? '#EF4444' : '#FFB020';
          ctx.beginPath();
          ctx.arc(px, py, (isPathEdge ? 4 : link.is_contradiction ? 3.5 : 2.5) / k, 0, Math.PI * 2);
          ctx.fill();

          // If on shortest path, draw secondary trailing beam
          if (isPathEdge) {
            const t2 = (t + 0.5) % 1;
            const px2 = source.x + (target.x - source.x) * t2;
            const py2 = source.y + (target.y - source.y) * t2;
            ctx.fillStyle = '#FFB020';
            ctx.beginPath();
            ctx.arc(px2, py2, 3 / k, 0, Math.PI * 2);
            ctx.fill();
          }
        }

        // Edge label if selected, hovered, or on shortest path
        if ((isHighlighted || isPathEdge) && link.label) {
          const midX = (source.x + target.x) / 2;
          const midY = (source.y + target.y) / 2;
          ctx.font = `${Math.max(9, 10 / k)}px "JetBrains Mono", monospace`;
          ctx.fillStyle = isPathEdge ? '#FFB020' : '#A8A8AB';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(link.label, midX, midY - (isPathEdge ? 8 : 6) / k);
        }
      });

      // 4. Draw Nodes
      activeNodes.forEach((node) => {
        if (node.x === undefined || node.y === undefined) return;

        const isSelected = selectedNodeId === node.id;
        const isHovered = hoveredNode?.id === node.id;
        const isPathNode = hasShortestPath && pathNodeIds.has(node.id);
        const isPathSource = pathSourceNodeId === node.id;
        const isPathTarget = pathTargetNodeId === node.id;
        const colors = NODE_TYPE_COLORS[node.type] || { bg: '#FFB020', border: '#F59E0B', text: '#0A0A0B', glow: 'rgba(255,176,32,0.4)' };

        // Node size based on importance & type
        let baseRadius = node.type === 'agent' ? 22 : node.type === 'goal' || node.type === 'knowledge' ? 18 : 14;
        baseRadius = baseRadius * (0.85 + (node.importance || 0.5) * 0.3);

        // Dim background nodes if shortest path is active and node is not in path
        const isDimmed = hasShortestPath && !isPathNode && !isSelected && !isHovered;

        // Glow ring for selected, path endpoints, path nodes, or contradiction
        if (isPathSource || isPathTarget || isPathNode || isSelected || isHovered || node.type === 'contradiction') {
          let glowColor = colors.glow;
          if (isPathSource) glowColor = 'rgba(56, 189, 248, 0.45)';
          else if (isPathTarget) glowColor = 'rgba(255, 176, 32, 0.45)';
          else if (isPathNode) glowColor = 'rgba(255, 176, 32, 0.3)';
          else if (isSelected) glowColor = 'rgba(255, 176, 32, 0.25)';
          else if (node.type === 'contradiction') glowColor = 'rgba(239, 68, 68, 0.3)';

          ctx.fillStyle = glowColor;
          ctx.beginPath();
          ctx.arc(node.x, node.y, baseRadius + ((isPathSource || isPathTarget) ? 9 : 7) / k, 0, Math.PI * 2);
          ctx.fill();

          if (isPathSource || isPathTarget || isSelected) {
            ctx.strokeStyle = isPathSource ? '#38BDF8' : '#FFB020';
            ctx.lineWidth = ((isPathSource || isPathTarget) ? 2.5 : 2) / k;
            ctx.beginPath();
            ctx.arc(node.x, node.y, baseRadius + 4 / k, 0, Math.PI * 2);
            ctx.stroke();
          }
        }

        // Node Body Circle
        ctx.fillStyle = isDimmed ? `${colors.bg}40` : colors.bg;
        ctx.beginPath();
        ctx.arc(node.x, node.y, baseRadius, 0, Math.PI * 2);
        ctx.fill();

        // Node Border
        ctx.strokeStyle = isPathSource ? '#38BDF8' : isPathTarget ? '#FFB020' : isSelected ? '#FFFFFF' : isDimmed ? `${colors.border}40` : colors.border;
        ctx.lineWidth = (isPathSource || isPathTarget || isSelected ? 2.2 : 1.2) / k;
        ctx.beginPath();
        ctx.arc(node.x, node.y, baseRadius, 0, Math.PI * 2);
        ctx.stroke();

        // Origin (A) / Destination (B) Pin Badge Above Node
        if (isPathSource || isPathTarget) {
          const badgeX = node.x;
          const badgeY = node.y - baseRadius - 12 / k;
          ctx.fillStyle = isPathSource ? '#38BDF8' : '#FFB020';
          ctx.beginPath();
          ctx.arc(badgeX, badgeY, 7 / k, 0, Math.PI * 2);
          ctx.fill();

          ctx.font = `bold ${Math.max(7, 8 / k)}px sans-serif`;
          ctx.fillStyle = '#0A0A0B';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(isPathSource ? 'A' : 'B', badgeX, badgeY);
        }

        // Inner Type Initial or Glyph
        ctx.font = `bold ${Math.max(8, (baseRadius * 0.7))}px sans-serif`;
        ctx.fillStyle = isDimmed ? 'rgba(0,0,0,0.3)' : colors.text;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        const glyphMap: Record<MemoryNodeType, string> = {
          agent: '⚡',
          goal: '🎯',
          task: '✓',
          knowledge: '📚',
          fact: '📌',
          observation: '👁',
          experience: '🧠',
          decision: '⚖',
          tool_result: '🛠',
          derived: '💡',
          contradiction: '⚠',
        };
        const initial = glyphMap[node.type] || (node.type ? node.type[0]?.toUpperCase() || 'M' : 'M');
        ctx.fillText(initial, node.x, node.y + (glyphMap[node.type] ? -1 : 1));

        // Node Label below
        ctx.font = `${Math.max(9, 10 / k)}px "Inter", sans-serif`;
        ctx.fillStyle = (isPathSource || isPathTarget) ? '#38BDF8' : isSelected ? '#FFB020' : isDimmed ? '#6B6B6E66' : '#F2F1EE';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        // Truncate long label for readability
        const maxLen = 22;
        const displayLabel = node.label.length > maxLen ? `${node.label.substring(0, maxLen)}...` : node.label;
        ctx.fillText(displayLabel, node.x, node.y + baseRadius + 4 / k);

        // Subtitle (Type pill)
        ctx.font = `${Math.max(8, 8.5 / k)}px "JetBrains Mono", monospace`;
        ctx.fillStyle = isDimmed ? '#6B6B6E33' : '#6B6B6E';
        ctx.fillText(node.type.toUpperCase(), node.x, node.y + baseRadius + 16 / k);
      });

      ctx.restore();

      // Render Minimap if enabled
      if (showMinimap && minimapCanvasRef.current) {
        renderMinimap(activeNodes);
      }

      animFrameId = requestAnimationFrame(render);
    };

    animFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animFrameId);
    };
  }, [layoutMode, selectedNodeId, hoveredNode, showClusters, showMinimap, animateParticles, shortestPath, pathSourceNodeId, pathTargetNodeId]);

  // Minimap Renderer
  const renderMinimap = (activeNodes: MemoryGraphNode[]) => {
    const miniCanvas = minimapCanvasRef.current;
    if (!miniCanvas) return;
    const miniCtx = miniCanvas.getContext('2d');
    if (!miniCtx) return;

    miniCtx.clearRect(0, 0, miniCanvas.width, miniCanvas.height);
    miniCtx.fillStyle = '#101012';
    miniCtx.fillRect(0, 0, miniCanvas.width, miniCanvas.height);

    if (activeNodes.length === 0) return;

    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    activeNodes.forEach((n) => {
      if (n.x !== undefined && n.y !== undefined) {
        minX = Math.min(minX, n.x);
        maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y);
        maxY = Math.max(maxY, n.y);
      }
    });

    const pad = 60;
    const boundW = Math.max(100, maxX - minX + pad * 2);
    const boundH = Math.max(100, maxY - minY + pad * 2);
    const scale = Math.min((miniCanvas.width - 10) / boundW, (miniCanvas.height - 10) / boundH);

    activeNodes.forEach((n) => {
      if (n.x !== undefined && n.y !== undefined) {
        const mx = 5 + (n.x - minX + pad) * scale;
        const my = 5 + (n.y - minY + pad) * scale;
        const color = NODE_TYPE_COLORS[n.type]?.bg || '#FFB020';
        miniCtx.fillStyle = n.id === selectedNodeId ? '#FFFFFF' : color;
        miniCtx.beginPath();
        miniCtx.arc(mx, my, n.id === selectedNodeId ? 3.5 : 2, 0, Math.PI * 2);
        miniCtx.fill();
      }
    });

    // Viewport box
    if (containerRef.current) {
      const cw = containerRef.current.clientWidth;
      const ch = containerRef.current.clientHeight;
      const { x, y, k } = transformRef.current;
      const vx1 = 5 + (-x / k - minX + pad) * scale;
      const vy1 = 5 + (-y / k - minY + pad) * scale;
      const vw = (cw / k) * scale;
      const vh = (ch / k) * scale;

      miniCtx.strokeStyle = '#FFB020';
      miniCtx.lineWidth = 1;
      miniCtx.strokeRect(vx1, vy1, vw, vh);
    }
  };

  // Canvas Resize Handler with ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const updateDimensions = () => {
      if (!containerRef.current || !canvasRef.current) return;
      const dpr = window.devicePixelRatio || 1;
      const width = containerRef.current.clientWidth || 800;
      const height = containerRef.current.clientHeight || 600;

      canvasRef.current.width = width * dpr;
      canvasRef.current.height = height * dpr;
      canvasRef.current.style.width = `${width}px`;
      canvasRef.current.style.height = `${height}px`;

      const ctx = canvasRef.current.getContext('2d');
      if (ctx) ctx.scale(dpr, dpr);
    };

    updateDimensions();

    const resizeObserver = new ResizeObserver(() => {
      updateDimensions();
    });

    resizeObserver.observe(container);
    window.addEventListener('resize', updateDimensions);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateDimensions);
    };
  }, []);

  // Node Finding under Mouse Screen Coord
  const findNodeAtPosition = (screenX: number, screenY: number): MemoryGraphNode | null => {
    const { x, y, k } = transformRef.current;
    const worldX = (screenX - x) / k;
    const worldY = (screenY - y) / k;

    const activeNodes = activeNodesRef.current;
    for (let i = activeNodes.length - 1; i >= 0; i--) {
      const node = activeNodes[i];
      if (node && node.x !== undefined && node.y !== undefined) {
        const radius = (node.type === 'agent' ? 22 : 16) + 6;
        const dx = worldX - node.x;
        const dy = worldY - node.y;
        if (dx * dx + dy * dy <= radius * radius) {
          return node;
        }
      }
    }
    return null;
  };

  // Mouse Interaction Handlers
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const hitNode = findNodeAtPosition(mouseX, mouseY);
    if (hitNode) {
      draggingNodeRef.current = hitNode;
      hitNode.fx = hitNode.x;
      hitNode.fy = hitNode.y;
      if (simulationRef.current) {
        simulationRef.current.alphaTarget(0.3).restart();
      }
    } else {
      isPanningRef.current = true;
      panStartRef.current = { x: mouseX - transformRef.current.x, y: mouseY - transformRef.current.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    if (draggingNodeRef.current) {
      const { x, y, k } = transformRef.current;
      draggingNodeRef.current.fx = (mouseX - x) / k;
      draggingNodeRef.current.fy = (mouseY - y) / k;
      draggingNodeRef.current.x = draggingNodeRef.current.fx;
      draggingNodeRef.current.y = draggingNodeRef.current.fy;
    } else if (isPanningRef.current) {
      transformRef.current.x = mouseX - panStartRef.current.x;
      transformRef.current.y = mouseY - panStartRef.current.y;
    } else {
      const node = findNodeAtPosition(mouseX, mouseY);
      setHoveredNode(node);
      if (node) {
        setTooltipPos({ x: e.clientX, y: e.clientY });
      } else {
        setTooltipPos(null);
      }
    }
  };

  const handleMouseUp = () => {
    if (draggingNodeRef.current) {
      draggingNodeRef.current.fx = null;
      draggingNodeRef.current.fy = null;
      draggingNodeRef.current = null;
      if (simulationRef.current) {
        simulationRef.current.alphaTarget(0);
      }
    }
    if (isPanningRef.current) {
      isPanningRef.current = false;
    }
  };

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const hitNode = findNodeAtPosition(mouseX, mouseY);
    onSelectNode(hitNode);
  };

  // Wheel Zoom
  const handleWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;

    const { x, y, k } = transformRef.current;
    const newK = Math.max(0.2, Math.min(4.0, k * zoomFactor));

    // Zoom centered around mouse
    transformRef.current = {
      k: newK,
      x: mouseX - (mouseX - x) * (newK / k),
      y: mouseY - (mouseY - y) * (newK / k),
    };
  };

  // Reset view to fit all nodes
  const fitView = useCallback(() => {
    if (!containerRef.current) return;
    const activeNodes = activeNodesRef.current;
    if (activeNodes.length === 0) return;

    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    activeNodes.forEach((n) => {
      if (n.x !== undefined && n.y !== undefined) {
        minX = Math.min(minX, n.x);
        maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y);
        maxY = Math.max(maxY, n.y);
      }
    });

    const pad = 80;
    const w = maxX - minX + pad * 2;
    const h = maxY - minY + pad * 2;
    const cw = containerRef.current.clientWidth;
    const ch = containerRef.current.clientHeight;

    const k = Math.max(0.3, Math.min(1.8, Math.min(cw / w, ch / h)));
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    transformRef.current = {
      k,
      x: cw / 2 - centerX * k,
      y: ch / 2 - centerY * k,
    };
  }, []);

  // Listen for custom fit-view event
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handleFit = () => fitView();
    el.addEventListener('fit-view', handleFit);
    return () => el.removeEventListener('fit-view', handleFit);
  }, [fitView]);

  return (
    <div
      ref={containerRef}
      id="memory-graph-canvas-container"
      className="relative w-full h-full bg-[#0E0E10] overflow-hidden select-none cursor-grab active:cursor-grabbing rounded-[8px] border border-white/[0.08]"
    >
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onClick={handleClick}
        onWheel={handleWheel}
        className="w-full h-full block"
      />

      {/* Floating Hover Tooltip */}
      {hoveredNode && tooltipPos && (
        <div
          className="fixed pointer-events-none z-50 px-3 py-2 bg-[#141416]/95 backdrop-blur-md border border-white/[0.12] rounded-[6px] shadow-2xl text-xs max-w-xs transition-opacity duration-150"
          style={{
            left: `${tooltipPos.x + 14}px`,
            top: `${tooltipPos.y + 14}px`,
          }}
        >
          <div className="flex items-center justify-between gap-2 pb-1 border-b border-white/[0.08]">
            <span
              className="text-[10px] font-mono font-medium uppercase px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: `${NODE_TYPE_COLORS[hoveredNode.type]?.bg}22`,
                color: NODE_TYPE_COLORS[hoveredNode.type]?.bg || '#FFB020',
              }}
            >
              {hoveredNode.type}
            </span>
            <span className="text-[10px] font-mono text-[#22C55E]">
              {Math.round(hoveredNode.confidence * 100)}% Conf
            </span>
          </div>
          <div className="font-sans font-medium text-[#F2F1EE] mt-1 text-[13px]">
            {hoveredNode.label}
          </div>
          <p className="text-[11px] text-[#A8A8AB] leading-tight mt-1">
            {hoveredNode.summary}
          </p>
          <div className="flex items-center justify-between text-[10px] font-mono text-[#6B6B6E] mt-2 pt-1 border-t border-white/[0.04]">
            <span>Agent: {hoveredNode.agent_id || 'System'}</span>
            <span>Weight: {(hoveredNode.importance * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}

      {/* Floating Minimap */}
      {showMinimap && (
        <div className="absolute bottom-4 right-4 z-20 bg-[#101012]/90 backdrop-blur-md border border-white/[0.12] rounded-[6px] p-1.5 shadow-xl">
          <canvas ref={minimapCanvasRef} width={130} height={90} className="rounded" />
          <div className="text-[9px] font-mono text-[#6B6B6E] text-center mt-1">
            CANVAS RADAR
          </div>
        </div>
      )}
    </div>
  );
}
