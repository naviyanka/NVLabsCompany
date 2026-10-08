import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';

import { server } from '@/test/setup';
import { ToolEffectRecovery, validateDecision } from '../ToolEffectRecovery';

const authState = vi.hoisted(() => ({ isAdmin: true }));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => authState,
}));

const EFFECT_A = {
  id: '11111111-1111-4111-8111-111111111111',
  turn_id: '22222222-2222-4222-8222-222222222222',
  round_index: 0,
  invocation_index: 2,
  tool_name: 'send_slack_message',
  effect_class: 'non_idempotent_write',
  status: 'ambiguous',
  attempt_count: 2,
  arguments_digest: 'a'.repeat(64),
  created_at: '2026-10-05T12:00:00Z',
};

const EFFECT_B = {
  ...EFFECT_A,
  id: '33333333-3333-4333-8333-333333333333',
  turn_id: '44444444-4444-4444-8444-444444444444',
  tool_name: 'create_ticket',
  status: 'manual_recovery_required',
  attempt_count: 1,
};

const REVIEW_A = `Review and resolve ${EFFECT_A.tool_name} effect ${EFFECT_A.id}`;

let getUrls: string[];
let postCount: number;
let capturedResolveHeaders: Headers | null;
let capturedResolveBody: unknown;

function listPage(items: unknown[], nextCursor: string | null): Response {
  return HttpResponse.json({ items, next_cursor: nextCursor });
}

function renderPage(): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToolEffectRecovery />
    </QueryClientProvider>
  );
}

function stubConsole(): { calls: () => string; restore: () => void } {
  const spies = (['log', 'warn', 'error', 'info', 'debug'] as const).map((level) =>
    vi.spyOn(console, level).mockImplementation(() => {})
  );
  return {
    calls: () => JSON.stringify(spies.flatMap((spy) => spy.mock.calls)),
    restore: () => spies.forEach((spy) => spy.mockRestore()),
  };
}

