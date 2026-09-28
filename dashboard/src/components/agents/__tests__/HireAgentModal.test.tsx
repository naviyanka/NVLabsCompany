import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import type { AgentProvider } from '@/api/agents';
import { HireAgentModal } from '../HireAgentModal';

const base: Omit<AgentProvider, 'id' | 'label'> = {
  adapter_type: 'cli',
  installed: false,
  resolved_command: null,
  version: null,
  execution_supported: true,
  configured: false,
  stability: 'stable',
  supports_model: true,
  supports_resume: false,
  supports_interactive: false,
  supports_worktree: false,
  recommended_model: null,
  models: [],
  install_command: 'npm i -g x',
  docs_url: 'https://example.test/docs',
  notes: null,
};

// API order deliberately puts a missing backend first.
const PROVIDERS: AgentProvider[] = [
  { ...base, id: 'claude', label: 'Claude Code' },
  { ...base, id: 'kimi', label: 'Kimi Code', execution_supported: false },
  {
    ...base,
    id: 'codex',
    label: 'OpenAI Codex CLI',
    installed: true,
    configured: null,
    version: 'codex-cli 0.9.1',
    resolved_command: '~/bin/codex',
    models: ['gpt-5-codex'],
  },
];

function serve(providers: AgentProvider[] | null) {
  const created: unknown[] = [];
  server.use(
    http.get('*/api/v1/agent-providers', () =>
      providers ? HttpResponse.json(providers) : HttpResponse.json({ detail: 'down' }, { status: 503 }),
    ),
    http.get('*/api/v1/agent-archetypes', () => HttpResponse.json([])),
    http.get('*/api/v1/soul-templates', () => HttpResponse.json([])),
    http.post('*/api/v1/companies/:companyId/agents', async ({ request }) => {
      created.push(await request.json());
      return HttpResponse.json({ id: 'a1' }, { status: 201 });
    }),
  );
  return created;
}

async function openManual() {
  const onSuccess = vi.fn();
  render(<HireAgentModal isOpen onClose={() => {}} onSuccess={onSuccess} />);
  fireEvent.click(await screen.findByText('Manual Hire'));
  return onSuccess;
}

const backendButton = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement;

describe('HireAgentModal CLI backend selection', () => {
  it('loads providers from the API with installed backends first', async () => {
    serve(PROVIDERS);
    await openManual();
    const ready = await screen.findByRole('group', { name: 'Installed and ready' });
    expect(within(ready).getByText('OpenAI Codex CLI')).toBeTruthy();
    // Missing backends stay hidden until requested, then follow the ready group.
    expect(screen.queryByText('Claude Code')).toBeNull();
    fireEvent.click(screen.getByLabelText(/Show unavailable/));
    const groups = screen.getAllByRole('group').map((g) => g.getAttribute('aria-label')).filter(Boolean);
    expect(groups).toEqual(['Installed and ready', 'Available to install', 'Experimental / catalog only']);
    expect(screen.queryByText(/metadata unavailable/i)).toBeNull();
  });

  it('never lets a catalog-only backend be selected, and missing ones only with the override', async () => {
    serve(PROVIDERS);
    await openManual();
    await screen.findByRole('group', { name: 'Installed and ready' });
    fireEvent.click(screen.getByLabelText(/Show unavailable/));
    expect(backendButton('Kimi Code').disabled).toBe(true);
    expect(backendButton('Claude Code').disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Allow unavailable backend/));
    expect(backendButton('Claude Code').disabled).toBe(false);
    expect(backendButton('Kimi Code').disabled).toBe(true);
  });

  it('submits the canonical CLI payload with a custom model', async () => {
    const created = serve(PROVIDERS);
    const onSuccess = await openManual();
    await screen.findByRole('group', { name: 'Installed and ready' });
    fireEvent.change(screen.getByPlaceholderText('e.g. Helix-10'), { target: { value: 'CLI Smoke Employee' } });
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'my-custom-model' } });
    fireEvent.click(screen.getByText('Deploy Agent'));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(created).toEqual([
      expect.objectContaining({
        name: 'CLI Smoke Employee',
        adapter_type: 'cli',
        adapter_config: {
          backend: 'codex',
          interactive: false,
          use_worktree: false,
          autonomy_mode: 'safe',
          extra_args: [],
        },
        allow_unavailable_backend: false,
        model: 'my-custom-model',
      }),
    ]);
  });

  it('shows the API validation error code', async () => {
    serve(PROVIDERS);
    server.use(
      http.post('*/api/v1/companies/:companyId/agents', () =>
        HttpResponse.json(
          { detail: { code: 'CLI_BACKEND_UNAVAILABLE', message: 'OpenAI Codex CLI is not installed' } },
          { status: 422 },
        ),
      ),
    );
    await openManual();
    await screen.findByRole('group', { name: 'Installed and ready' });
    fireEvent.change(screen.getByPlaceholderText('e.g. Helix-10'), { target: { value: 'X' } });
    fireEvent.click(screen.getByText('Deploy Agent'));
    expect(await screen.findByText(/CLI_BACKEND_UNAVAILABLE: OpenAI Codex CLI is not installed/)).toBeTruthy();
  });

  it('Test CLI shows probe success and failure', async () => {
    serve(PROVIDERS);
    let ok = true;
    server.use(
      http.post('*/api/v1/agent-providers/:id/probe', ({ params }) =>
        HttpResponse.json({
          id: params.id,
          installed: ok,
          resolved_command: ok ? '~/bin/codex' : null,
          version: ok ? 'codex-cli 0.9.1' : null,
          execution_supported: true,
          configured: null,
          ok,
          error: ok ? null : 'Executable not found on PATH.',
        }),
      ),
    );
    await openManual();
    await screen.findByRole('group', { name: 'Installed and ready' });
    fireEvent.click(screen.getByText('Test CLI'));
    expect(await screen.findByText(/OK — codex-cli 0.9.1/)).toBeTruthy();
    ok = false;
    fireEvent.click(screen.getByText('Test CLI'));
    expect(await screen.findByText(/Failed — Executable not found on PATH./)).toBeTruthy();
  });

  it('labels the offline fallback when the provider API is down', async () => {
    serve(null);
    await openManual();
    expect(await screen.findByText(/Provider metadata unavailable/)).toBeTruthy();
  });
});
