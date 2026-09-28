import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import { TaskAttemptPanel } from '../TaskAttemptPanel';
import type { Task, TaskAttempt } from '@/types/task';
import type { Agent } from '@/types/agent';

// Capture every realtime subscriber so tests deliver server events by hand.
const streams = vi.hoisted(() => ({ handlers: [] as Array<(event: unknown) => void> }));
vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: (channel: string, onEvent: (event: unknown) => void) => {
    if (channel === 'sessions') streams.handlers.push(onEvent);
  },
}));

const AGENTS = [
  { id: 'claude-1', name: 'Clara' },
  { id: 'agy-1', name: 'Agnes' },
] as unknown as Agent[];

function makeTask(id: string, agent: string): Task {
  return {
    id,
    title: `Task ${id}`,
    status: 'pending',
    priority: 2,
    assigned_agent_id: agent,
    work_spec: { mode: 'write' },
  } as unknown as Task;
}

function makeAttempt(taskId: string, agent: string, extra: Partial<TaskAttempt> = {}): TaskAttempt {
  return {
    id: `${taskId}-a1`,
    task_id: taskId,
    agent_id: agent,
    session_id: `${taskId}-s1`,
    attempt_number: 1,
    status: 'queued',
    active: true,
    execution_id: null,
    cancel_requested: false,
    report: null,
    report_seq: 0,
    artifacts: [],
    verification: null,
    usage: null,
    ...extra,
  };
}

const RUNNING = (taskId: string, agent: string) =>
  makeAttempt(taskId, agent, {
    status: 'running',
    execution_id: 'exec-42',
    report_seq: 3,
    report: {
      state: 'working',
      summary: 'Writing the calculator',
      progress_percent: 40,
      current_step: 'write tests',
      completed_steps: ['read spec'],
      next_step: 'run pytest',
      blockers: ['waiting on fixture data'],
      artifacts: [],
      tests_run: [],
      confidence: 0.6,
      needs_help: false,
      eta: null,
    },
    artifacts: [
      {
        path: 'calculator.py',
        type: 'source',
        size: 120,
        sha256: 'abcdef0123456789abcdef',
        validation: 'present',
      },
    ],
    verification: {
      passed: true,
      commands: [
        { id: '0:pytest', command: 'pytest', argv: [], exit_code: 0, timed_out: false, passed: true, tests: { passed: 4 } },
      ],
    },
    usage: { backend: 'claude', model: 'sonnet' },
  });

/** A tiny fake backend keyed by task id; tests assert on what it holds. */
let backend: {
  attempts: Record<string, TaskAttempt[]>;
  posts: string[];
  startGate: Record<string, Promise<void>>;
};

function useBackend() {
  server.use(
    http.get('*/api/v1/tasks/:taskId/attempts', ({ params }) =>
      HttpResponse.json(backend.attempts[String(params.taskId)] ?? [])
    ),
    http.post('*/api/v1/tasks/:taskId/attempts', async ({ params }) => {
      const taskId = String(params.taskId);
      backend.posts.push(`start:${taskId}`);
      await backend.startGate[taskId];
      const agent = taskId === 't-agy' ? 'agy-1' : 'claude-1';
      const current = backend.attempts[taskId]?.[0];
      if (current?.active) return HttpResponse.json({ ...current, created: false });
      const attempt = makeAttempt(taskId, agent);
      backend.attempts[taskId] = [attempt];
      return HttpResponse.json({ ...attempt, created: true }, { status: 201 });
    }),
    http.post('*/api/v1/tasks/:taskId/attempts/:attemptId/cancel', ({ params }) => {
      const taskId = String(params.taskId);
      backend.posts.push(`cancel:${params.attemptId}`);
      const [attempt] = backend.attempts[taskId]!;
      backend.attempts[taskId] = [{ ...attempt!, cancel_requested: true }];
      return HttpResponse.json(backend.attempts[taskId]![0]);
    })
  );
}

function renderPanels(tasks: Task[], client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const view = render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        {tasks.map((t) => (
          <div key={t.id} data-testid={`panel-${t.id}`}>
            <TaskAttemptPanel task={t} agents={AGENTS} />
          </div>
        ))}
      </QueryClientProvider>
    </MemoryRouter>
  );
  return { ...view, client };
}

const panel = (taskId: string) => within(screen.getByTestId(`panel-${taskId}`));

beforeEach(() => {
  streams.handlers = [];
  backend = { attempts: {}, posts: [], startGate: {} };
  useBackend();
});