/** Render with data and open the resolve dialog for EFFECT_A, filling only the reason. */
async function openDialogWithReason(): Promise<void> {
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
  await screen.findByRole('dialog');
  fireEvent.change(screen.getByLabelText(/Reason \(required/), {
    target: { value: 'checked the provider; no message was sent' },
  });
}

/** Open the resolve dialog with a reason and the not_applied outcome selected. */
async function openResolveDialog(): Promise<void> {
  await openDialogWithReason();
  fireEvent.click(screen.getByRole('radio', { name: /Not applied/ }));
}

describe('Tool Effect Recovery page', () => {
  beforeEach(() => {
    authState.isAdmin = true;
    getUrls = [];
    postCount = 0;
    capturedResolveHeaders = null;
    capturedResolveBody = null;
    document.cookie = 'nv_csrf=test-csrf-token';
    server.use(
      http.get('*/api/v1/tool-effects/open', ({ request }) => {
        getUrls.push(request.url);
        const cursor = new URL(request.url).searchParams.get('cursor');
        if (cursor === 'cursor-page-2') return listPage([EFFECT_B], null);
        return listPage([EFFECT_A], 'cursor-page-2');
      }),
      http.post('*/api/v1/tool-effects/:effectId/resolve', async ({ request }) => {
        postCount++;
        capturedResolveHeaders = request.headers;
        const body = (await request.json()) as { outcome?: string; reason?: string; note?: string | null };
        capturedResolveBody = body;
        const effectId = new URL(request.url).pathname.split('/')[4] ?? EFFECT_A.id;
        return HttpResponse.json({
          id: effectId,
          status: body.outcome === 'applied' ? 'succeeded' : 'failed',
          outcome: body.outcome,
        });
      })
    );
  });

  afterEach(() => {
    document.cookie = 'nv_csrf=; max-age=0';
    cleanup();
  });

  it('renders the recovery queue for an authorized administrator', async () => {
    renderPage();
    expect(
      await screen.findByRole('heading', { name: 'Tool Effect Recovery' })
    ).toBeInTheDocument();
    expect(await screen.findByText('send_slack_message')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: REVIEW_A })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeInTheDocument();
  });

  it('loads nothing and denies the page to a non-administrator', async () => {
    authState.isAdmin = false;
    renderPage();
    expect(await screen.findByText('Administrator access required')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(getUrls).toEqual([]);
  });

  it('announces the loading state with aria-busy', async () => {
    server.use(
      http.get('*/api/v1/tool-effects/open', async () => {
        await new Promise((resolve) => setTimeout(resolve, 80));
        getUrls.push('delayed');
        return listPage([EFFECT_A], null);
      })
    );
    const { container } = renderPage();
    expect(screen.getByText(/Loading unresolved effects/)).toBeInTheDocument();
    expect(container.querySelector('section')?.getAttribute('aria-busy')).toBe('true');
    expect(await screen.findByText('send_slack_message')).toBeInTheDocument();
    expect(container.querySelector('section')?.getAttribute('aria-busy')).toBe('false');
  });

  it('shows the empty state when nothing awaits a decision', async () => {
    server.use(http.get('*/api/v1/tool-effects/open', () => listPage([], null)));
    renderPage();
    expect(await screen.findByText('No unresolved effects')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
  });

  it('shows a sanitized load error without server internals', async () => {
    server.use(
      http.get('*/api/v1/tool-effects/open', () =>
        HttpResponse.json({ detail: 'db exploded internally' }, { status: 500 })
      )
    );
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to load unresolved tool effects.'
    );
    expect(document.body.textContent).not.toContain('db exploded internally');
  });

  it('renders only the safe metadata the API model returns', async () => {
    server.use(
      http.get('*/api/v1/tool-effects/open', () =>
        HttpResponse.json({
          items: [
            {
              ...EFFECT_A,
              // A contract violation on the server's side: the UI must still not show these.
              arguments: { api_key: 'sk-live-LEAKED-KEY' },
              result: 'LEAKED-RESULT-PAYLOAD',
              error: 'LEAKED-ERROR-TRACE',
            },
          ],
          next_cursor: null,
        })
      )
    );
    renderPage();
    expect(await screen.findByText('send_slack_message')).toBeInTheDocument();
    expect(screen.getByText(/round 0 · call 2/)).toBeInTheDocument();
    expect(screen.getByText(`${'a'.repeat(10)}…`)).toBeInTheDocument();
    const body = document.body.textContent ?? '';
    for (const secret of ['sk-live-LEAKED-KEY', 'LEAKED-RESULT-PAYLOAD', 'LEAKED-ERROR-TRACE']) {
      expect(body).not.toContain(secret);
    }
  });

  it('pages with the server cursor and never fabricates a client-side page', async () => {
    renderPage();
    await screen.findByText('send_slack_message');
    // The server served one row; the second effect exists server-side but must
    // not appear until the server sends its page.
    expect(screen.queryByText('create_ticket')).not.toBeInTheDocument();
    expect(getUrls).toHaveLength(1);
    expect(getUrls[0]).toContain('limit=100');
    expect(getUrls[0]).not.toContain('cursor=');

    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByText('create_ticket')).toBeInTheDocument();
    expect(screen.queryByText('send_slack_message')).not.toBeInTheDocument();
    expect(getUrls).toHaveLength(2);
    expect(getUrls[1]).toContain('cursor=cursor-page-2');

    fireEvent.click(screen.getByRole('button', { name: 'Previous page' }));
    expect(await screen.findByText('send_slack_message')).toBeInTheDocument();
  });

  it('selects no outcome when the dialog opens', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    expect(screen.getByRole('radio', { name: /Applied/ })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: /Not applied/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeDisabled();
  });

  it('keeps confirmation disabled until an outcome is explicitly selected', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    const confirm = screen.getByRole('button', { name: 'Record decision' });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Reason \(required/), {
      target: { value: 'a reason alone is not enough' },
    });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: /Applied/ }));
    expect(confirm).toBeEnabled();
    expect(postCount).toBe(0);
  });

  it('rejects an incomplete decision at the shared guard, which the handler also uses', () => {
    const missingOutcome = validateDecision(null, 'a reason is present');
    expect(missingOutcome.ok).toBe(false);
    if (!missingOutcome.ok) expect(missingOutcome.message).toMatch(/Select an outcome/);

    const missingReason = validateDecision('applied', '   ');
    expect(missingReason.ok).toBe(false);
    if (!missingReason.ok) expect(missingReason.message).toMatch(/reason is required/);

    expect(validateDecision('not_applied', 'verified nothing happened')).toEqual({
      ok: true,
      outcome: 'not_applied',
    });
  });

  it('cannot be bypassed by DOM manipulation: nothing is sent without an explicit outcome', async () => {
    await openDialogWithReason();
    const confirm = screen.getByRole('button', {
      name: 'Record decision',
    }) as HTMLButtonElement;
    // React dispatches events against the rendered props, so removing the
    // disabled attribute in the DOM cannot reach the handler. Prove that no
    // request is sent and no error path is entered.
    confirm.disabled = false;
    fireEvent.click(confirm);
    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(postCount).toBe(0);
    expect(capturedResolveBody).toBeNull();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('sends exactly outcome "applied" when that is what the administrator selects', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('radio', { name: /Applied/ }));
    fireEvent.change(screen.getByLabelText(/Reason \(required/), {
      target: { value: 'confirmed delivered in the provider console' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/the effect was applied/);
    expect(capturedResolveBody).toEqual({
      outcome: 'applied',
      reason: 'confirmed delivered in the provider console',
      note: null,
    });
    expect(postCount).toBe(1);
  });

  it('sends exactly outcome "not_applied" when that is what the administrator selects', async () => {
    await openResolveDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/the effect was not applied/);
    expect(capturedResolveBody).toEqual({
      outcome: 'not_applied',
      reason: 'checked the provider; no message was sent',
      note: null,
    });
    expect(postCount).toBe(1);
  });

  it('resets the outcome and fields when the dialog is closed and reopened', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('radio', { name: /Not applied/ }));
    fireEvent.change(screen.getByLabelText(/Reason \(required/), {
      target: { value: 'a decision that must not leak into the next dialog' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    expect(screen.getByRole('radio', { name: /Applied/ })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: /Not applied/ })).not.toBeChecked();
    expect(screen.getByLabelText(/Reason \(required/)).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeDisabled();
    expect(postCount).toBe(0);
  });

  it('records a server-confirmed resolution and refreshes the row away', async () => {
    const resolved = { done: false };
    server.use(
      http.get('*/api/v1/tool-effects/open', () => {
        getUrls.push('success-flow');
        return listPage(resolved.done ? [] : [EFFECT_A], null);
      }),
      http.post('*/api/v1/tool-effects/:effectId/resolve', () => {
        postCount++;
        resolved.done = true;
        return HttpResponse.json({ id: EFFECT_A.id, status: 'failed', outcome: 'not_applied' });
      })
    );
    await openResolveDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Decision recorded');
    expect(await screen.findByText('No unresolved effects')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(postCount).toBe(1);
  });

  it('prevents a duplicate submission while a decision is in flight', async () => {
    // The executor below runs synchronously, so this is assigned before use.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('*/api/v1/tool-effects/:effectId/resolve', async () => {
        postCount++;
        await gate;
        return HttpResponse.json({ id: EFFECT_A.id, status: 'failed', outcome: 'not_applied' });
      })
    );
    await openResolveDialog();
    const confirm = screen.getByRole('button', { name: 'Record decision' });
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    for (const button of screen.getAllByRole('button', { name: /Review and resolve/ })) {
      expect(button).toBeDisabled();
    }
    fireEvent.click(confirm); // a second attempt while the first is in flight
    release();
    await screen.findByRole('status');
    expect(postCount).toBe(1);
  });

  it('explains an expired session on 401', async () => {
    server.use(
      http.post('*/api/v1/tool-effects/:effectId/resolve', () =>
        HttpResponse.json({ detail: 'Authentication required' }, { status: 401 })
      )
    );
    await openResolveDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/session has expired/i);
    // Focus moves to the alert once React's effects flush; poll for it rather
    // than race the commit.
    await waitFor(() => expect(document.activeElement).toHaveAttribute('role', 'alert'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('explains missing permission on 403', async () => {
    server.use(
      http.post('*/api/v1/tool-effects/:effectId/resolve', () =>
        HttpResponse.json({ detail: 'Administrator role required' }, { status: 403 })
      )
    );
    await openResolveDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /do not have permission to record recovery decisions/i
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps foreign and missing effects indistinguishable on 404 and refreshes', async () => {
    server.use(
      http.post('*/api/v1/tool-effects/:effectId/resolve', () => {
        postCount++;
        return HttpResponse.json({ detail: 'Tool effect not found' }, { status: 404 });
      })
    );
    renderPage();
    await screen.findByText('send_slack_message');
    expect(getUrls).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    fireEvent.change(screen.getByLabelText(/Reason \(required/), { target: { value: 'r' } });
    fireEvent.click(screen.getByRole('radio', { name: /Not applied/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/no such effect awaiting a decision/);
    expect(alert).toHaveTextContent(/by design/);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(getUrls).toHaveLength(2));
    expect(postCount).toBe(1);
  });

  it('explains that another decision won on 409 and refreshes the row', async () => {
    server.use(
      http.post('*/api/v1/tool-effects/:effectId/resolve', () => {
        postCount++;
        return HttpResponse.json(
          { detail: 'tool effect is succeeded, not awaiting recovery' },
          { status: 409 }
        );
      })
    );
    renderPage();
    await screen.findByText('send_slack_message');
    expect(getUrls).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    fireEvent.change(screen.getByLabelText(/Reason \(required/), { target: { value: 'r' } });
    fireEvent.click(screen.getByRole('radio', { name: /Not applied/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Another decision was recorded first/);
    expect(alert).toHaveTextContent('tool effect is succeeded, not awaiting recovery');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(getUrls).toHaveLength(2));
    expect(postCount).toBe(1);
    await waitFor(() => expect(document.activeElement).toHaveAttribute('role', 'alert'));
  });

  it('shows a generic sanitized failure and leaks nothing on an unexpected error', async () => {
    const consoleStub = stubConsole();
    try {
      server.use(
        http.post('*/api/v1/tool-effects/:effectId/resolve', () =>
          HttpResponse.json(
            { detail: 'internal boom sk-live-SECRET-12345' },
            { status: 500 }
          )
        )
      );
      await openResolveDialog();
      fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('Recording the decision failed');
      expect(document.body.textContent).not.toContain('sk-live-SECRET-12345');
      expect(document.body.textContent).not.toContain('internal boom');
      expect(consoleStub.calls()).not.toMatch(/sk-live-SECRET-12345|internal boom/);
    } finally {
      consoleStub.restore();
    }
  });

  it('moves focus into the dialog and back to its trigger', async () => {
    renderPage();
    const trigger = await screen.findByRole('button', { name: REVIEW_A });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('keeps confirmation disabled until the required reason is provided', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: REVIEW_A }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('radio', { name: /Applied/ }));
    const confirm = screen.getByRole('button', { name: 'Record decision' });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Reason \(required/), {
      target: { value: 'provider shows no message' },
    });
    expect(confirm).toBeEnabled();
    expect(postCount).toBe(0);
  });

  it('never logs effect details, resolution payloads or tokens', async () => {
    const consoleStub = stubConsole();
    try {
      await openResolveDialog();
      fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
      await screen.findByRole('status');
      expect(consoleStub.calls()).not.toMatch(
        /send_slack_message|arguments_digest|aaaaaaaaaa|no message was sent|test-csrf-token/
      );
    } finally {
      consoleStub.restore();
    }
  });

  it('sends the mandatory headers on resolve and cannot override them', async () => {
    await openResolveDialog();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    await screen.findByRole('status');
    expect(capturedResolveHeaders?.get('X-CSRF-Token')).toBe('test-csrf-token');
    expect(capturedResolveHeaders?.get('Content-Type')).toBe('application/json');
    expect(capturedResolveHeaders?.get('X-Company-Id')).toBeNull();
  });
});
