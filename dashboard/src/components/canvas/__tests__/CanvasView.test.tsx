import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import { Workspace } from '@/pages/Workspace';

// React Flow measures the DOM; jsdom has no layout, so give it inert observers.
beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  (globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly ??= class {
    m22 = 1;
    constructor() {}
  };
});

// Realtime handlers are captured so a test can deliver a server event by hand.
const streams = vi.hoisted(() => ({ handlers: {} as Record<string, (event: unknown) => void> }));
vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: (channel: string, onEvent: (event: unknown) => void) => {
    streams.handlers[channel] = onEvent;
  },
}));

type Binding = {
  id: string;
  connection_id: string;
  target_type: 'agent' | 'session';
  agent_id: string | null;
  session_id: string | null;
  disabled_tools: string[];
  instructions: null;
  status: 'active' | 'disabled';
  version: number;
};

function agent(id: string, name: string, role: string, manager_id: string | null, extra = {}) {
  return { id, name, role, title: role, status: 'idle', manager_id, team_id: null, department_id: null, ...extra };
}

/**
 * A small fake backend. Tests assert on what it holds after a Canvas action,
 * and the Canvas must show only what it answers on the next read.
 */
let backend: {
  agents: ReturnType<typeof agent>[];
  bindings: Binding[];
  /** Policy the server applies on top of bindings; the UI must never override it. */
  policy: Record<string, 'allowed' | 'would_deny' | 'denied'>;
  refuse: { status: number; detail: string } | null;
  writes: string[];
};

const CATALOG: Record<string, Array<{ tool_name: string; risk_level: string }>> = {
  gh: [
    { tool_name: 'search', risk_level: 'read' },
    { tool_name: 'delete_repo', risk_level: 'write' },
  ],
};

function effectiveFor(agentId: string) {
  return backend.bindings
    .filter((b) => b.agent_id === agentId)
    .flatMap((b) =>
      (CATALOG[b.connection_id] ?? []).map((t) => ({
        connection_id: b.connection_id,
        tool_name: t.tool_name,
        risk_level: t.risk_level,
        outcome: b.status === 'disabled' ? 'denied' : (backend.policy[t.tool_name] ?? 'allowed'),
        problems: [],
      }))
    );
}

function refused() {
  const r = backend.refuse;
  return r ? HttpResponse.json({ detail: r.detail }, { status: r.status }) : null;
}

