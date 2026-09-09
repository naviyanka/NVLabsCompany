import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Approvals } from '../Approvals';

vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: vi.fn(),
}));

describe('Approvals page', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
  });

  it('renders approvals page without crashing', () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <Approvals />
        </QueryClientProvider>
      </MemoryRouter>
    );
    expect(screen.getByText(/Governance & Action Approval Gate/i)).toBeInTheDocument();
  });
});
