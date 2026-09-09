import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Activity } from '../Activity';

vi.mock('@/hooks/useEventStream', () => ({
  useEventStream: vi.fn(),
}));

vi.mock('recharts', async () => {
  const original = await vi.importActual('recharts');
  return {
    ...original,
    ResponsiveContainer: ({ children }: { children: any }) => (
      <div data-testid="responsive-container" style={{ width: 800, height: 400 }}>
        {children}
      </div>
    ),
  };
});

describe('Activity page', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
  });

  it('renders activity page without crashing', () => {
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <Activity />
        </QueryClientProvider>
      </MemoryRouter>
    );
    expect(screen.getByText(/Real-Time Audit Log & Telemetry Traces/i)).toBeInTheDocument();
  });
});
