import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import { getActiveCompanyId } from '@/config';
import { Workspace } from '../Workspace';

// Capture the realtime handler so tests can deliver server events by hand.
const streams = vi.hoisted(() => ({ handlers: {} as { sessions: (event: unknown) => void } }));
vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: (channel: string, onEvent: (event: unknown) => void) => {
    (streams.handlers as Record<string, (event: unknown) => void>)[channel] = onEvent;
  },
}));

const AGENTS = [
  { id: 'a1', name: 'Ada', role: 'engineer', status: 'idle', model: 'gpt-x' },
  { id: 'b1', name: 'Bob', role: 'analyst', status: 'active', model: 'gpt-y' },
];

function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    id: 's1',
    company_id: getActiveCompanyId(),
    agent_id: 'a1',
    workspace_id: null,
    status: 'active',
    title: 'Fix the build',
    adapter_type: 'openai',
    model: 'gpt-x',
    llm_connection_id: null,
    external_session_id: null,
    event_seq: 0,
    created_by: 'api',
    metadata: null,
    started_at: '2026-09-26T10:00:00',
    last_activity_at: '2026-09-26T10:00:00',
    ended_at: null,
    ...overrides,
  };
}

/** A tiny fake backend: the tests assert on what it holds, not on UI state. */
let backend: {
  session: ReturnType<typeof makeSession>;
  timeline: Array<Record<string, unknown>>;
  sessionGets: number;
  listCompany: string | null;
  posted: string[];
};