describe('TaskAttemptPanel', () => {
  it('restores the live attempt from the server after a refresh', async () => {
    backend.attempts['t-claude'] = [RUNNING('t-claude', 'claude-1')];

    for (let load = 0; load < 2; load++) {
      // A fresh QueryClient per render is a page refresh: nothing is cached.
      const { unmount } = renderPanels([makeTask('t-claude', 'claude-1')]);
      const p = panel('t-claude');
      expect(await p.findByText('Attempt 1: running')).toBeInTheDocument();
      expect(p.getByTestId('attempt-state')).toHaveTextContent('working');
      expect(p.getByText('write tests')).toBeInTheDocument();
      expect(p.getByText('40%')).toBeInTheDocument();
      expect(p.getByText('claude')).toBeInTheDocument();
      expect(p.getByText('exec-42')).toBeInTheDocument();
      expect(p.getByRole('list', { name: 'Blockers' })).toHaveTextContent('waiting on fixture data');
      expect(p.getByRole('list', { name: 'Artifacts' })).toHaveTextContent('calculator.py');
      expect(p.getByRole('list', { name: 'Tests' })).toHaveTextContent('pytest exit 0 · 4 passed');
      expect(p.getByRole('link', { name: 'Open session' })).toHaveAttribute(
        'href',
        '/workspace?agent=claude-1&session=t-claude-s1'
      );
      unmount();
    }
  });

  it('starts work once and then attaches to the active attempt', async () => {
    renderPanels([makeTask('t-claude', 'claude-1')]);
    const p = panel('t-claude');

    fireEvent.click(await p.findByRole('button', { name: 'Start work' }));

    expect(await p.findByText('Attempt 1: queued')).toBeInTheDocument();
    expect(p.queryByRole('button', { name: 'Start work' })).not.toBeInTheDocument();
    expect(p.getByRole('button', { name: 'Cancel attempt' })).toBeEnabled();
    expect(backend.posts).toEqual(['start:t-claude']);
  });

  it('cancels only the attempt it belongs to', async () => {
    backend.attempts['t-claude'] = [RUNNING('t-claude', 'claude-1')];
    backend.attempts['t-agy'] = [RUNNING('t-agy', 'agy-1')];
    renderPanels([makeTask('t-claude', 'claude-1'), makeTask('t-agy', 'agy-1')]);

    fireEvent.click(await panel('t-claude').findByRole('button', { name: 'Cancel attempt' }));

    expect(await panel('t-claude').findByRole('button', { name: 'Cancelling…' })).toBeDisabled();
    expect(backend.posts).toEqual(['cancel:t-claude-a1']);
    expect(backend.attempts['t-agy']![0]!.cancel_requested).toBe(false);
    expect(panel('t-agy').getByRole('button', { name: 'Cancel attempt' })).toBeEnabled();
  });

  it('a pending Claude start does not block starting Agy work', async () => {
    let release!: () => void;
    backend.startGate['t-claude'] = new Promise<void>((resolve) => (release = resolve));
    renderPanels([makeTask('t-claude', 'claude-1'), makeTask('t-agy', 'agy-1')]);

    fireEvent.click(await panel('t-claude').findByRole('button', { name: 'Start work' }));
    await waitFor(() => expect(backend.posts).toContain('start:t-claude'));
    expect(panel('t-claude').getByRole('button', { name: 'Start work' })).toBeDisabled();

    fireEvent.click(panel('t-agy').getByRole('button', { name: 'Start work' }));
    expect(await panel('t-agy').findByText('Attempt 1: queued')).toBeInTheDocument();
    expect(panel('t-claude').queryByText(/Attempt 1/)).not.toBeInTheDocument();

    await act(async () => release());
    expect(await panel('t-claude').findByText('Attempt 1: queued')).toBeInTheDocument();
  });

  it('refetches on its own task events and refreshes the board when an attempt ends', async () => {
    backend.attempts['t-claude'] = [makeAttempt('t-claude', 'claude-1')];
    const { client } = renderPanels([makeTask('t-claude', 'claude-1')]);
    expect(await panel('t-claude').findByText('Attempt 1: queued')).toBeInTheDocument();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    backend.attempts['t-claude'] = [RUNNING('t-claude', 'claude-1')];
    act(() =>
      streams.handlers.forEach((h) =>
        h({ event_type: 'task.attempt', payload: { task_id: 'other', attempt_status: 'running' } })
      )
    );
    expect(invalidate).not.toHaveBeenCalled();

    act(() =>
      streams.handlers.forEach((h) =>
        h({ event_type: 'task.attempt', payload: { task_id: 't-claude', attempt_status: 'running' } })
      )
    );
    expect(await panel('t-claude').findByText('Attempt 1: running')).toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ['tasks'] });

    act(() =>
      streams.handlers.forEach((h) =>
        h({ event_type: 'task.attempt', payload: { task_id: 't-claude', attempt_status: 'completed' } })
      )
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tasks'] });
  });

  it('shows the stable error code when the server refuses to start', async () => {
    server.use(
      http.post('*/api/v1/tasks/:taskId/attempts', () =>
        HttpResponse.json(
          { detail: { code: 'EMPLOYEE_NOT_CLI', message: 'Employee has no CLI backend' } },
          { status: 422 }
        )
      )
    );
    renderPanels([makeTask('t-claude', 'claude-1')]);

    fireEvent.click(await panel('t-claude').findByRole('button', { name: 'Start work' }));

    expect(await panel('t-claude').findByRole('alert')).toHaveTextContent('EMPLOYEE_NOT_CLI');
  });
});
