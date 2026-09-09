import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Tasks } from '../Tasks';

vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: vi.fn(),
}));

describe('Tasks page', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
  });

  it('renders tasks page without crashing', () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <Tasks />
        </QueryClientProvider>
      </MemoryRouter>
    );
    expect(screen.getByText(/Task Operations Queue/i)).toBeInTheDocument();
  });
});
