import { beforeEach, describe, it, expect } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ManagerPanel, type HiringRequest, type Rollup } from '../ManagerPanel';

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

const HIRE: HiringRequest = {
  id: 'h1',
  status: 'approval_required',
  approval_status: 'pending',
  request: {
    role: 'engineer',
    title: 'Backend Engineer',
    backend: 'codex',
    model: null,
    estimated_monthly_cents: 3000,
    estimated_one_time_cents: 500,
  },
  policy_decision: 'approval_required',
  policy_rule: 'policy:default:hiring',
  policy_reasons: [{ code: 'HUMAN_APPROVAL_REQUIRED', message: 'A human must approve this hire' }],
  decided_by: null,
  rejection_reason: null,
  employee: null,
};

describe('ManagerPanel', () => {
  beforeEach(() => {
    server.use(http.get('*/api/v1/agents/lead/hiring-requests', () => HttpResponse.json([])));
  });

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

  it('shows hiring requests with policy, cost, employee and rejection reason', async () => {
    serve([ROLLUP]);
    server.use(
      http.get('*/api/v1/agents/lead/hiring-requests', () =>
        HttpResponse.json([
          HIRE,
          {
            ...HIRE,
            id: 'h2',
            status: 'hired',
            approval_status: 'approved',
            decided_by: 'policy:p1:v1:hiring.auto_approve',
            policy_decision: 'auto_approved',
            policy_reasons: [],
            employee: { id: 'e1', name: 'Backend Engineer' },
          },
          { ...HIRE, id: 'h3', status: 'rejected', approval_status: 'rejected', rejection_reason: 'Over budget' },
        ]),
      ),
    );
    render(<ManagerPanel agentId="lead" />);

    await waitFor(() => expect(screen.getAllByTestId('hire-row')).toHaveLength(3));
    const [pending, hired, rejected] = screen.getAllByTestId('hire-row');
    expect(pending).toHaveTextContent('approval_required');
    expect(pending).toHaveTextContent('codex');
    expect(pending).toHaveTextContent('$30.00/month · $5.00 one-time');
    expect(pending).toHaveTextContent('policy:default:hiring');
    expect(hired).toHaveTextContent('Employee: Backend Engineer');
    expect(hired).toHaveTextContent('Decided by policy:p1:v1:hiring.auto_approve');
    expect(rejected).toHaveTextContent('Rejected: Over budget');
    // Only the pending request can be decided.
    expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(1);
  });

  it('approves through the approval endpoint and rejects only with a reason', async () => {
    serve([ROLLUP]);
    let listed = [HIRE];
    const decisions: { action: string; body: unknown }[] = [];
    server.use(
      http.get('*/api/v1/agents/lead/hiring-requests', () => HttpResponse.json(listed)),
      http.post('*/api/v1/approvals/h1/:action', async ({ params, request }) => {
        decisions.push({ action: String(params.action), body: await request.json() });
        listed = [{ ...HIRE, status: 'hired', approval_status: 'approved', employee: { id: 'e1', name: 'Backend Engineer' } }];
        return HttpResponse.json({ id: 'h1' });
      }),
    );
    render(<ManagerPanel agentId="lead" />);

    const reject = await screen.findByRole('button', { name: 'Reject' });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Decision note for Backend Engineer'), { target: { value: 'welcome' } });
    expect(reject).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Employee: Backend Engineer')).toBeInTheDocument();
    expect(decisions).toEqual([{ action: 'approve', body: { decision_note: 'welcome' } }]);
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('shows a refused decision', async () => {
    serve([ROLLUP]);
    server.use(
      http.get('*/api/v1/agents/lead/hiring-requests', () => HttpResponse.json([HIRE])),
      http.post('*/api/v1/approvals/h1/approve', () =>
        HttpResponse.json({ detail: { code: 'HIRING_POLICY_REJECTED', message: 'over budget' } }, { status: 409 }),
      ),
    );
    render(<ManagerPanel agentId="lead" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getAllByTestId('hire-row')[0]).toHaveTextContent('approval_required');
  });
});
