import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GovernanceAccess } from '../GovernanceAccess';

// Capability text is display only: every request must keep sending the technical id.
const auth = vi.hoisted(() => ({
  status: 'authenticated', isAdmin: false, me: { company_id: 'c1', user: { id: 'u1' } },
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
const LONG = 'A'.repeat(200);
const HTTP = {
  id: 'tool.http-request', name: 'HTTP request', display_name: 'Make an HTTP Request',
  description: 'Sends a request to a web address. It can reach outside services.',
  limitations: 'Only the engine decides.', examples: ['Fetch a status page'],
  category: 'tools', risk: 'write', support: 'enforced', tool_name: 'http-request',
  explicit_allow_required: false, scope_schema: { conditions: ['tool_name'] },
};
const SEARCH = {
  id: 'tool.web-search', name: 'Web search', display_name: 'Search the Web',
  description: 'Looks something up on the web.', category: 'tools', risk: 'read', support: 'enforced',
  tool_name: 'web-search', explicit_allow_required: false,
};
const BROWSER = {
  id: 'computer.browser', name: 'Browser control', display_name: 'Control a Web Browser',
  description: 'Drives a browser. NEXUS cannot currently enforce this.',
  limitations: 'NEXUS cannot currently enforce this capability.',
  category: 'computer_use', risk: 'write', support: 'unsupported', tool_name: null,
  explicit_allow_required: false,
};
const LONGCAP = {
  id: `tool.${LONG}`, name: LONG, display_name: LONG, description: LONG, category: 'tools',
  risk: 'read', support: 'enforced', tool_name: LONG, explicit_allow_required: false,
};
const decide = (c: Record<string, unknown>, over: Record<string, unknown> = {}) => ({
  ...c, state: 'allowed', code: 'DEFAULT_ALLOW', source: 'default policy',
  explanation: 'engine: allowed by default',
  plain_explanation: 'Nothing restricts this, so it runs.', ...over,
});

let catalog: Record<string, unknown>[];
let access: Record<string, unknown>[];
let grants: unknown[];
let audit: unknown[];
let findings: unknown[];

const draft = {
  id: 'd1', status: 'draft', base_version: 3, stale: false, reason: 'Freeze outbound HTTP',
  ticket_ref: null, created_by: 'alice', reviewers: [], created_at: '2026-09-01T10:00:00',
  updated_at: '2026-09-01T10:05:00', published_version: null,
  rules: [{ name: 'freeze', effect: 'deny', priority: 10, description: null, conditions: { tool_name: ['http-request'] } }],
  diff: { added: [], removed: [], changed: [] },
  affects: { all_agents: true, agent_ids: [], capability_ids: ['tool.http-request', 'tool.brand-new'] },
  loosens: false, findings: [],
};

function respond(path: string) {
  if (path.endsWith('/me')) return { can_write: server.canWrite };
  if (path.endsWith('/agents')) return { items: [{ id: 'a1', name: 'Atlas', role: 'engineer' }] };
  if (path.endsWith('/restrictions')) return { lockdown: null, isolated_agents: [] };
  if (path.endsWith('/effective-access')) return { capabilities: access };
  if (path.endsWith('/catalog')) return { capabilities: catalog };
  if (path.endsWith('/grants')) return { items: grants };
  if (path.endsWith('/audit')) return { items: audit };
  if (path.endsWith('/drafts')) return { items: [draft] };
  if (path.includes('/drafts/d1/impact')) {
    return { capability_diff: { changes: [], excluded: [] }, findings };
  }
  if (path.endsWith('/policy/active')) return { version: 3 };
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

describe('capability names, descriptions and technical ids', () => {
  beforeEach(() => {
    server.canWrite = true;
    for (const m of [get, post, put]) m.mockReset();
    post.mockResolvedValue({ status: 'active' });
    put.mockResolvedValue(draft);
    get.mockImplementation((path: string) => Promise.resolve(respond(path)));
    catalog = [HTTP, SEARCH, BROWSER];
    access = [decide(HTTP), decide(SEARCH), decide(BROWSER, {
      state: 'unsupported', code: 'UNSUPPORTED', plain_explanation: 'NEXUS cannot enforce this.',
    })];
    grants = [];
    audit = [];
    findings = [];
  });

  it('shows the name, the first sentence of the description and the technical id', async () => {
    mount();
    const row = await screen.findByTestId('cap-tool.http-request');
    expect(within(row).getByText('Make an HTTP Request')).toBeInTheDocument();
    expect(within(row).getByText('Sends a request to a web address.')).toBeInTheDocument();
    expect(within(row).queryByText(/reach outside services/)).toBeNull();
    expect(within(row).getByText('tool.http-request').tagName).toBe('CODE');
    expect(within(row).getByText('Nothing restricts this, so it runs.')).toBeInTheDocument();
  });

  it('keeps the reason code, engine message, full text and a copy control in the details', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: /Make an HTTP Request/ }));
    const details = screen.getByLabelText('Make an HTTP Request details');
    expect(details).toHaveTextContent('It can reach outside services.');
    expect(details).toHaveTextContent('DEFAULT_ALLOW');
    expect(details).toHaveTextContent('engine: allowed by default');
    expect(details).toHaveTextContent('Fetch a status page');
    expect(within(details).getByRole('button', { name: 'Copy technical ID tool.http-request' })).toBeInTheDocument();
  });

  it('searches by friendly name, description, category and raw id', async () => {
    mount();
    const box = await screen.findByLabelText('Search capabilities');
    await screen.findByTestId('cap-tool.http-request');
    const shown = () => screen.queryAllByTestId(/^cap-/).map((r) => r.getAttribute('data-testid'));
    fireEvent.change(box, { target: { value: 'search the web' } });
    expect(shown()).toEqual(['cap-tool.web-search']);
    fireEvent.change(box, { target: { value: 'tool.http-request' } });
    expect(shown()).toEqual(['cap-tool.http-request']);
    fireEvent.change(box, { target: { value: 'reach outside' } });
    expect(shown()).toEqual(['cap-tool.http-request']);
    fireEvent.change(box, { target: { value: 'computer use' } });
    expect(shown()).toEqual(['cap-computer.browser']);
    fireEvent.change(box, { target: { value: 'nothing like this' } });
    expect(shown()).toEqual([]);
    expect(screen.getByRole('status')).toHaveTextContent('No capability matches');
  });

  it('gives each name button a label with the name, state, risk and support', async () => {
    mount();
    const button = await screen.findByRole('button', { name: 'Make an HTTP Request, allowed, write risk, Enforced' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    button.focus();
    expect(button).toHaveFocus();
  });

  it('keeps an unsupported capability visibly non-enforceable and non-actionable', async () => {
    mount();
    const row = await screen.findByTestId('cap-computer.browser');
    expect(within(row).getByText('Not enforceable')).toBeInTheDocument();
    expect(within(row).getByText('unsupported')).toBeInTheDocument();
    expect(within(row).queryByRole('switch')).toBeNull();
    expect(within(row).queryByRole('checkbox')).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: /Control a Web Browser/ }));
    expect(screen.getByLabelText('Control a Web Browser details'))
      .toHaveTextContent('NEXUS cannot currently enforce this capability.');
  });

  it('falls back to a readable name, no invented description and the id for an unknown capability', async () => {
    access = [decide({ id: 'tool.mystery_widget', name: 'tool.mystery_widget', category: 'tools',
      risk: 'write', support: 'enforced', tool_name: 'mystery_widget' })];
    mount();
    const row = await screen.findByTestId('cap-tool.mystery_widget');
    expect(within(row).getByText('Mystery Widget')).toBeInTheDocument();
    expect(within(row).getByText('Description unavailable')).toBeInTheDocument();
    expect(within(row).getByText('tool.mystery_widget')).toBeInTheDocument();
    expect(within(row).getByText('Enforced')).toBeInTheDocument();
  });

  it('wraps long text instead of widening the table', async () => {
    access = [decide(LONGCAP)];
    mount();
    const row = await screen.findByTestId(`cap-tool.${LONG}`);
    expect(row.className).toContain('[overflow-wrap:anywhere]');
    expect(row.closest('table')?.className).toContain('table-fixed');
    expect(row.closest('.overflow-x-auto')).toBeNull();
  });

  it('keeps a viewer read-only while still showing names', async () => {
    server.canWrite = false;
    mount();
    await screen.findByTestId('cap-tool.http-request');
    expect(screen.getByText('Make an HTTP Request')).toBeInTheDocument();
    await tab('Grants');
    await screen.findByText('No temporary grants.');
    expect(screen.queryByRole('form', { name: 'New temporary grant' })).toBeNull();
  });

  it('posts the technical tool name for a grant chosen by its friendly name', async () => {
    mount();
    await tab('Grants');
    const option = await screen.findByRole('option', { name: /Make an HTTP Request \(tool\.http-request\)/ });
    fireEvent.change(screen.getByLabelText(/^Tool/), { target: { value: (option as HTMLOptionElement).value } });
    expect(screen.getByLabelText('Selected tool')).toHaveTextContent('Make an HTTP Request');
    expect(screen.getByLabelText('Selected tool')).toHaveTextContent('tool.http-request');
    fireEvent.change(screen.getByLabelText(/^Expires/), { target: { value: '2999-01-01T00:00' } });
    fireEvent.change(screen.getByLabelText('Grant reason'), { target: { value: 'needed for the demo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create grant' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/grants`,
      expect.objectContaining({ tool_name: 'http-request', agent_id: 'a1' })));
  });

  it('names a grant and an audit entry, and shows the stored tool for an unknown one', async () => {
    grants = [
      { id: 'g1', agent_id: 'a1', tool_name: 'http-request', effect: 'allow', status: 'active',
        expires_at: '2999-01-01T00:00:00', requested_by: 'alice' },
      { id: 'g2', agent_id: 'a1', tool_name: 'unlisted-tool', effect: 'deny', status: 'active',
        expires_at: '2999-01-01T00:00:00', requested_by: 'alice' },
    ];
    audit = [{ id: 'e1', action: 'governance.grant.created', actor: 'alice', at: '2026-09-01T10:00:00',
      details: { tool_name: 'http-request' } }];
    mount();
    await tab('Grants');
    expect(await screen.findByText(/Make an HTTP Request \(http-request\)/)).toBeInTheDocument();
    expect(screen.getByText(/deny unlisted-tool/)).toBeInTheDocument();
    await tab('Audit');
    expect(await screen.findByText(/grant\.created/)).toHaveTextContent('Make an HTTP Request (http-request)');
  });

  it('simulates with the technical capability id and explains the decision in plain words', async () => {
    post.mockResolvedValue({
      current: { state: 'denied', decision: 'deny', code: 'DEFAULT_DENY', explanation: 'engine: no rule',
        plain_explanation: 'No policy grants this capability, so the safe default is Deny.',
        source: null, approval: null, backend_support: 'enforced', steps: [], blockers: [], validity: null },
      proposed: null, findings: [], notes: [],
    });
    mount();
    await tab('Simulator');
    const option = await screen.findByRole('option', { name: /Search the Web \(tool\.web-search\)/ });
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: (option as HTMLOptionElement).value } });
    expect(screen.getByLabelText('Selected capability')).toHaveTextContent('tool.web-search');
    fireEvent.click(screen.getByRole('button', { name: 'Simulate' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(`${G}/simulate`,
      expect.objectContaining({ capability_id: 'tool.web-search' })));
    const now = await screen.findByRole('region', { name: 'Decision now' });
    expect(within(now).getByText('No policy grants this capability, so the safe default is Deny.')).toBeInTheDocument();
    expect(within(now).getByText('DEFAULT_DENY')).toBeInTheDocument();
    expect(within(now).getByText('engine: no rule')).toBeInTheDocument();
  });

  it('marks an unsupported capability in the simulator without hiding its id', async () => {
    mount();
    await tab('Simulator');
    await screen.findByRole('option', { name: /Control a Web Browser/ });
    fireEvent.change(screen.getByLabelText('Capability'), { target: { value: 'computer.browser' } });
    const picked = screen.getByLabelText('Selected capability');
    expect(picked).toHaveTextContent('computer.browser');
    expect(picked).toHaveTextContent('NEXUS cannot currently enforce this capability');
  });

  it('saves a policy draft with technical tool names chosen from named capabilities', async () => {
    mount();
    await tab('Policy');
    fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
    fireEvent.click(await screen.findByRole('checkbox', { name: /Search the Web/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(`${G}/drafts/d1`, expect.objectContaining({
      rules: [expect.objectContaining({ conditions: { tool_name: ['http-request', 'web-search'] } })],
    })));
  });

  it('names affected and risky capabilities, falling back for one the catalogue lacks', async () => {
    findings = [{ code: 'HIGH_RISK_NO_APPROVAL', severity: 'high', detail: 'No approval.',
      capabilities: ['tool.http-request', 'tool.brand-new'] }];
    mount();
    await tab('Policy');
    fireEvent.click(await screen.findByRole('button', { name: /Open draft: Freeze outbound HTTP/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Review and publish/ }));
    fireEvent.click(await screen.findByText(/Show the 2 capabilities/));
    const list = screen.getAllByRole('listitem').filter((li) => li.textContent?.includes('tool.brand-new'))[0]!;
    expect(list).toHaveTextContent('Brand New');
    expect(list).toHaveTextContent('tool.brand-new');
    expect(await screen.findByText(/Capabilities involved: Make an HTTP Request \(tool\.http-request\), Brand New \(tool\.brand-new\)/))
      .toBeInTheDocument();
  });
});
