/**
 * The four Canvas modes. Each is a projection of existing domain reads into
 * nodes and edges, plus the existing API calls its relationships map to.
 * None of them decides anything: validation here only spares an obviously
 * wrong request, and every mutation is authorized again by the server.
 */

import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { listAgents } from '@/api/agents';
import {
  canvasKeys,
  createBinding,
  deleteBinding,
  getAgentEffectiveTools,
  listAgentBindings,
  listConnectionTools,
  listDelegations,
  listDepartments,
  listPipelines,
  listTeams,
  listToolConnections,
  setBindingStatus,
  setManager,
} from '@/api/canvas';
import {
  getSessionEffectiveTools,
  listSessionBindings,
  listSessions,
  sessionKeys,
  type EffectiveTool,
  type McpBinding,
} from '@/api/sessions';
import type { Agent } from '@/types/agent';
import { EDGE_STYLES, edge, placeByRank } from './registry';
import type {
  CanvasEdge,
  CanvasMode,
  CanvasModeDef,
  CanvasNode,
  EntityData,
  ModeContext,
  ModeGraph,
  ToolOutcome,
} from './types';

const agentNode = (id: string) => `agent:${id}`;
const sessionNode = (id: string) => `session:${id}`;
const connectionNode = (id: string) => `connection:${id}`;
const toolNode = (connectionId: string, name: string) => `tool:${connectionId}:${name}`;

/** The raw domain id behind a node id such as `agent:<uuid>`. */
function entityOf(nodeId: string | null, kind: string): string | null {
  return nodeId?.startsWith(`${kind}:`) ? nodeId.slice(kind.length + 1) : null;
}

function entity(id: string, data: EntityData, position = { x: 0, y: 0 }): CanvasNode {
  return { id, type: 'entity', position, data };
}

function useAgents() {
  return useQuery({ queryKey: canvasKeys.agents(), queryFn: listAgents });
}

/** Depth below the top of the reporting line; a cycle in bad data stops the walk. */
function managerDepth(agents: Agent[]): Map<string, number> {
  const byId = new Map(agents.map((a) => [a.id, a]));
  const depth = new Map<string, number>();
  for (const a of agents) {
    let d = 0;
    const seen = new Set([a.id]);
    for (let m = a.manager_id; m && byId.has(m) && !seen.has(m); m = byId.get(m)!.manager_id) {
      seen.add(m);
      d += 1;
    }
    depth.set(a.id, d);
  }
  return depth;
}

function reportingEdges(agents: Agent[]): CanvasEdge[] {
  const ids = new Set(agents.map((a) => a.id));
  return agents
    .filter((a) => a.manager_id && ids.has(a.manager_id))
    .map((a) =>
      edge(`reports:${a.id}`, agentNode(a.manager_id!), agentNode(a.id), 'reports_to', {
        entityId: a.id,
        deletable: true,
      })
    );
}

/** A reporting line is `manager -> report`; it is the agent's `manager_id`. */
function reportingMutations(agents: Agent[]): Pick<ModeGraph, 'connectLabel' | 'canConnect' | 'connect' | 'removeEdge'> {
  return {
    connectLabel: 'Add direct report',
    canConnect: ({ source, target }) => {
      const manager = entityOf(source, 'agent');
      const report = entityOf(target, 'agent');
      if (!manager || !report) return 'A reporting line joins two agents.';
      if (manager === report) return 'An agent cannot report to itself.';
      if (agents.find((a) => a.id === report)?.manager_id === manager) return 'Already reports to this agent.';
      return null;
    },
    connect: ({ source, target }) => setManager(entityOf(target, 'agent')!, entityOf(source, 'agent')!),
    removeEdge: (e) => setManager(e.data!.entityId!, null),
  };
}

function agentEntity(a: Agent): EntityData {
  return { kind: 'agent', entityId: a.id, label: a.name, subtitle: a.title || a.role, muted: a.status === 'terminated' };
}

/* ── Workflow ───────────────────────────────────────────────────────────── */

