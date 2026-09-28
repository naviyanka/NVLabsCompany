import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ManagerPanel, type Rollup } from '../ManagerPanel';

const attempt = (task_title: string, status: string, extra: Record<string, unknown> = {}) => ({
  task_title,
  status,
  summary: null,
  error_code: null,
  error: null,
  ...extra,
});

const ROLLUP: Rollup = {
  summary: 'Lead has 2 direct report(s): 1 active, 0 queued, 1 completed, 1 failed/blocked, 0 stale.',
  generated_at: '2026-09-28T10:00:00Z',
  direct_reports: [
    {
      employee: { id: 'a', name: 'Ada', title: null },
      state: 'working',
      active: attempt('Build calculator', 'running'),
      progress: { report: { progress_percent: 40, current_step: 'writing tests' } },
      last_success: attempt('Fix login', 'completed', { summary: 'login fixed' }),
      latest_failure: null,
      backend: 'claude',
    },
    {
      employee: { id: 'b', name: 'Bo', title: null },
      state: 'blocked',
      active: null,
      progress: null,
      last_success: null,
      latest_failure: attempt('Deploy', 'blocked', { error: 'needs credentials' }),
      backend: 'codex',
    },
  ],
};

function serve(rollups: Rollup[]) {
  let calls = 0;
  server.use(
    http.get('*/api/v1/agents/lead/rollup', () => HttpResponse.json(rollups[Math.min(calls++, rollups.length - 1)])),
  );
  return () => calls;
}

describe('ManagerPanel', () => {
  it('shows each direct report with state, progress, blocker and latest result', async () => {
    serve([ROLLUP]);
    render(<ManagerPanel agentId="lead" />);

    expect(await screen.findByText(ROLLUP.summary)).toBeInTheDocument();
    const rows = screen.getAllByTestId('report-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Ada');
    expect(rows[0]).toHaveTextContent('working');
    expect(rows[0]).toHaveTextContent('Build calculator · 40% · writing tests');
    expect(rows[0]).toHaveTextContent('Latest result: Fix login — login fixed');
    expect(rows[1]).toHaveTextContent('blocked');
    expect(rows[1]).toHaveTextContent('Blocker: Deploy: needs credentials');
  });

  it('refresh reloads the roll-up', async () => {
    const calls = serve([{ ...ROLLUP, direct_reports: [] }, ROLLUP]);
    render(<ManagerPanel agentId="lead" />);
    expect(await screen.findByText(/No direct reports/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(screen.getAllByTestId('report-row')).toHaveLength(2));
    expect(calls()).toBe(2);
  });

  it('shows an error when the roll-up is refused', async () => {
    server.use(
      http.get('*/api/v1/agents/lead/rollup', () =>
        HttpResponse.json({ detail: { code: 'NOT_THIS_MANAGER', message: 'no' } }, { status: 403 }),
      ),
    );
    render(<ManagerPanel agentId="lead" />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryAllByTestId('report-row')).toHaveLength(0);
  });
});
