import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GovernanceAccess } from '../GovernanceAccess';

// The signed-in role (`isAdmin`) is a decoy: only the server's `can_write` may decide.
const auth = vi.hoisted(() => ({
  status: 'authenticated', isAdmin: false,
  me: { company_id: 'c1', user: { id: 'u1' } } as { company_id: string; user: { id: string } } | null,
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth }));
const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
  },
}));

let me: () => Promise<unknown>;
const G = '/api/v1/governance';
const rule = { name: 'freeze', effect: 'deny', priority: 10, description: null, conditions: {} };
const draft = {
  id: 'd1', status: 'draft', base_version: 3, stale: false, rules: [rule], reason: 'Freeze things',
  ticket_ref: null, created_by: 'alice', reviewers: [], created_at: '2026-09-01T10:00:00',
  updated_at: '2026-09-01T10:05:00', published_version: null,
  diff: { added: [rule], removed: [], changed: [] },
  affects: { all_agents: true, agent_ids: [], capability_ids: [] }, loosens: false, findings: [],
};
const version = (n: number, status: string) => ({
  version: n, status, base_version: n - 1, published_by: 'bob', reason: 'r', rollback_of: null,
  rule_count: 1, created_at: '2026-09-02T09:00:00',
  diff_from_previous: { added: [], removed: [], changed: [] },
  affects: { all_agents: true, agent_ids: [], capability_ids: [] },
});

function respond(path: string): unknown {
  if (path.endsWith('/me')) return me();
  if (path.endsWith('/agents')) return { items: [{ id: 'a1', name: 'Atlas', role: 'engineer' }] };
  if (path.endsWith('/restrictions')) return { lockdown: null, isolated_agents: [] };
  if (path.endsWith('/effective-access')) return { capabilities: [] };
  if (path.endsWith('/catalog')) return { capabilities: [] };
  if (path.endsWith('/policy')) return { version: 3, rules: [rule] };
  if (path.endsWith('/drafts')) return { items: [draft] };
  if (path.endsWith('/drafts/d1/impact')) return { capability_diff: { changes: [], excluded: [] }, findings: [] };
  if (path.endsWith('/versions')) return { items: [version(3, 'active'), version(2, 'superseded')] };
  if (path.endsWith('/versions/2/rollback-preview')) {
    return { target_version: 2, current_version: 3, loosens: false, applies_at_once: true, findings: [],
      affects: { all_agents: true, agent_ids: [], capability_ids: [] },
      diff: { added: [], removed: [], changed: [] } };
  }
  if (path.endsWith('/versions/2')) return version(2, 'superseded');
  if (path.endsWith('/versions/3')) return version(3, 'active');
  if (path.endsWith('/autonomy-presets')) {
    return { items: [{ key: 'advisory', label: 'Advisory', summary: 'Read-only.', unavailable_reason: null }] };
  }
  if (path.endsWith('/runtime')) {
    return { attempts: [{ id: 'abcdef123456', agent_id: 'a1', status: 'running', cancel_requested: false }], turns: [] };
  }
  if (path.endsWith('/grants')) {
    return { items: [
      { id: 'g1', agent_id: 'a1', tool_name: 'http-request', effect: 'allow', status: 'active',
        expires_at: '2026-09-30T10:00:00', requested_by: 'alice' },
      { id: 'g2', agent_id: 'a1', tool_name: 'http-request', effect: 'allow', status: 'pending_approval',
        expires_at: '2026-09-30T10:00:00', requested_by: 'alice' },
    ] };
  }
  if (path.endsWith('/audit')) return { items: [{ id: 'x1', action: 'governance.lockdown', actor: 'bob', created_at: '2026-09-01T10:00:00' }] };
  return { items: [] };
}

function tree() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}><GovernanceAccess /></QueryClientProvider>
  );
}
const tab = async (name: string) => fireEvent.click(await screen.findByRole('button', { name }));
const settled = () => screen.findByRole('option', { name: 'Atlas' });

/** Every control that writes. Each query returns what is on screen right now. */
async function writeControls() {
  const found: string[] = [];
  const has = (label: string, el: HTMLElement | null) => { if (el) found.push(label); };
  const q = (role: Parameters<typeof screen.queryByRole>[0], name: string | RegExp) =>
    screen.queryAllByRole(role, { name })[0] ?? null;

  has('lockdown', q('button', /lock down company|release lockdown/i));
  has('isolate', q('button', /^isolate agent$/i));
  await tab('Grants');
  await screen.findByText(/g1|http-request/, undefined, { timeout: 2000 }).catch(() => undefined);
  has('grant form', q('form', 'New temporary grant'));
  has('grant approve', q('button', /^approve$/i));
  has('grant revoke', q('button', /^revoke$/i));
  await tab('Policy');
  await screen.findByRole('table', { name: 'Policy drafts' });
  has('new draft', q('button', /new draft/i));
  fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze things/ }));
  has('save draft', await screen.findByText('Edit policy draft').then(() => q('button', 'Save draft')));
  has('publish', q('button', /review and publish/i));
  has('discard', q('button', /discard draft/i));
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Versions' }));
  fireEvent.click(await screen.findByRole('button', { name: 'View version 2' }));
  await screen.findByText(/Changes from the previous version/);
  has('rollback', q('button', /roll back to this version/i));
  await tab('Autonomy presets');
  await screen.findByText('Advisory');
  has('preset draft', q('button', /^Preview /));
  await tab('Runtime');
  await screen.findByText(/Attempt abcdef12/);
  has('runtime cancel', q('button', /^cancel$/i));
  return found;
}

