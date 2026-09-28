import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import type { Agent } from '@/types/agent';
import { CeoControlPanel, type CeoStatus } from '../CeoControlPanel';

const AGENTS = [
  { id: 'a1', name: 'Ada', title: 'Chief Executive' },
  { id: 'a2', name: 'Bo', title: 'Engineering Lead' },
] as Agent[];

const STATUS: CeoStatus = {
  ceo: { id: 'a1', name: 'Ada', title: 'Chief Executive', backend: 'hermes' },
  ceo_tools_available: false,
  ceo_tools_unavailable_reason: 'hermes cannot load an execution-scoped MCP server',
  snapshot: {
    version: 3,
    generated_at: '2026-09-29T10:00:00Z',
    freshness: { status: 'stale', age_seconds: 900 },
    last_refresh_error: null,
  },
  pending_approvals: [{ id: 'p', type: 'hire_employee', created_at: '2026-09-29T09:00:00Z' }],
  memory: [
    { id: 'm', type: 'directive', content: 'Ship the billing fix first', status: 'active', created_at: '2026-09-29T09:30:00Z' },
  ],
};

const renderPanel = () =>
  render(
    <MemoryRouter>
      <CeoControlPanel agents={AGENTS} />
    </MemoryRouter>,
  );

describe('CeoControlPanel', () => {
  it('shows the CEO, tool availability, snapshot freshness, approvals and memory', async () => {
    server.use(http.get('*/api/v1/organization/ceo', () => HttpResponse.json(STATUS)));
    renderPanel();

    expect(await screen.findByTestId('ceo-backend')).toHaveTextContent('Backend: hermes');
    expect(screen.getByTestId('ceo-backend')).toHaveTextContent('chat only, no CEO tools');
    expect(screen.getByTestId('ceo-snapshot')).toHaveTextContent('Snapshot v3');
    expect(screen.getByText('stale')).toBeInTheDocument();
    expect(screen.getByTestId('ceo-approvals')).toHaveTextContent('1 pending human approval(s)');
    expect(screen.getByTestId('ceo-memory')).toHaveTextContent('[directive] Ship the billing fix first');
    expect(screen.getByRole('link', { name: 'Open CEO chat' })).toHaveAttribute('href', '/agents/a1');
  });

  it('replaces the CEO with the selected agent', async () => {
    let body: unknown = null;
    server.use(
      http.get('*/api/v1/organization/ceo', () =>
        HttpResponse.json(body ? { ...STATUS, ceo: { ...STATUS.ceo!, id: 'a2', name: 'Bo' } } : STATUS),
      ),
      http.put('*/api/v1/organization/ceo', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({});
      }),
    );
    renderPanel();
    await screen.findByTestId('ceo-backend');

    fireEvent.change(screen.getByLabelText('CEO agent'), { target: { value: 'a2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Replace CEO' }));
    await waitFor(() => expect(body).toEqual({ agent_id: 'a2' }));
    expect(await screen.findByText('CEO · Bo')).toBeInTheDocument();
  });

  it('offers appointment when no CEO is designated and shows a refusal', async () => {
    server.use(
      http.get('*/api/v1/organization/ceo', () => HttpResponse.json({ ...STATUS, ceo: null, memory: [] })),
      http.put('*/api/v1/organization/ceo', () =>
        HttpResponse.json({ detail: { code: 'HUMAN_OWNER_REQUIRED', message: 'no' } }, { status: 403 }),
      ),
    );
    renderPanel();
    expect(await screen.findByText('No CEO designated.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('CEO agent'), { target: { value: 'a1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Appoint CEO' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