beforeEach(() => {
  streams.handlers = {} as typeof streams.handlers;
  backend = { session: makeSession(), timeline: [], sessionGets: 0, listCompany: null, posted: [] };
  server.use(
    http.get('*/api/v1/companies/:companyId/agents', () => HttpResponse.json(AGENTS)),
    http.get('*/api/v1/companies/:companyId/sessions', ({ params, request }) => {
      backend.listCompany = String(params.companyId);
      const agent = new URL(request.url).searchParams.get('agent_id');
      return HttpResponse.json({
        items: agent === backend.session.agent_id ? [backend.session] : [],
        next_cursor: null,
      });
    }),
    http.get('*/api/v1/sessions/missing', () =>
      HttpResponse.json({ detail: 'Session not found' }, { status: 404 })
    ),
    http.get('*/api/v1/sessions/forbidden', () =>
      HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })
    ),
    http.get('*/api/v1/sessions/:id', () => {
      backend.sessionGets += 1;
      return HttpResponse.json(backend.session);
    }),
    http.get('*/api/v1/sessions/:id/timeline', () =>
      HttpResponse.json({ session_id: 's1', items: backend.timeline, next_cursor: null })
    ),
    http.get('*/api/v1/sessions/:id/usage', () =>
      HttpResponse.json({ session_id: 's1', events: 1, cost_cents: 125, input_tokens: 10, output_tokens: 20 })
    ),
    http.get('*/api/v1/sessions/:id/effective-tools', () =>
      HttpResponse.json([
        { connection_id: 'c1', tool_name: 'search', risk_level: 'read', outcome: 'allowed', problems: [] },
        { connection_id: 'c1', tool_name: 'delete_repo', risk_level: 'write', outcome: 'denied', problems: [] },
      ])
    ),
    http.get('*/api/v1/sessions/:id/mcp-bindings', () =>
      HttpResponse.json([
        {
          id: 'b-1',
          connection_id: 'c1234567-conn',
          target_type: 'agent',
          agent_id: 'a1',
          session_id: null,
          disabled_tools: [],
          instructions: null,
          status: 'active',
          version: 1,
        },
      ])
    ),
    http.post('*/api/v1/sessions/:id/messages', async ({ request }) => {
      const { prompt } = (await request.json()) as { prompt: string };
      backend.posted.push(prompt);
      backend.timeline.push(
        { type: 'message', id: `u${backend.timeline.length}`, at: '2026-09-26T10:01:00', sender: 'user', text: prompt },
        { type: 'message', id: `r${backend.timeline.length}`, at: '2026-09-26T10:01:01', sender: 'agent', text: `echo: ${prompt}` }
      );
      return HttpResponse.json({ session_id: 's1', seq: 2 });
    }),
    http.post('*/api/v1/agents/:agentId/sessions', ({ params }) => {
      backend.session = makeSession({ id: 's2', agent_id: String(params.agentId), title: null });
      return HttpResponse.json(backend.session, { status: 201 });
    })
  );
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function renderWorkspace(url: string) {
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

describe('Agent Workspace', () => {
  it('loads the three panes', async () => {
    renderWorkspace('/workspace');
    expect(screen.getByRole('complementary', { name: 'Agents and sessions' })).toBeTruthy();
    expect(screen.getByText(/Select an agent and a session/)).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'Context' })).toBeTruthy();
    expect(await screen.findByText('Ada')).toBeTruthy();
  });

  it('selects an agent and then a session through the URL', async () => {
    renderWorkspace('/workspace');
    fireEvent.click(await screen.findByText('Ada'));
    expect(search().get('agent')).toBe('a1');

    fireEvent.click(await screen.findByText('Fix the build'));
    expect(backend.listCompany).toBe(getActiveCompanyId());
    expect(search().get('session')).toBe('s1');
    expect(await screen.findByRole('heading', { name: 'Fix the build' })).toBeTruthy();

    // Switching agent drops the session, which belonged to the other agent.
    fireEvent.click(screen.getByText('Bob'));
    expect(search().get('agent')).toBe('b1');
    expect(search().get('session')).toBeNull();
  });

  it('restores a deep link on reload from the server, not from the browser', async () => {
    const first = renderWorkspace('/workspace?session=s1&tab=chat');
    expect(await screen.findByRole('heading', { name: 'Fix the build' })).toBeTruthy();
    // The owning agent comes from the session the server returned.
    const rail = screen.getByRole('complementary', { name: 'Agents and sessions' });
    await waitFor(() =>
      expect(within(rail).getByText('Ada').closest('button')?.getAttribute('aria-current')).toBe('true')
    );
    first.unmount();

    backend.session = makeSession({ title: 'Renamed on the server' });
    renderWorkspace('/workspace?session=s1&tab=chat');
    expect(await screen.findByRole('heading', { name: 'Renamed on the server' })).toBeTruthy();
    expect(backend.sessionGets).toBe(2);

    const stored = [...Object.keys(localStorage), ...Object.keys(sessionStorage)]
      .map((k) => `${k}=${localStorage.getItem(k) ?? sessionStorage.getItem(k)}`)
      .join('\n');
    expect(stored).not.toContain('s1');
  });

  it('keeps the selected tab in the URL', async () => {
    renderWorkspace('/workspace?session=s1');
    fireEvent.click(await screen.findByRole('tab', { name: 'Terminal' }));
    expect(search().get('tab')).toBe('terminal');
    expect(screen.getByText(/Terminal for this session arrives in a later phase/)).toBeTruthy();
  });

  it('shows a not-found session as unavailable', async () => {
    renderWorkspace('/workspace?session=missing');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Not found, or not in your company.');
    fireEvent.click(within(alert).getByText('Clear selection'));
    expect(search().get('session')).toBeNull();
  });

  it('shows a forbidden session as a permission error', async () => {
    renderWorkspace('/workspace?session=forbidden');
    expect((await screen.findByRole('alert')).textContent).toContain('You do not have permission');
  });

  it('shows server-decided tools, bindings and usage in the context panel', async () => {
    renderWorkspace('/workspace?session=s1');
    const context = screen.getByRole('complementary', { name: 'Context' });
    expect(await within(context).findByText('search')).toBeTruthy();
    expect(within(context).getByText('denied')).toBeTruthy();
    expect(await within(context).findByText('c1234567')).toBeTruthy();
    expect(await within(context).findByText('$1.25')).toBeTruthy();
    expect(await within(context).findByText('Ada')).toBeTruthy();
  });

  it('sends messages through the API and renders the reply from the timeline', async () => {
    renderWorkspace('/workspace?session=s1');
    const box = await screen.findByLabelText('Message');
    fireEvent.change(box, { target: { value: 'hello' } });
    fireEvent.click(screen.getByText('Send'));

    expect(await screen.findByText('echo: hello')).toBeTruthy();
    expect(backend.posted).toEqual(['hello']);
  });

  it('creates a session through the API and selects it', async () => {
    renderWorkspace('/workspace?agent=a1');
    fireEvent.click(await screen.findByText('New session'));
    await waitFor(() => expect(search().get('session')).toBe('s2'));
  });

  it('refetches the session when a realtime event names it', async () => {
    renderWorkspace('/workspace?session=s1');
    expect(await screen.findByText('Terminate')).toBeTruthy();
    expect(Object.keys(streams.handlers)).toEqual(['sessions']);

    backend.session = makeSession({ status: 'terminated' });
    act(() => streams.handlers.sessions({ event_type: 'session.terminated', payload: { session_id: 's1' } }));

    expect(await screen.findByPlaceholderText('This session has ended.')).toBeTruthy();
    expect(screen.queryByText('Terminate')).toBeNull();
  });

  it('ignores realtime events for other sessions', async () => {
    renderWorkspace('/workspace?session=s1');
    await screen.findByRole('heading', { name: 'Fix the build' });
    const before = backend.sessionGets;
    act(() => streams.handlers.sessions({ event_type: 'session.updated', payload: { session_id: 'other' } }));
    await new Promise((r) => setTimeout(r, 20));
    expect(backend.sessionGets).toBe(before);
  });
});
