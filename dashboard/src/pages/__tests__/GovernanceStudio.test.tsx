import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GovernanceAccess } from '../GovernanceAccess';

// `isAdmin` is false on purpose: the screen must follow the server's `can_write`, never this.
const auth = vi.hoisted(() => ({
  status: 'authenticated', isAdmin: false,
  me: { company_id: 'c1', user: { id: 'u1' } },
}));
const server = vi.hoisted(() => ({ canWrite: true }));
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

const G = '/api/v1/governance';
const rule = (over: Record<string, unknown> = {}) => ({
  name: 'freeze network', effect: 'deny', priority: 10, description: null,
  conditions: { tool_name: ['http-request'] }, ...over,
});
const draft = (over: Record<string, unknown> = {}) => ({
  id: 'd1', status: 'draft', base_version: 3, stale: false, rules: [rule()], reason: 'Freeze outbound HTTP',
  ticket_ref: null, created_by: 'alice', reviewers: [], created_at: '2026-09-01T10:00:00',
  updated_at: '2026-09-01T10:05:00', published_version: null,
  diff: { added: [rule()], removed: [], changed: [] },
  affects: { all_agents: true, agent_ids: [], capability_ids: ['tool.http-request'] },
  loosens: false, findings: [], ...over,
});
const CATALOG = [
  { id: 'tool.http-request', name: 'HTTP request', category: 'tools', support: 'enforced',
    tool_name: 'http-request', risk: 'write', explicit_allow_required: false,
    scope_schema: { conditions: ['tool_name', 'agent_id'] } },
  { id: 'computer.browser', name: 'Browser control', category: 'computer_use', support: 'unsupported',
    tool_name: null, risk: 'write', explicit_allow_required: false },
];
const DECISION = {
  state: 'denied', decision: 'deny', code: 'POLICY_DENY', explanation: 'Denied by freeze network.',
  source: 'policy:freeze network', approval: { required: false }, validity: null,
  backend_support: 'enforced', blockers: ['Feature gate tool_binding_enforcement is \'log\', not \'enforce\''],
  steps: [
    { label: 'Capability can be enforced', result: 'checked' },
    { label: 'Explicit deny rule', result: 'decided' },
    { label: 'Default deny', result: 'not reached' },
  ],
};

let drafts: unknown[];
let presetItems: unknown[];
let grants: unknown[];

