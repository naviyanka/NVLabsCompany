import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { OrganizationSnapshotPanel, type SnapshotEnvelope } from '../OrganizationSnapshotPanel';

const ENVELOPE: SnapshotEnvelope = {
  version: 2,
  generated_at: '2026-09-29T10:00:00Z',
  freshness: { status: 'fresh', age_seconds: 12 },
  last_refresh_error: null,
  snapshot: {
    company: { name: 'Acme' },
    hierarchy: { depth: 2, managers: [{ id: 'm', name: 'Lead', direct_reports: 2 }] },
    employees: { total: 3, by_status: { idle: 2, working: 1 } },
    work: { counts: { active: 1, completed: 1, blocked: 1 } },
    hiring: { counts: { pending: 1, approved: 1, rejected: 0, failed: 0 } },
    approvals: { pending: 1, by_type: { hire_employee: 1 } },
    budget: {
      company_monthly_cents: 100000,
      company_spent_cents: 2500,
      hiring_reserved_cents: 0,
      hiring_pending_cents: 2400,
    },
    incidents: { open: 1, items: [{ id: 'i', title: 'DB down', severity: 'high' }] },
    summary: { text: 'Acme: 3 employee(s), 1 manager(s).', attention: ['Bo: Deploy'] },
  },
};

describe('OrganizationSnapshotPanel', () => {
  it('shows freshness, hierarchy, work, human actions, budget and blockers', async () => {
    server.use(http.get('*/api/v1/organization/snapshot', () => HttpResponse.json(ENVELOPE)));
    render(<OrganizationSnapshotPanel />);

    expect(await screen.findByText(ENVELOPE.snapshot!.summary.text)).toBeInTheDocument();
    expect(screen.getByText('fresh')).toBeInTheDocument();
    expect(screen.getByText(/v2/)).toBeInTheDocument();
    expect(screen.getByTestId('snapshot-hierarchy')).toHaveTextContent('Lead: 2 direct report(s)');
    expect(screen.getByTestId('snapshot-workforce')).toHaveTextContent('Work: 1 active, 1 completed, 1 blocked');
    expect(screen.getByTestId('snapshot-human actions')).toHaveTextContent('1 pending approval(s)');
    expect(screen.getByTestId('snapshot-budget')).toHaveTextContent('$25.00 of $1000.00 spent');
    expect(screen.getByTestId('snapshot-budget')).toHaveTextContent('$24.00 pending');
    expect(screen.getByTestId('snapshot-blockers')).toHaveTextContent('Bo: Deploy');
    expect(screen.getByTestId('snapshot-blockers')).toHaveTextContent('Incident (high): DB down');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps the stale snapshot and shows the last refresh error', async () => {
    server.use(
      http.get('*/api/v1/organization/snapshot', () => HttpResponse.json(ENVELOPE)),
      http.post('*/api/v1/organization/snapshot/refresh', () =>
        HttpResponse.json({
          ...ENVELOPE,
          freshness: { status: 'failed_refresh', age_seconds: 900 },
          last_refresh_error: { message: 'OperationalError: timeout', at: '2026-09-29T10:15:00Z' },
          refresh: { outcome: 'failed', version: null },
        }),
      ),
    );
    render(<OrganizationSnapshotPanel />);
    await screen.findByText('fresh');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh snapshot' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Last refresh failed: OperationalError: timeout');
    expect(screen.getByText('failed_refresh')).toBeInTheDocument();
    expect(screen.getByText(ENVELOPE.snapshot!.summary.text)).toBeInTheDocument();
  });

  it('invites a refresh when no snapshot exists yet', async () => {
    server.use(
      http.get('*/api/v1/organization/snapshot', () =>
        HttpResponse.json({ ...ENVELOPE, snapshot: null, version: null, freshness: { status: 'stale', age_seconds: null } }),
      ),
    );
    render(<OrganizationSnapshotPanel />);
    expect(await screen.findByText(/No snapshot yet/)).toBeInTheDocument();
  });

  it('shows an error when the read is refused', async () => {
    server.use(
      http.get('*/api/v1/organization/snapshot', () =>
        HttpResponse.json({ detail: { code: 'SNAPSHOT_FORBIDDEN', message: 'no' } }, { status: 403 }),
      ),
    );
    render(<OrganizationSnapshotPanel />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  });
});
