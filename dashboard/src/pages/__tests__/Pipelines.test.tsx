import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import { CanvasView } from '@/components/canvas/CanvasView';
import { Pipelines } from '@/pages/Pipelines';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  (globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly ??= class {
    m22 = 1;
  };
});

vi.mock('@/hooks/useEventStream', () => ({ useEventStream: () => {} }));

type Stage = Record<string, unknown>;

/** A fake backend holding pipelines the way the API stores them. */
let backend: { stages: Stage[]; name: string; puts: Array<{ name: string; stages: Stage[] }>; refuse: string | null };

beforeEach(() => {
  backend = {
    name: 'Release',
    // Stored before the builder existed: no ids, and executor fields the builder never shows.
    stages: [{ name: 'Build', agent_id: 'ada', prompt: 'Compile the release' }, { name: 'Publish' }],
    puts: [],
    refuse: null,
  };
  const row = () => ({
    id: 'p1',
    company_id: 'c1',
    name: backend.name,
    description: null,
    trigger_type: 'manual',
    is_active: true,
    stages: backend.stages,
  });
  server.use(
    http.get('*/api/v1/companies/:cid/pipelines', () => HttpResponse.json([row()])),
    http.get('*/api/v1/nodes', () => HttpResponse.json({ items: [] })),
    http.put('*/api/v1/pipelines/:id', async ({ request }) => {
      const body = (await request.json()) as { name: string; stages: Stage[] };
      backend.puts.push(body);
      if (backend.refuse) return HttpResponse.json({ detail: backend.refuse }, { status: 422 });
      backend.name = body.name;
      backend.stages = body.stages;
      return HttpResponse.json(row());
    })
  );
});

async function openBuilder() {
  render(<Pipelines />);
  fireEvent.click(await screen.findByRole('button', { name: /Edit Visual/ }));
  await screen.findByRole('button', { name: /Save Pipeline/ });
}

async function renameStage(from: string, to: string) {
  fireEvent.click(await screen.findByText(from));
  fireEvent.change(await screen.findByDisplayValue(from), { target: { value: to } });
}

describe('Pipeline builder save', () => {
  it('persists an edited stage, and a reload (builder and Canvas) shows it', async () => {
    await openBuilder();
    await renameStage('Build', 'Build and sign');
    fireEvent.click(screen.getByRole('button', { name: /Save Pipeline/ }));

    await waitFor(() => expect(screen.queryByRole('button', { name: /Save Pipeline/ })).toBeNull());
    expect(backend.puts).toHaveLength(1);
    const [build, publish] = backend.puts[0]!.stages;
    expect([build!.name, publish!.name]).toEqual(['Build and sign', 'Publish']);
    // What the executor runs from survives the save.
    expect([build!.agent_id, build!.prompt]).toEqual(['ada', 'Compile the release']);

    // Reload: a fresh page reads only what the server holds.
    cleanup();
    await openBuilder();
    expect(screen.getByText('Build and sign')).toBeTruthy();
    expect(screen.queryByText('Build')).toBeNull();

    cleanup();
    render(
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <CanvasView
            mode="workflow"
            onMode={() => {}}
            ctx={{ agentId: null, sessionId: null, pipelineId: 'p1', select: () => {} }}
          />
        </QueryClientProvider>
      </MemoryRouter>
    );
    expect(await screen.findByText('Build and sign')).toBeTruthy();
    expect(screen.getByText('Publish')).toBeTruthy();
  }, 15_000); // Several full renders; the 5s default flakes under parallel load.

  it('keeps the builder open and says why when the server refuses the save', async () => {
    backend.refuse = 'stages must be a list';
    await openBuilder();
    await renameStage('Build', 'Build and sign');
    fireEvent.click(screen.getByRole('button', { name: /Save Pipeline/ }));

    expect((await screen.findByRole('alert')).textContent).toBe('Pipeline not saved: stages must be a list');
    expect(screen.getByRole('button', { name: /Save Pipeline/ })).toBeTruthy();
    expect(backend.stages.map((s) => s.name)).toEqual(['Build', 'Publish']);
  });
});