function respond(path: string): unknown {
  if (path.endsWith('/me')) return { can_write: server.canWrite };
  if (path.endsWith('/agents')) return { items: [{ id: 'a1', name: 'Atlas', role: 'engineer' }] };
  if (path.endsWith('/restrictions')) return { lockdown: null, isolated_agents: [] };
  if (path.endsWith('/catalog')) return { capabilities: CATALOG };
  if (path.endsWith('/policy')) return { version: 3, rules: [rule({ name: 'live rule' })] };
  if (path.endsWith('/drafts')) return { items: drafts };
  if (path.endsWith('/drafts/d1/impact')) {
    return { capability_diff: { changes: [{ capability_id: 'tool.http-request', name: 'HTTP request', risk: 'write',
      before: 'allow', after: 'deny', code: 'POLICY_DENY' }], excluded: [] }, findings: [] };
  }
  if (path.endsWith('/versions')) {
    return { items: [
      { version: 3, status: 'active', base_version: 2, published_by: 'bob', reason: 'tighten', rollback_of: null, rule_count: 2, created_at: '2026-09-02T09:00:00' },
      { version: 2, status: 'superseded', base_version: 1, published_by: 'carol', reason: 'first', rollback_of: null, rule_count: 1, created_at: '2026-09-01T09:00:00' },
    ] };
  }
  if (path.endsWith('/versions/2/rollback-preview')) {
    return { target_version: 2, current_version: 3, loosens: false, applies_at_once: true, findings: [],
      affects: { all_agents: true, agent_ids: [], capability_ids: [] },
      diff: { added: [], removed: [rule({ name: 'extra deny' })], changed: [] } };
  }
  if (path.endsWith('/versions/3')) {
    return { version: 3, status: 'active', base_version: 2, published_by: 'bob', reason: 'tighten',
      rollback_of: null, rule_count: 2, created_at: '2026-09-02T09:00:00',
      diff_from_previous: { added: [], removed: [], changed: [] },
      affects: { all_agents: false, agent_ids: ['a1'], capability_ids: [] } };
  }
  if (path.endsWith('/versions/2')) {
    return { version: 2, status: 'superseded', base_version: 1, published_by: 'carol', reason: 'first',
      rollback_of: null, rule_count: 1, created_at: '2026-09-01T09:00:00',
      diff_from_previous: { added: [rule({ name: 'first rule' })], removed: [], changed: [] },
      affects: { all_agents: true, agent_ids: [], capability_ids: [] } };
  }
  if (path.endsWith('/autonomy-presets')) return { items: presetItems };
  if (path.endsWith('/autonomy-presets/advisory')) {
    return { preset: 'advisory', base_version: 3, applied: false, draft: null,
      rules: [rule({ name: 'autonomy:a1:deny' })],
      capability_diff: { changes: [{ capability_id: 'tool.http-request', name: 'HTTP request', risk: 'write',
        before: 'allow', after: 'deny', code: 'POLICY_DENY' }],
      excluded: [{ capability_id: 'computer.browser', name: 'Browser control', label: 'Not enforceable' }] } };
  }
  if (path.endsWith('/grants')) return { items: grants };
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

const tab = async (name: string) => fireEvent.click(await screen.findByRole('button', { name }));
const conflict = () => Object.assign(new Error('API Error 409: STALE_BASE: moved'), { status: 409 });

describe('Governance Studio', () => {
  beforeEach(() => {
    server.canWrite = true;
    get.mockReset(); post.mockReset(); put.mockReset();
    get.mockImplementation((path: string) => Promise.resolve(respond(path)));
    post.mockResolvedValue({});
    put.mockResolvedValue(draft());
    drafts = [draft()];
    grants = [];
    presetItems = [
      { key: 'advisory', label: 'Advisory', summary: 'Read-only tools.', unavailable_reason: null },
      { key: 'delegated_autonomy', label: 'Delegated autonomy', summary: 'For a manager.',
        unavailable_reason: 'Only an agent with at least one direct report can hold this preset' },
    ];
  });

  describe('simulator', () => {
    it('evaluates the chosen capability against a draft and shows the whole explanation', async () => {
      post.mockResolvedValue({
        current: { ...DECISION, decision: 'allow', code: 'DEFAULT_ALLOW', state: 'allowed', blockers: [], steps: [] },
        proposed: DECISION,
        findings: [{ code: 'HIGH_RISK_NO_APPROVAL', severity: 'medium', detail: 'No approval.' }],
        notes: ['Nothing was called, spent or sent.'],
      });
      mount();
      await tab('Simulator');
      expect(screen.getByRole('note')).toHaveTextContent(/calls no tool, spends no temporary grant/i);
      await screen.findByRole('option', { name: /Browser control \(not enforceable\)/ });
      fireEvent.change(screen.getByLabelText('Policy to test'), { target: { value: 'd1' } });
      fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'tool.http-request' } });
      fireEvent.click(screen.getByRole('button', { name: 'Simulate' }));
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/simulate`, {
        agent_id: 'a1', capability_id: 'tool.http-request', proposed_rules: [rule()],
      }));
      const withDraft = await screen.findByRole('region', { name: 'Decision with the draft' });
      expect(within(withDraft).getByText('POLICY_DENY')).toBeInTheDocument();
      expect(within(withDraft).getByText('policy:freeze network')).toBeInTheDocument();
      expect(within(withDraft).getByText(/decided here/)).toBeInTheDocument();
      expect(within(withDraft).getByText(/Feature gate tool_binding_enforcement/)).toBeInTheDocument();
      expect(screen.getByRole('region', { name: 'Decision now' })).toHaveTextContent('ALLOW');
      expect(screen.getByText('HIGH_RISK_NO_APPROVAL')).toBeInTheDocument();
    });

    it('offers only catalogue choices, a session and a policy: no free JSON or code', async () => {
      const { container } = mount();
      await tab('Simulator');
      await screen.findByRole('option', { name: /HTTP request/ });
      expect(container.querySelector('textarea')).toBeNull();
      expect(screen.getAllByRole('textbox')).toHaveLength(1);
      expect(screen.getByLabelText(/Session \(optional\)/)).toBeInTheDocument();
      expect(screen.getByText(/Task and resource scopes are not enforceable/)).toBeInTheDocument();
    });

    it('refuses a session that is not an id', async () => {
      mount();
      await tab('Simulator');
      await screen.findByRole('option', { name: /HTTP request/ });
      fireEvent.change(screen.getByLabelText(/Session \(optional\)/), { target: { value: 'not-an-id' } });
      expect(screen.getByRole('button', { name: 'Simulate' })).toBeDisabled();
      expect(screen.getByRole('alert')).toHaveTextContent('valid id');
    });
  });

  describe('drafts', () => {
    it('lists owner, base version, status, reason, author and staleness', async () => {
      drafts = [draft(), draft({ id: 'd2', stale: true, reason: 'Old idea', base_version: 1 })];
      mount();
      await tab('Policy');
      const table = await screen.findByRole('table', { name: 'Policy drafts' });
      const stale = within(table).getByText('Old idea').closest('tr') as HTMLElement;
      expect(within(stale).getByText('STALE')).toBeInTheDocument();
      expect(within(stale).getByText('1')).toBeInTheDocument();
      const fresh = within(table).getByText('Freeze outbound HTTP').closest('tr') as HTMLElement;
      expect(within(fresh).getAllByText('alice').length).toBeGreaterThan(0);
      expect(within(fresh).getByText('Open')).toBeInTheDocument();
    });

    it('saves an edit with the updated_at it loaded', async () => {
      mount();
      await tab('Policy');
      fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
      fireEvent.change(await screen.findByLabelText(/^Priority/), { target: { value: '25' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save draft' }));
      await waitFor(() => expect(put).toHaveBeenCalledWith(`${G}/drafts/d1`, expect.objectContaining({
        expected_updated_at: '2026-09-01T10:05:00',
        rules: [rule({ priority: 25 })],
      })));
    });

    it('shows a conflict instead of overwriting when the draft moved', async () => {
      put.mockRejectedValue(conflict());
      mount();
      await tab('Policy');
      fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
      fireEvent.click(await screen.findByRole('button', { name: 'Save draft' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(/Nothing was saved/);
    });

    it('never offers an unenforceable capability to a rule', async () => {
      mount();
      await tab('Policy');
      fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
      const box = await screen.findByRole('checkbox', { name: /Browser control/ }).catch(() => null);
      expect(box).toBeNull();
      const http = await screen.findByRole('checkbox', { name: /HTTP request/ });
      expect(http).toBeChecked();
    });
  });

  describe('publish', () => {
    const open = async () => {
      mount();
      await tab('Policy');
      fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
      fireEvent.click(await screen.findByRole('button', { name: /Review and publish/ }));
    };

    it('needs the reviewed box, shows the exact diff and simulator summary, then sends the version', async () => {
      await open();
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByRole('list', { name: 'Rule changes' })).toHaveTextContent('freeze network');
      expect(await within(dialog).findByRole('table', { name: 'Capability changes' })).toHaveTextContent('HTTP request');
      const go = within(dialog).getByRole('button', { name: 'Publish' });
      expect(go).toBeDisabled();
      fireEvent.click(within(dialog).getByRole('checkbox', { name: /reviewed the exact changes/ }));
      expect(go).toBeEnabled();
      fireEvent.click(go);
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/drafts/d1/publish`, {
        reason: undefined, expected_version: 3,
      }));
    });

    it('shows the conflict when another publish got there first and offers no retry', async () => {
      post.mockRejectedValue(conflict());
      await open();
      const dialog = await screen.findByRole('dialog');
      fireEvent.click(within(dialog).getByRole('checkbox', { name: /reviewed the exact changes/ }));
      fireEvent.click(within(dialog).getByRole('button', { name: 'Publish' }));
      expect(await within(dialog).findByRole('alert')).toHaveTextContent(/rules changed while you were reviewing/);
      expect(within(dialog).getByRole('button', { name: 'Publish' })).toBeDisabled();
    });

    it('blocks a stale draft and warns about a loosening change', async () => {
      drafts = [draft({ stale: true, base_version: 1, loosens: true })];
      await open();
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText('LOOSENS ACCESS')).toBeInTheDocument();
      expect(within(dialog).getByText(/cannot be published/)).toBeInTheDocument();
      fireEvent.click(within(dialog).getByRole('checkbox', { name: /reviewed the exact changes/ }));
      expect(within(dialog).getByRole('button', { name: 'Publish' })).toBeDisabled();
    });

    it('lists high risk findings as advisory warnings', async () => {
      drafts = [draft({ findings: [{ code: 'WILDCARD_HIGH_RISK', severity: 'high', detail: 'Matches every tool.' }] })];
      await open();
      const dialog = await screen.findByRole('dialog');
      expect(within(dialog).getByText('WILDCARD_HIGH_RISK')).toBeInTheDocument();
      expect(within(dialog).getByText(/advisory and do not block/)).toBeInTheDocument();
    });
  });

  describe('versions and rollback', () => {
    const toVersions = async () => {
      mount();
      await tab('Policy');
      fireEvent.click(await screen.findByRole('button', { name: 'Versions' }));
    };

    it('shows history, the diff from the previous version and the affected scope', async () => {
      await toVersions();
      expect(await screen.findByRole('table', { name: 'Policy versions' })).toHaveTextContent('superseded');
      fireEvent.click(screen.getByRole('button', { name: 'View version 2' }));
      expect(await screen.findByText(/Changes from the previous version/)).toBeInTheDocument();
      expect(await screen.findByText(/Affected: every agent/)).toBeInTheDocument();
    });

    it('previews the exact diff and rolls back with a reason, never deleting history', async () => {
      post.mockResolvedValue({ applied: true, version: 4 });
      await toVersions();
      fireEvent.click(await screen.findByRole('button', { name: 'View version 2' }));
      const roll = await screen.findByRole('button', { name: /Roll back to this version/ });
      await waitFor(() => expect(roll).toBeEnabled());
      fireEvent.click(roll);
      const dialog = await screen.findByRole('dialog');
      expect(await within(dialog).findByRole('list', { name: 'Rule changes' })).toHaveTextContent('extra deny');
      expect(dialog).toHaveTextContent('never deletes history');
      const go = within(dialog).getByRole('button', { name: 'Roll back' });
      expect(go).toBeDisabled();
      fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'undo the change' } });
      fireEvent.click(within(dialog).getByRole('checkbox', { name: /reviewed the exact changes/ }));
      fireEvent.click(go);
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/versions/2/rollback`, {
        reason: 'undo the change', expected_version: 3,
      }));
      expect(await screen.findByText(/applied as new version 4/)).toBeInTheDocument();
    });

    it('cannot roll back to the active version', async () => {
      await toVersions();
      fireEvent.click(await screen.findByRole('button', { name: 'View version 3' }));
      expect(await screen.findByRole('button', { name: /This is the active version/ })).toBeDisabled();
    });
  });

  describe('autonomy presets', () => {
    it('disables a preset the agent cannot hold and says why, with no direct setter', async () => {
      mount();
      await tab('Autonomy presets');
      expect(await screen.findByRole('button', { name: 'Preview Delegated autonomy' })).toBeDisabled();
      expect(screen.getByText(/at least one direct report/)).toBeInTheDocument();
      expect(screen.queryByRole('slider')).toBeNull();
      expect(screen.queryByRole('switch')).toBeNull();
    });

    it('creates a draft only, after showing the exact capability diff', async () => {
      post.mockResolvedValue({ draft: { id: 'dx' } });
      mount();
      await tab('Autonomy presets');
      fireEvent.click(await screen.findByRole('button', { name: 'Preview Advisory' }));
      const dialog = await screen.findByRole('dialog');
      expect(await within(dialog).findByRole('table', { name: 'Capability changes' })).toHaveTextContent('HTTP request');
      expect(within(dialog).getByText(/Browser control: Not enforceable/)).toBeInTheDocument();
      expect(dialog).toHaveTextContent('never bypasses role, designation or an existing explicit deny');
      const go = within(dialog).getByRole('button', { name: 'Create policy draft' });
      expect(go).toBeDisabled();
      fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'try advisory' } });
      fireEvent.click(go);
      await waitFor(() => expect(post).toHaveBeenCalledWith(
        `${G}/agents/a1/autonomy-presets/advisory/draft`, { reason: 'try advisory' }));
      expect(await screen.findByText(/Nothing is active yet/)).toBeInTheDocument();
      expect(post).not.toHaveBeenCalledWith(expect.stringContaining('/publish'), expect.anything());
    });
  });

  describe('confirmations', () => {
    it('asks before revoking a grant', async () => {
      grants = [{ id: 'g1', agent_id: 'a1', tool_name: 'http-request', effect: 'allow', status: 'active',
        expires_at: '2026-09-30T10:00:00', requested_by: 'alice' }];
      mount();
      await tab('Grants');
      fireEvent.change(await screen.findByLabelText('Reason'), { target: { value: 'no longer needed' } });
      fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }));
      expect(post).not.toHaveBeenCalled();
      const dialog = await screen.findByRole('dialog');
      fireEvent.click(within(dialog).getByRole('button', { name: 'Revoke grant' }));
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/grants/g1/revoke`, { reason: 'no longer needed' }));
    });

    it('asks before isolating an agent', async () => {
      mount();
      await waitFor(() => expect(screen.getByRole('option', { name: 'Atlas' })).toBeInTheDocument());
      fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'suspicious output' } });
      fireEvent.click(screen.getByRole('button', { name: 'Isolate agent' }));
      expect(post).not.toHaveBeenCalled();
      const dialog = await screen.findByRole('dialog');
      fireEvent.click(within(dialog).getByRole('button', { name: 'Isolate agent' }));
      await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/agents/a1/isolate`, { reason: 'suspicious output' }));
    });
  });

  it('states are not conveyed by color alone and tabs are keyboard reachable buttons', async () => {
    mount();
    const nav = await screen.findByRole('navigation', { name: 'Sections' });
    const buttons = within(nav).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual([
      'Effective access', 'Simulator', 'Policy', 'Autonomy presets', 'Runtime', 'Grants', 'Audit',
    ]);
    expect(buttons[0]).toHaveAttribute('aria-current', 'page');
  });
});
