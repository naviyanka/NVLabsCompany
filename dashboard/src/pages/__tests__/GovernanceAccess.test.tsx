import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GovernanceAccess } from '../GovernanceAccess';

const get = vi.fn();
const post = vi.fn();
vi.mock('@/api/client', () => ({
  apiClient: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) },
}));

const cap = (over: Record<string, unknown>) => ({
  id: 'x', name: 'X', category: 'tools', risk: 'write', support: 'enforced',
  state: 'allowed', explanation: 'Runs.', ...over,
});
const CAPS = [
  cap({ id: 'tool.http-request', name: 'HTTP request' }),
  cap({ id: 'computer.browser', name: 'Browser control', category: 'computer_use',
    support: 'unsupported', state: 'unsupported', explanation: 'Not preventable.' }),
];

let restrictions: unknown;
let runtime: unknown;

function respond(path: string) {
  if (path.endsWith('/agents')) return { items: [{ id: 'a1', name: 'Atlas', role: 'engineer' }] };
  if (path.endsWith('/restrictions')) return restrictions;
  if (path.endsWith('/effective-access')) return { capabilities: CAPS };
  if (path.endsWith('/runtime')) return runtime;
  if (path.endsWith('/grants')) return { items: [] };
  return { items: [] };
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GovernanceAccess />
    </QueryClientProvider>
  );
}

describe('GovernanceAccess', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    post.mockResolvedValue({});
    get.mockImplementation((path: string) => Promise.resolve(respond(path)));
    restrictions = { lockdown: null, isolated_agents: [] };
    runtime = { attempts: [], turns: [] };
  });

  it('shows what the engine says and offers no control on an unenforceable capability', async () => {
    mount();
    const row = await screen.findByTestId('cap-computer.browser');
    expect(within(row).getByText('Not enforceable')).toBeInTheDocument();
    expect(within(row).queryByRole('button')).toBeNull();
    expect(within(row).queryByRole('switch')).toBeNull();
    expect(within(row).queryByRole('checkbox')).toBeNull();
    expect(within(await screen.findByTestId('cap-tool.http-request')).getByText('Enforced'))
      .toBeInTheDocument();
  });

  it('locks down only after a reason and the confirmation phrase', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: /lock down company/i }));
    const go = screen.getByRole('button', { name: /^lock down$/i });
    expect(go).toBeDisabled();
    const reason = screen.getAllByLabelText('Reason').slice(-1)[0] as HTMLElement;
    fireEvent.change(reason, { target: { value: 'incident drill' } });
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'LOCK' } });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'DOWN' } });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'LOCKDOWN' } });
    fireEvent.click(go);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/governance/lockdown', {
        reason: 'incident drill', confirm: 'LOCKDOWN',
      })
    );
  });

  it('shows an active lockdown and releases it with its own phrase', async () => {
    restrictions = {
      lockdown: { id: 'r1', kind: 'lockdown', agent_id: null, reason: 'drill', created_by: 'p' },
      isolated_agents: [],
    };
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Company lockdown is active: drill');
    fireEvent.click(screen.getByRole('button', { name: /release lockdown/i }));
    const reason = screen.getAllByLabelText('Reason').slice(-1)[0] as HTMLElement;
    fireEvent.change(reason, { target: { value: 'drill is over' } });
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'LOCKDOWN' } });
    expect(screen.getByRole('button', { name: /^release$/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Confirmation'), { target: { value: 'RELEASE LOCKDOWN' } });
    fireEvent.click(screen.getByRole('button', { name: /^release$/i }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/governance/lockdown/release', {
        reason: 'drill is over', confirm: 'RELEASE LOCKDOWN',
      })
    );
  });

  it('cancels running work with a reason', async () => {
    runtime = {
      attempts: [{ id: 'abcdef123456', agent_id: 'a1', status: 'running', cancel_requested: false }],
      turns: [],
    };
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Runtime' }));
    const cancel = await screen.findByRole('button', { name: 'Cancel' });
    expect(cancel).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'stop this work' } });
    fireEvent.click(cancel);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/v1/governance/runtime/attempts/abcdef123456/cancel', { reason: 'stop this work' }
      )
    );
  });
});