beforeEach(() => {
  streams.handlers = {};
  backend = {
    agents: [
      agent('cy', 'Cy', 'ceo', null, { department_id: 'eng' }),
      agent('lee', 'Lee', 'lead', 'cy', { team_id: 'platform' }),
      agent('ada', 'Ada', 'engineer', null),
    ],
    bindings: [],
    policy: {},
    refuse: null,
    writes: [],
  };
  server.use(
    http.get('*/api/v1/companies/:cid/agents', () => HttpResponse.json(backend.agents)),
    http.get('*/api/v1/companies/:cid/departments', () =>
      HttpResponse.json([{ id: 'eng', name: 'Engineering', description: null }])
    ),
    http.get('*/api/v1/companies/:cid/teams', () =>
      HttpResponse.json([{ id: 'platform', name: 'Platform', description: null, department_id: 'eng' }])
    ),
    http.get('*/api/v1/companies/:cid/delegations', () => HttpResponse.json([])),
    http.get('*/api/v1/companies/:cid/sessions', () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get('*/api/v1/companies/:cid/pipelines', () =>
      HttpResponse.json([
        {
          id: 'p1',
          name: 'Release',
          description: null,
          trigger_type: 'manual',
          is_active: true,
          stages: [{ name: 'Build', agent_id: 'ada' }, { name: 'Publish' }],
        },
        { id: 'p2', name: 'Triage', description: null, trigger_type: 'webhook', is_active: true, stages: [] },
      ])
    ),
    http.get('*/api/v1/tool-connections', () =>
      HttpResponse.json([
        { id: 'gh', name: 'GitHub', transport_type: 'mcp_remote', health_status: 'healthy', is_active: true },
      ])
    ),
    http.get('*/api/v1/tool-connections/:id/tools', ({ params }) =>
      HttpResponse.json(
        (CATALOG[String(params.id)] ?? []).map((t) => ({
          id: t.tool_name,
          connection_id: params.id,
          description: null,
          is_active: true,
          ...t,
        }))
      )
    ),
    http.get('*/api/v1/agents/:id/mcp-bindings', ({ params }) =>
      HttpResponse.json(backend.bindings.filter((b) => b.agent_id === params.id))
    ),
    http.get('*/api/v1/agents/:id/effective-tools', ({ params }) => HttpResponse.json(effectiveFor(String(params.id)))),
    http.post('*/api/v1/agents/:id/mcp-bindings', async ({ params, request }) => {
      backend.writes.push('POST binding');
      const denied = refused();
      if (denied) return denied;
      const { connection_id } = (await request.json()) as { connection_id: string };
      const b: Binding = {
        id: `b${backend.bindings.length + 1}`,
        connection_id,
        target_type: 'agent',
        agent_id: String(params.id),
        session_id: null,
        disabled_tools: [],
        instructions: null,
        status: 'active',
        version: 1,
      };
      backend.bindings.push(b);
      return HttpResponse.json(b, { status: 201 });
    }),
    http.patch('*/api/v1/mcp-bindings/:id', async ({ params, request }) => {
      backend.writes.push('PATCH binding');
      const denied = refused();
      if (denied) return denied;
      const { status } = (await request.json()) as { status: Binding['status'] };
      const b = backend.bindings.find((x) => x.id === params.id)!;
      b.status = status;
      return HttpResponse.json(b);
    }),
    http.delete('*/api/v1/mcp-bindings/:id', ({ params }) => {
      backend.writes.push('DELETE binding');
      const denied = refused();
      if (denied) return denied;
      backend.bindings = backend.bindings.filter((b) => b.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.put('*/api/v1/agents/:id/manager', async ({ params, request }) => {
      backend.writes.push('PUT manager');
      const denied = refused();
      if (denied) return denied;
      const { manager_id } = (await request.json()) as { manager_id: string | null };
      const a = backend.agents.find((x) => x.id === params.id)!;
      a.manager_id = manager_id;
      return HttpResponse.json(a);
    })
  );
});

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function renderCanvas(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[url]}>
      <QueryClientProvider client={queryClient}>
        <Routes>
          <Route
            path="/workspace"
            element={
              <>
                <Workspace />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

const search = () => new URLSearchParams(screen.getByTestId('location').textContent ?? '');

async function canvas(label: string) {
  return screen.findByRole('region', { name: `${label} canvas` });
}

/** Pick a node in the inspector (the accessible twin of clicking it). */
async function selectNode(region: HTMLElement, option: string) {
  const picker = (await within(region).findByLabelText('Selected item')) as HTMLSelectElement;
  await waitFor(() => expect(within(picker).getByText(option)).toBeTruthy());
  const value = [...picker.options].find((o) => o.textContent === option)!.value;
  fireEvent.change(picker, { target: { value } });
}

async function connectTo(region: HTMLElement, label: string, target: string) {
  const picker = (await within(region).findByLabelText(label)) as HTMLSelectElement;
  const value = [...picker.options].find((o) => o.textContent === target)!.value;
  fireEvent.change(picker, { target: { value } });
  fireEvent.click(within(region).getByRole('button', { name: label }));
}

const relationships = (region: HTMLElement) =>
  within(within(region).getByRole('list', { name: 'Relationships' }))
    .queryAllByRole('listitem')
    .map((li) => li.querySelector('span')!.textContent);

const toolOutcome = (region: HTMLElement, name: string) => within(region).getByLabelText(`tool ${name}`).textContent;

describe('Canvas', () => {
  it('opens from the workspace and keeps its mode in the URL', async () => {
    renderCanvas('/workspace');
    fireEvent.click(screen.getByRole('button', { name: 'Open canvas' }));
    expect(search().get('tab')).toBe('canvas');
    expect(await canvas('Agent Network')).toBeTruthy();

    fireEvent.click(screen.getByRole('tab', { name: 'Organization' }));
    expect(search().get('mode')).toBe('organization');
    const org = await canvas('Organization');
    expect(await within(org).findByLabelText('department Engineering')).toBeTruthy();
    expect(within(org).getByLabelText('team Platform')).toBeTruthy();

    // Back to chat: the canvas and its realtime subscription go away.
    fireEvent.click(screen.getByRole('tab', { name: 'Chat' }));
    expect(search().get('tab')).toBeNull();
    expect(screen.queryByRole('region', { name: /canvas$/ })).toBeNull();
  });

  it('restores mode and selection from a deep link', async () => {
    const first = renderCanvas('/workspace?tab=canvas&mode=context&agent=ada');
    const ctx = await canvas('Context / MCP');
    expect(await within(ctx).findByLabelText('connection GitHub')).toBeTruthy();
    first.unmount();

    renderCanvas('/workspace?tab=canvas&mode=workflow&pipeline=p2');
    const wf = await canvas('Workflow');
    expect(((await within(wf).findByLabelText('Pipeline')) as HTMLSelectElement).value).toBe('p2');
  });

  it('sets and clears a reporting line through the API, and draws only what the server holds', async () => {
    renderCanvas('/workspace?tab=canvas&mode=network');
    const net = await canvas('Agent Network');
    await selectNode(net, 'agent: Cy');
    expect(relationships(net)).toEqual(['manages: Lee']);

    await connectTo(net, 'Add direct report', 'Ada');
    await waitFor(() => expect(relationships(net)).toContain('manages: Ada'));
    expect(backend.agents.find((a) => a.id === 'ada')!.manager_id).toBe('cy');

    fireEvent.click(within(net).getByRole('button', { name: 'Remove manages: Ada' }));
    await waitFor(() => expect(relationships(net)).toEqual(['manages: Lee']));
    expect(backend.agents.find((a) => a.id === 'ada')!.manager_id).toBeNull();
  });

  it('keeps the graph at server state when the server refuses a change', async () => {
    backend.refuse = { status: 403, detail: "Role 'viewer' may not write agent" };
    renderCanvas('/workspace?tab=canvas&mode=organization');
    const org = await canvas('Organization');
    await selectNode(org, 'agent: Cy');
    await connectTo(org, 'Add direct report', 'Ada');

    expect((await within(org).findByRole('alert')).textContent).toBe("Role 'viewer' may not write agent");
    expect(backend.writes).toEqual(['PUT manager']);
    expect(backend.agents.find((a) => a.id === 'ada')!.manager_id).toBeNull();
    expect(relationships(org)).not.toContain('manages: Ada');

    // A cycle refused by the server surfaces the same way.
    backend.refuse = { status: 409, detail: 'An agent cannot report to itself or to one of its reports' };
    fireEvent.click(within(org).getByRole('button', { name: 'Remove manages: Lee' }));
    expect(await within(org).findByText(/cannot report to itself/)).toBeTruthy();
    expect(relationships(org)).toContain('manages: Lee');
  });

  it('shows membership as read-only and only reporting lines as editable', async () => {
    renderCanvas('/workspace?tab=canvas&mode=organization');
    const org = await canvas('Organization');
    expect(await within(org).findByText(/team and department membership/)).toBeTruthy();

    await selectNode(org, 'agent: Lee');
    expect(relationships(org).sort()).toEqual(['manages: Cy', 'member of: Platform']);
    expect(within(org).getByRole('button', { name: 'Remove manages: Cy' })).toBeTruthy();
    expect(within(org).queryByRole('button', { name: 'Remove member of: Platform' })).toBeNull();

    // A team is not something an agent reports to, so nothing is offered from it.
    await selectNode(org, 'team: Platform');
    expect(within(org).queryByLabelText('Add direct report')).toBeNull();
    expect(within(org).queryByRole('button', { name: /^Remove/ })).toBeNull();
    expect(backend.writes).toEqual([]);
  });

  it('reports a resource outside the company as not found', async () => {
    backend.refuse = { status: 404, detail: 'Manager not found' };
    renderCanvas('/workspace?tab=canvas&mode=network');
    const net = await canvas('Agent Network');
    await selectNode(net, 'agent: Cy');
    await connectTo(net, 'Add direct report', 'Ada');
    expect((await within(net).findByRole('alert')).textContent).toBe('Not found, or not in your company.');
    expect(backend.agents.find((a) => a.id === 'ada')!.manager_id).toBeNull();
  });

  it('does not send a reporting line it already knows is pointless', async () => {
    renderCanvas('/workspace?tab=canvas&mode=network');
    const net = await canvas('Agent Network');
    await selectNode(net, 'agent: Cy');
    const picker = (await within(net).findByLabelText('Add direct report')) as HTMLSelectElement;
    // Lee already reports to Cy, and Cy cannot report to Cy.
    expect([...picker.options].map((o) => o.textContent)).toEqual(['Choose…', 'Ada']);
    expect(backend.writes).toEqual([]);
  });

  it('creates, disables and deletes an MCP binding, reading tool access back from the server', async () => {
    renderCanvas('/workspace?tab=canvas&mode=context&agent=ada');
    const ctx = await canvas('Context / MCP');
    await selectNode(ctx, 'agent: Ada');
    expect(relationships(ctx)).toEqual([]);

    await connectTo(ctx, 'Bind tool connection', 'GitHub');
    await waitFor(() => expect(relationships(ctx)).toContain('bound: GitHub'));
    expect(backend.bindings).toMatchObject([{ agent_id: 'ada', connection_id: 'gh', status: 'active' }]);
    await waitFor(() => expect(toolOutcome(ctx, 'search')).toContain('allowed'));

    fireEvent.click(within(ctx).getByRole('button', { name: 'Disable bound: GitHub' }));
    await waitFor(() => expect(relationships(ctx)).toContain('binding disabled: GitHub'));
    expect(backend.bindings[0]!.status).toBe('disabled');
    await waitFor(() => expect(toolOutcome(ctx, 'search')).toContain('denied'));

    fireEvent.click(within(ctx).getByRole('button', { name: 'Remove binding disabled: GitHub' }));
    await waitFor(() => expect(relationships(ctx)).toEqual([]));
    expect(backend.bindings).toEqual([]);
    expect(within(ctx).queryByLabelText('tool search')).toBeNull();
  });

  it('never shows a tool as usable because of a local change the server did not grant', async () => {
    backend.policy = { delete_repo: 'denied', search: 'would_deny' };
    renderCanvas('/workspace?tab=canvas&mode=context&agent=ada');
    const ctx = await canvas('Context / MCP');
    await selectNode(ctx, 'agent: Ada');
    await connectTo(ctx, 'Bind tool connection', 'GitHub');

    // The binding exists, but access is the server's answer, not the edge's.
    await waitFor(() => expect(relationships(ctx)).toContain('bound: GitHub'));
    await waitFor(() => expect(toolOutcome(ctx, 'delete_repo')).toContain('denied'));
    expect(toolOutcome(ctx, 'search')).toContain('would deny');

    // A refused binding leaves no edge and no tools behind.
    backend.bindings = [];
    backend.refuse = { status: 403, detail: "Role 'agent' may not write mcp_binding" };
    await act(async () => streams.handlers.topology!({ event_type: 'mcp_binding.deleted' }));
    await waitFor(() => expect(relationships(ctx)).toEqual([]));
    await connectTo(ctx, 'Bind tool connection', 'GitHub');
    expect((await within(ctx).findByRole('alert')).textContent).toContain('may not write mcp_binding');
    expect(relationships(ctx)).toEqual([]);
    expect(within(ctx).queryByLabelText('tool delete_repo')).toBeNull();
  });

  it('draws a disabled binding and its tools as denied', async () => {
    backend.bindings = [
      {
        id: 'b9',
        connection_id: 'gh',
        target_type: 'agent',
        agent_id: 'ada',
        session_id: null,
        disabled_tools: [],
        instructions: null,
        status: 'disabled',
        version: 2,
      },
    ];
    renderCanvas('/workspace?tab=canvas&mode=context&agent=ada');
    const ctx = await canvas('Context / MCP');
    await selectNode(ctx, 'connection: GitHub');
    expect(relationships(ctx)).toContain('binding disabled: Ada');
    expect(within(ctx).getByRole('button', { name: 'Enable binding disabled: Ada' })).toBeTruthy();
    await waitFor(() => expect(toolOutcome(ctx, 'search')).toContain('denied'));
  });

  it('asks for an agent before drawing tool context', async () => {
    renderCanvas('/workspace?tab=canvas&mode=context');
    const ctx = await canvas('Context / MCP');
    expect(within(ctx).getByText(/Select an agent/)).toBeTruthy();
  });

  it('refetches when the server announces a topology change', async () => {
    renderCanvas('/workspace?tab=canvas&mode=network');
    const net = await canvas('Agent Network');
    await selectNode(net, 'agent: Cy');
    expect(relationships(net)).toEqual(['manages: Lee']);

    // Someone else changed the org chart.
    backend.agents.find((a) => a.id === 'ada')!.manager_id = 'cy';
    expect(Object.keys(streams.handlers)).toContain('topology');
    await act(async () => streams.handlers.topology!({ event_type: 'agent.manager_changed', payload: {} }));
    await waitFor(() => expect(relationships(net)).toEqual(['manages: Lee', 'manages: Ada']));
  });

  it('opens an agent in the workspace from the canvas', async () => {
    renderCanvas('/workspace?tab=canvas&mode=network');
    const net = await canvas('Agent Network');
    await selectNode(net, 'agent: Lee');
    fireEvent.click(within(net).getByRole('button', { name: 'Open in workspace' }));
    expect(search().get('agent')).toBe('lee');
    expect(search().get('tab')).toBe('canvas');
  });

  it('projects a pipeline read-only and switches pipeline through the URL', async () => {
    renderCanvas('/workspace?tab=canvas&mode=workflow');
    const wf = await canvas('Workflow');
    expect(await within(wf).findByText('Build')).toBeTruthy();
    expect(within(wf).getByText('Publish')).toBeTruthy();
    await selectNode(wf, 'stage: Build');
    expect(within(wf).queryByRole('button', { name: /^Remove/ })).toBeNull();
    expect(within(wf).queryByLabelText('Add direct report')).toBeNull();
    // Nothing on a workflow node offers to delete it: the builder is where pipelines change.
    expect(within(wf).queryByTitle('Delete node')).toBeNull();
    expect(within(wf).queryByRole('button', { name: /delete/i })).toBeNull();
    expect(within(wf).getByRole('link', { name: 'Edit in the pipeline builder' })).toBeTruthy();

    fireEvent.change(within(wf).getByLabelText('Pipeline'), { target: { value: 'p2' } });
    expect(search().get('pipeline')).toBe('p2');
    await waitFor(() => expect(within(wf).queryByText('Build')).toBeNull());
    expect(backend.writes).toEqual([]);
  });
});