const ALL = [
  'lockdown', 'isolate', 'grant form', 'grant approve', 'grant revoke', 'new draft', 'save draft',
  'publish', 'discard', 'rollback', 'preset draft', 'runtime cancel',
];

describe('Governance Studio permission', () => {
  beforeEach(() => {
    auth.status = 'authenticated';
    auth.isAdmin = false;
    auth.me = { company_id: 'c1', user: { id: 'u1' } };
    me = () => Promise.resolve({ can_write: true });
    get.mockReset(); post.mockReset(); put.mockReset();
    get.mockImplementation((path: string) => Promise.resolve(respond(path)));
    post.mockResolvedValue({});
  });

  it('an administrator, as the server says, sees every write control', async () => {
    render(tree());
    await waitFor(() => expect(screen.getByRole('button', { name: /lock down company/i })).toBeInTheDocument());
    expect(await writeControls()).toEqual(ALL);
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('a viewer sees the read-only state and no write control on any tab', async () => {
    me = () => Promise.resolve({ can_write: false });
    render(tree());
    expect(await screen.findByRole('note')).toHaveTextContent('View only');
    await settled();
    expect(await writeControls()).toEqual([]);
  });

  it('a viewer still reads the matrix, the audit trail and the history', async () => {
    me = () => Promise.resolve({ can_write: false });
    render(tree());
    await settled();
    await tab('Audit');
    expect(await screen.findByText('lockdown')).toBeInTheDocument();
    await tab('Policy');
    expect(await screen.findByRole('table', { name: 'Policy drafts' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Versions' }));
    expect(await screen.findByRole('table', { name: 'Policy versions' })).toBeInTheDocument();
    await tab('Simulator');
    expect(await screen.findByRole('button', { name: 'Simulate' })).toBeInTheDocument();
  });

  it('a viewer who loses nothing by clicking: no write request is ever sent', async () => {
    me = () => Promise.resolve({ can_write: false });
    render(tree());
    await settled();
    await writeControls();
    expect(post).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
  });

  it('forged client role data does not override the server', async () => {
    auth.isAdmin = true;
    me = () => Promise.resolve({ can_write: false });
    render(tree());
    expect(await screen.findByRole('note')).toHaveTextContent('View only');
    await settled();
    expect(await writeControls()).toEqual([]);
  });

  it('the server wins in the other direction too', async () => {
    auth.isAdmin = false;
    render(tree());
    expect(await screen.findByRole('button', { name: /lock down company/i })).toBeInTheDocument();
  });

  it('a truthy but not-true flag is not a yes', async () => {
    me = () => Promise.resolve({ can_write: 'true' });
    render(tree());
    await settled();
    expect(screen.queryByRole('button', { name: /lock down company/i })).toBeNull();
  });

  it('keeps every control off while the permission is loading', async () => {
    let release: (v: unknown) => void = () => undefined;
    me = () => new Promise((r) => { release = r; });
    render(tree());
    await settled();
    expect(screen.queryByRole('button', { name: /lock down company/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^isolate agent$/i })).toBeNull();
    release({ can_write: true });
    expect(await screen.findByRole('button', { name: /lock down company/i })).toBeInTheDocument();
  });

  it('keeps every control off, and says so, when the permission cannot be read', async () => {
    me = () => Promise.reject(new Error('API Error 500'));
    render(tree());
    expect(await screen.findByRole('note')).toHaveTextContent('Could not confirm your permission');
    await settled();
    expect(await writeControls()).toEqual([]);
  });

  it('asks the server again when the user or company changes, and follows the new answer', async () => {
    me = () => Promise.resolve({ can_write: auth.me?.company_id === 'c1' });
    // one client for every render so the cache is shared, as in the app
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = () => <QueryClientProvider client={client}><GovernanceAccess /></QueryClientProvider>;
    const { rerender } = render(view());
    expect(await screen.findByRole('button', { name: /lock down company/i })).toBeInTheDocument();
    const calls = () => get.mock.calls.filter(([p]) => String(p).endsWith('/me')).length;
    const before = calls();
    auth.me = { company_id: 'c2', user: { id: 'u1' } };
    rerender(view());
    await waitFor(() => expect(screen.queryByRole('button', { name: /lock down company/i })).toBeNull());
    expect(calls()).toBeGreaterThan(before);
    expect(await screen.findByRole('note')).toHaveTextContent('View only');
  });

  it('removes every control on logout and never asks while signed out', async () => {
    const { rerender } = render(tree());
    expect(await screen.findByRole('button', { name: /lock down company/i })).toBeInTheDocument();
    auth.status = 'anonymous';
    auth.me = null;
    get.mockClear();
    rerender(tree());
    await waitFor(() => expect(screen.queryByRole('button', { name: /lock down company/i })).toBeNull());
    expect(get.mock.calls.some(([p]) => String(p).endsWith('/me'))).toBe(false);
  });

  it('closes an open confirmation when the permission goes away', async () => {
    me = () => Promise.resolve({ can_write: auth.me?.user.id === 'u1' });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = () => <QueryClientProvider client={client}><GovernanceAccess /></QueryClientProvider>;
    const { rerender } = render(view());
    fireEvent.click(await screen.findByRole('button', { name: /lock down company/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    auth.me = { company_id: 'c1', user: { id: 'u2' } };
    rerender(view());
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(post).not.toHaveBeenCalledWith(`${G}/lockdown`, expect.anything());
  });
});
