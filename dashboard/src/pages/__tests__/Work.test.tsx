import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { Work } from '../Work';

vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

const task = {
  id: 't1',
  title: 'Write the summary',
  status: 'in_review',
  assignee: { id: 'a1', name: 'Eve' },
  attempt: {
    attempt_id: 'att1',
    attempt_number: 1,
    status: 'verifying',
    awaiting_review: true,
    verification: 'pending_review',
    deliverable: 'The finished summary',
    error_code: null,
    stale: false,
  },
  result: null,
  failure: null,
  updated_at: null,
};

const list = {
  metrics: { awaiting_review: 1, stale_attempts: 0 },
  work: [
    {
      id: 'w1',
      title: 'Quarterly report',
      status: 'in_progress',
      assignee: { id: 'm1', name: 'Max' },
      attempt: null,
      result: null,
      failure: null,
      updated_at: null,
      tasks: [task],
    },
  ],
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <Work />
    </QueryClientProvider>
  );
}

describe('Work page', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockResolvedValue(list);
    vi.mocked(apiClient.post).mockResolvedValue({});
  });

  it('shows work, its task, the deliverable awaiting review and the owner', async () => {
    renderPage();
    expect(await screen.findByText('Quarterly report')).toBeInTheDocument();
    expect(screen.getByText('Write the summary')).toBeInTheDocument();
    expect(screen.getByText('The finished summary')).toBeInTheDocument();
    expect(screen.getByText(/attempt 1: awaiting review/)).toBeInTheDocument();
  });

  it('verifies with one call to the review route', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Verify' }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith('/api/v1/work/attempts/att1/review', {
        decision: 'verify',
        reason: null,
      })
    );
  });

  it('needs a reason to reject', async () => {
    renderPage();
    const reject = await screen.findByRole('button', { name: 'Reject' });
    expect(reject).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Rejection reason'), { target: { value: 'too thin' } });
    expect(reject).toBeEnabled();
  });

  it('creates work with an idempotency key', async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText('Work title'), { target: { value: 'New order' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create work order' }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [path, body, headers] = vi.mocked(apiClient.post).mock.calls[0]!;
    expect(path).toBe('/api/v1/work');
    expect(body).toMatchObject({ title: 'New order' });
    expect((headers as Record<string, string>)['Idempotency-Key']).toBeTruthy();
  });
});