function useWorkflow(ctx: ModeContext): ModeGraph {
  const pipelines = useQuery({ queryKey: canvasKeys.pipelines(), queryFn: listPipelines });
  const agents = useAgents();
  const pipeline = pipelines.data?.find((p) => p.id === ctx.pipelineId) ?? pipelines.data?.[0] ?? null;

  const nodes = useMemo(() => {
    if (!pipeline) return [];
    const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]));
    // Read-only entity nodes: the builder's own nodes carry a delete action,
    // and the Canvas never edits a pipeline (the builder does).
    const trigger = entity('trigger', {
      kind: 'pipeline',
      entityId: pipeline.id,
      label: pipeline.name,
      subtitle: `trigger: ${pipeline.trigger_type ?? 'manual'}`,
      muted: !pipeline.is_active,
    });
    const stages = pipeline.stages.map((s, i) => {
      const agentId = s.agent_id ?? null;
      return entity(
        `stage-${i}`,
        {
          kind: 'stage',
          entityId: `${pipeline.id}:${i}`,
          label: s.name ?? `Stage ${i + 1}`,
          subtitle: (agentId && names.get(agentId)) || s.assignedAgent || undefined,
        },
        { x: (i + 1) * 280, y: 0 }
      );
    });
    return [trigger, ...stages];
  }, [pipeline, agents.data]);

  const edges = useMemo(
    () => nodes.slice(1).map((n, i) => edge(`step:${i}`, nodes[i]!.id, n.id, 'step')),
    [nodes]
  );

  return {
    nodes,
    edges,
    loading: pipelines.isLoading,
    error: pipelines.error,
    empty: pipelines.data && !pipeline ? 'No pipelines yet.' : undefined,
    toolbar: (
      <>
        {pipelines.data && pipelines.data.length > 0 && (
          <select
            aria-label="Pipeline"
            value={pipeline?.id ?? ''}
            onChange={(e) => ctx.select({ pipeline: e.target.value })}
            className="bg-[#141416] border border-white/[0.08] rounded px-2 py-1 text-xs text-[#F2F1EE]"
          >
            {pipelines.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <Link to="/pipelines" className="text-xs text-[#38BDF8]">
          Edit in the pipeline builder
        </Link>
      </>
    ),
  };
}

/* ── Agent Network ─────────────────────────────────────────────────────── */

function useNetwork(ctx: ModeContext): ModeGraph {
  const agents = useAgents();
  // Delegations are advisory context; if the log is unavailable the network still draws.
  const delegations = useQuery({ queryKey: canvasKeys.delegations(), queryFn: listDelegations });
  const sessions = useQuery({
    queryKey: sessionKeys.list(ctx.agentId ?? undefined),
    queryFn: () => listSessions(ctx.agentId!),
    enabled: !!ctx.agentId,
  });

  const list = useMemo(() => agents.data ?? [], [agents.data]);
  const nodes = useMemo(() => {
    const depth = managerDepth(list);
    const maxDepth = Math.max(0, ...depth.values());
    const own = ctx.agentId ? (sessions.data ?? []) : [];
    const pos = placeByRank([
      ...list.map((a) => ({ id: agentNode(a.id), rank: depth.get(a.id)! })),
      ...own.map((s) => ({ id: sessionNode(s.id), rank: maxDepth + 1 })),
    ]);
    return [
      ...list.map((a) => entity(agentNode(a.id), agentEntity(a), pos.get(agentNode(a.id)))),
      ...own.map((s) =>
        entity(
          sessionNode(s.id),
          { kind: 'session', entityId: s.id, label: s.title || `Session ${s.id.slice(0, 8)}`, subtitle: s.status },
          pos.get(sessionNode(s.id))
        )
      ),
    ];
  }, [list, sessions.data, ctx.agentId]);

  const edges = useMemo(() => {
    const ids = new Set(list.map((a) => a.id));
    return [
      ...reportingEdges(list),
      ...(delegations.data ?? [])
        .filter((d) => ids.has(d.from_agent_id) && ids.has(d.to_agent_id))
        .map((d) => edge(`delegation:${d.id}`, agentNode(d.from_agent_id), agentNode(d.to_agent_id), 'delegation')),
      ...(ctx.agentId ? (sessions.data ?? []) : []).map((s) =>
        edge(`session-of:${s.id}`, agentNode(s.agent_id), sessionNode(s.id), 'session_of')
      ),
    ];
  }, [list, delegations.data, sessions.data, ctx.agentId]);

  return {
    nodes,
    edges,
    loading: agents.isLoading,
    error: agents.error,
    empty: agents.data?.length === 0 ? 'No agents yet.' : undefined,
    ...reportingMutations(list),
  };
}

/* ── Context / MCP ─────────────────────────────────────────────────────── */

function useContextMode(ctx: ModeContext): ModeGraph {
  const { agentId, sessionId } = ctx;
  const agents = useAgents();
  const connections = useQuery({ queryKey: canvasKeys.connections(), queryFn: listToolConnections });
  const agentBindings = useQuery({
    queryKey: canvasKeys.agentBindings(agentId ?? ''),
    queryFn: () => listAgentBindings(agentId!),
    enabled: !!agentId,
  });
  const sessionBindings = useQuery({
    queryKey: sessionKeys.bindings(sessionId ?? ''),
    queryFn: () => listSessionBindings(sessionId!),
    enabled: !!sessionId,
  });
  // The one source of truth for "can this tool be used": the server's answer.
  const effective = useQuery<EffectiveTool[]>({
    queryKey: sessionId ? sessionKeys.tools(sessionId) : canvasKeys.agentTools(agentId ?? ''),
    queryFn: () => (sessionId ? getSessionEffectiveTools(sessionId) : getAgentEffectiveTools(agentId!)),
    enabled: !!agentId || !!sessionId,
  });

  const bindings = useMemo(() => {
    const byId = new Map<string, McpBinding>();
    for (const b of [...(agentBindings.data ?? []), ...(sessionBindings.data ?? [])]) byId.set(b.id, b);
    return [...byId.values()];
  }, [agentBindings.data, sessionBindings.data]);

  const bound = useMemo(() => [...new Set(bindings.map((b) => b.connection_id))].sort(), [bindings]);
  const catalogs = useQueries({
    queries: bound.map((id) => ({ queryKey: canvasKeys.connectionTools(id), queryFn: () => listConnectionTools(id) })),
  });
  const catalogData = catalogs.map((c) => c.data);
  const catalogKey = JSON.stringify(catalogData);

  const subject = sessionId ? sessionNode(sessionId) : agentId ? agentNode(agentId) : null;

  const nodes = useMemo(() => {
    if (!agentId) return [];
    const agent = agents.data?.find((a) => a.id === agentId);
    const outcome = new Map((effective.data ?? []).map((t) => [`${t.connection_id}:${t.tool_name}`, t.outcome]));
    const tools = new Map<string, { connectionId: string; name: string; risk: string }>();
    catalogData.forEach((rows, i) => {
      for (const t of rows ?? []) tools.set(`${bound[i]}:${t.tool_name}`, { connectionId: bound[i]!, name: t.tool_name, risk: t.risk_level });
    });
    for (const t of effective.data ?? []) {
      const key = `${t.connection_id}:${t.tool_name}`;
      if (!tools.has(key)) tools.set(key, { connectionId: t.connection_id, name: t.tool_name, risk: t.risk_level });
    }

    const conns = connections.data ?? [];
    const pos = placeByRank([
      { id: agentNode(agentId), rank: 0 },
      ...(sessionId ? [{ id: sessionNode(sessionId), rank: 0 }] : []),
      ...conns.map((c) => ({ id: connectionNode(c.id), rank: 1 })),
      ...[...tools.values()].map((t) => ({ id: toolNode(t.connectionId, t.name), rank: 2 })),
    ]);
    const at = (id: string) => pos.get(id);
    return [
      entity(agentNode(agentId), agent ? agentEntity(agent) : { kind: 'agent', entityId: agentId, label: agentId.slice(0, 8) }, at(agentNode(agentId))),
      ...(sessionId
        ? [entity(sessionNode(sessionId), { kind: 'session', entityId: sessionId, label: `Session ${sessionId.slice(0, 8)}` }, at(sessionNode(sessionId)))]
        : []),
      ...conns.map((c) =>
        entity(
          connectionNode(c.id),
          { kind: 'connection', entityId: c.id, label: c.name, subtitle: `${c.transport_type} · ${c.health_status}`, muted: !c.is_active },
          at(connectionNode(c.id))
        )
      ),
      ...[...tools.entries()].map(([key, t]) =>
        entity(
          toolNode(t.connectionId, t.name),
          {
            kind: 'tool',
            entityId: key,
            label: t.name,
            subtitle: t.risk,
            outcome: (outcome.get(key) as ToolOutcome | undefined) ?? 'unscoped',
          },
          at(toolNode(t.connectionId, t.name))
        )
      ),
    ];
    // catalogKey stands in for the per-render `catalogData` array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, sessionId, agents.data, connections.data, effective.data, bound, catalogKey]);

  const edges = useMemo(() => {
    if (!agentId || !subject) return [];
    const toolIds = new Set(nodes.filter((n) => n.data.kind === 'tool').map((n) => n.id));
    return [
      ...bindings.map((b) =>
        edge(
          `binding:${b.id}`,
          b.target_type === 'session' && b.session_id ? sessionNode(b.session_id) : agentNode(b.agent_id ?? agentId),
          connectionNode(b.connection_id),
          b.status === 'disabled' ? 'binding_disabled' : 'binding',
          { entityId: b.id, deletable: true }
        )
      ),
      ...[...toolIds].map((id) => {
        const connectionId = id.split(':')[1]!;
        return edge(`provides:${id}`, connectionNode(connectionId), id, 'provides');
      }),
      ...(effective.data ?? []).map((t) => {
        const kind = t.outcome === 'allowed' ? 'effective_allowed' : t.outcome === 'would_deny' ? 'effective_would_deny' : 'effective_denied';
        return edge(`effective:${t.connection_id}:${t.tool_name}`, subject, toolNode(t.connection_id, t.tool_name), kind);
      }),
    ];
  }, [agentId, subject, nodes, bindings, effective.data]);

  if (!agentId) {
    return {
      nodes: [],
      edges: [],
      loading: false,
      error: null,
      empty: 'Select an agent (in the rail, or in the Agent Network) to see its tool context.',
    };
  }
  return {
    nodes,
    edges,
    loading: connections.isLoading || agentBindings.isLoading || effective.isLoading,
    error: connections.error ?? agentBindings.error ?? sessionBindings.error ?? effective.error,
    connectLabel: 'Bind tool connection',
    canConnect: ({ source, target }) => {
      const connection = entityOf(target, 'connection');
      const onSession = entityOf(source, 'session');
      const onAgent = entityOf(source, 'agent');
      if (!connection || !(onSession || onAgent)) return 'Bind an agent or session to a tool connection.';
      const exists = bindings.some(
        (b) =>
          b.connection_id === connection &&
          (onSession ? b.target_type === 'session' && b.session_id === onSession : b.target_type === 'agent' && b.agent_id === onAgent)
      );
      return exists ? 'Already bound to this connection.' : null;
    },
    connect: ({ source, target }) => {
      const onSession = entityOf(source, 'session');
      const connection = entityOf(target, 'connection')!;
      return onSession ? createBinding({ sessionId: onSession }, connection) : createBinding({ agentId: entityOf(source, 'agent')! }, connection);
    },
    removeEdge: (e) => deleteBinding(e.data!.entityId!),
    toggleEdge: (e) => setBindingStatus(e.data!.entityId!, e.data!.kind === 'binding' ? 'disabled' : 'active'),
  };
}

/* ── Organization ──────────────────────────────────────────────────────── */

function useOrganization(): ModeGraph {
  const agents = useAgents();
  const departments = useQuery({ queryKey: canvasKeys.departments(), queryFn: listDepartments });
  const teams = useQuery({ queryKey: canvasKeys.teams(), queryFn: listTeams });

  const list = useMemo(() => agents.data ?? [], [agents.data]);
  const nodes = useMemo(() => {
    const depth = managerDepth(list);
    const depts = departments.data ?? [];
    const tms = teams.data ?? [];
    const pos = placeByRank([
      ...depts.map((d) => ({ id: `department:${d.id}`, rank: 0 })),
      ...tms.map((t) => ({ id: `team:${t.id}`, rank: 1 })),
      ...list.map((a) => ({ id: agentNode(a.id), rank: 2 + depth.get(a.id)! })),
    ]);
    return [
      ...depts.map((d) =>
        entity(`department:${d.id}`, { kind: 'department', entityId: d.id, label: d.name }, pos.get(`department:${d.id}`))
      ),
      ...tms.map((t) => entity(`team:${t.id}`, { kind: 'team', entityId: t.id, label: t.name }, pos.get(`team:${t.id}`))),
      ...list.map((a) => entity(agentNode(a.id), agentEntity(a), pos.get(agentNode(a.id)))),
    ];
  }, [list, departments.data, teams.data]);

  const edges = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    const member = (from: string, to: string) =>
      ids.has(from) && ids.has(to) ? [edge(`member:${from}`, from, to, 'member_of')] : [];
    return [
      ...(teams.data ?? []).flatMap((t) => member(`team:${t.id}`, `department:${t.department_id}`)),
      ...list.flatMap((a) =>
        a.team_id
          ? member(agentNode(a.id), `team:${a.team_id}`)
          : a.department_id
            ? member(agentNode(a.id), `department:${a.department_id}`)
            : []
      ),
      ...reportingEdges(list),
    ];
  }, [nodes, list, teams.data]);

  return {
    nodes,
    edges,
    loading: agents.isLoading || departments.isLoading || teams.isLoading,
    error: agents.error ?? departments.error ?? teams.error,
    empty: agents.data?.length === 0 && departments.data?.length === 0 ? 'No organization yet.' : undefined,
    // Only reporting lines have a write API here; membership is shown, not edited.
    toolbar: (
      <p className="text-[11px] text-[#9C9C9F]">
        <span style={{ color: EDGE_STYLES.reports_to.stroke }}>manages</span>: reporting line, editable here.{' '}
        <span style={{ color: EDGE_STYLES.member_of.stroke }}>member of</span>: team and department membership,
        read-only. Moving a node changes only this view.
      </p>
    ),
    ...reportingMutations(list),
  };
}

export const CANVAS_MODE_DEFS: Record<CanvasMode, CanvasModeDef> = {
  workflow: { id: 'workflow', label: 'Workflow', useGraph: useWorkflow },
  network: { id: 'network', label: 'Agent Network', useGraph: useNetwork },
  context: { id: 'context', label: 'Context / MCP', useGraph: useContextMode },
  organization: { id: 'organization', label: 'Organization', useGraph: useOrganization },
};
