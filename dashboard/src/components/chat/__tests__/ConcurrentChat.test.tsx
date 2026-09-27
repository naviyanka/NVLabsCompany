/**
 * Concurrent employee chats. Every server reply is a deferred stream the test
 * resolves by hand, so ordering is decided here, never by timers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ChatDock } from '../ChatDock';
import {
  ChatManagerProvider,
  chatReducer,
  conversationKey,
  initialChatState,
  useChatManager,
  type ChatAgent,
} from '@/contexts/ChatManagerContext';
import { getActiveCompanyId } from '@/config';

function agent(id: string, name: string, backend: string): ChatAgent {
  return {
    id,
    name,
    title: `${name} title`,
    role: 'engineer',
    adapter_type: 'cli',
    cli_backend: backend,
    model: '',
    status: 'idle',
    capabilities: [],
    budget_monthly_cents: 0,
    spent_monthly_cents: 0,
  };
}
const CLAUDE = agent('claude-id', 'Claude Emp', 'claude');
const AGY = agent('agy-id', 'Agy Emp', 'agy');

/** One in-flight stream request the test can answer, fail or observe being aborted. */
interface Call {
  agentId: string;
  prompt: string;
  signal: AbortSignal;
  push: (event: object) => void;
  reply: (text: string, backend: string) => void;
}

let calls: Call[];
let history: Record<string, Array<Record<string, string>>>;
const encoder = new TextEncoder();

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const agentId = /agents\/([^/]+)\/chat/.exec(url)?.[1] ?? '';
  if (!init?.method || init.method === 'GET') {
    return Promise.resolve(Response.json(history[agentId] ?? []));
  }
  const signal = init.signal as AbortSignal;
  const { prompt } = JSON.parse(String(init.body)) as { prompt: string };
  if (prompt === 'overloaded') {
    return Promise.resolve(Response.json({ detail: { code: 'CHAT_CONCURRENCY_LIMIT', message: 'Too many chats running' } }, { status: 429 }));
  }
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => void (controller = c) });
  signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')));
  const push = (event: object) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
  calls.push({
    agentId,
    prompt,
    signal,
    push,
    reply: (text, backend) => {
      push({
        type: 'done',
        message: { id: `srv-${calls.length}-${text}`, sender: 'agent', text, timestamp: '2026-09-27T10:00:00Z' },
        adapter_used: 'cli',
        backend_used: backend,
        execution_id: `exec-${agentId}`,
      });
      controller.close();
    },
  });
  return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
}

/** Stand-in for the agent list: always clickable, opens a chat per agent. */
function AgentButtons() {
  const chat = useChatManager();
  return (
    <div>
      <button onClick={() => chat.open(CLAUDE)}>Chat with Claude</button>
      <button onClick={() => chat.open(AGY)}>Chat with Agy</button>
    </div>
  );
}

function renderApp() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ChatManagerProvider>
        <AgentButtons />
        <ChatDock />
      </ChatManagerProvider>
    </QueryClientProvider>,
  );
}

const transcript = (name: string) => screen.getByRole('list', { name: `Transcript with ${name}` });
const tab = (name: string) => screen.getByRole('tab', { name: new RegExp(name) });

async function openAndSend(button: string, name: string, prompt: string) {
  fireEvent.click(screen.getByText(button));
  const box = await screen.findByLabelText(`Message ${name}`);
  fireEvent.change(box, { target: { value: prompt } });
  fireEvent.click(within(screen.getByRole('region', { name: 'Employee chats' })).getByText('Send'));
}

async function until(n: number) {
  await waitFor(() => expect(calls).toHaveLength(n));
}

beforeEach(() => {
  calls = [];
  history = {};
  try {
    localStorage.clear();
  } catch {
    /* no storage */
  }
  vi.stubGlobal('fetch', vi.fn(fakeFetch));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('concurrent employee chats', () => {
  it('routes each reply to its own chat whatever is selected (scenarios 1-10)', async () => {
    renderApp();
    // 1. slow Claude request
    await openAndSend('Chat with Claude', 'Claude Emp', 'wait then 5050');
    await until(1);
    // 2-3. switch to Agy before Claude completes, and send
    await openAndSend('Chat with Agy', 'Agy Emp', 'return 55');
    await until(2);
    const [claude, agy] = calls as [Call, Call];
    expect([claude.agentId, agy.agentId]).toEqual(['claude-id', 'agy-id']);

    // 4-5. Agy resolves first and lands only in Agy's chat
    await act(async () => agy.reply('{"employee":"agy","result":55}', 'agy'));
    expect(await within(transcript('Agy Emp')).findByText('{"employee":"agy","result":55}')).toBeTruthy();
    expect(within(transcript('Agy Emp')).getByText('via cli · agy')).toBeTruthy();
    expect(within(tab('Claude Emp')).getByLabelText('Pending')).toBeTruthy();

    // 6-8. Claude resolves later, while Agy is on screen: unread badge, not Agy's transcript
    await act(async () => claude.reply('{"employee":"claude","result":5050}', 'claude'));
    expect(await within(tab('Claude Emp')).findByLabelText('1 unread')).toBeTruthy();
    expect(within(transcript('Agy Emp')).queryByText(/5050/)).toBeNull();

    // 9. switching back shows Claude's reply and clears the badge
    fireEvent.click(tab('Claude Emp'));
    expect(within(transcript('Claude Emp')).getByText('{"employee":"claude","result":5050}')).toBeTruthy();
    expect(within(tab('Claude Emp')).queryByLabelText(/unread/)).toBeNull();

    // 10. neither transcript overwritten
    expect(within(transcript('Claude Emp')).getByText('wait then 5050')).toBeTruthy();
    fireEvent.click(tab('Agy Emp'));
    expect(within(transcript('Agy Emp')).getByText('return 55')).toBeTruthy();
    expect(within(transcript('Agy Emp')).getByText('{"employee":"agy","result":55}')).toBeTruthy();
  });

  it('a failure in one chat leaves the other untouched (scenario 11)', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'slow');
    await openAndSend('Chat with Agy', 'Agy Emp', 'breaks');
    await until(2);
    const [claude, agy] = calls as [Call, Call];
    await act(async () => agy.push({ type: 'error', text: 'CLI exited with code 1' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('CLI exited with code 1');
    fireEvent.click(tab('Claude Emp'));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(within(transcript('Claude Emp')).getByLabelText('Pending request')).toBeTruthy();
    expect(claude.signal.aborted).toBe(false);

    await act(async () => claude.reply('fine', 'claude'));
    expect(await within(transcript('Claude Emp')).findByText('fine')).toBeTruthy();
  });

  it('cancel stops only that request (scenario 12)', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'slow');
    await openAndSend('Chat with Agy', 'Agy Emp', 'also slow');
    await until(2);
    const [claude, agy] = calls as [Call, Call];

    fireEvent.click(tab('Claude Emp'));
    fireEvent.click(within(transcript('Claude Emp')).getByText('Cancel'));
    expect(await within(transcript('Claude Emp')).findByText('Request cancelled.')).toBeTruthy();
    expect(claude.signal.aborted).toBe(true);
    expect(agy.signal.aborted).toBe(false);

    await act(async () => agy.reply('agy done', 'agy'));
    fireEvent.click(tab('Agy Emp'));
    expect(await within(transcript('Agy Emp')).findByText('agy done')).toBeTruthy();
  });

  it('the agent list stays clickable while a chat is pending (scenario 13)', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'slow');
    await until(1);
    const other = screen.getByText('Chat with Agy');
    expect(other).not.toBeDisabled();
    fireEvent.click(other);
    expect(tab('Agy Emp')).toHaveAttribute('aria-selected', 'true');
    // No page-blocking overlay: the dock is a plain region, not a dialog.
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('hiding the chat keeps the in-flight request and its reply (scenario 14)', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'slow');
    await until(1);
    const [claude] = calls as [Call];

    fireEvent.click(screen.getByLabelText('Hide chats'));
    expect(screen.queryByRole('region', { name: 'Employee chats' })).toBeNull();
    expect(claude.signal.aborted).toBe(false);

    await act(async () => claude.reply('arrived while hidden', 'claude'));
    expect(await screen.findByLabelText('1 unread')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Open chats'));
    expect(within(transcript('Claude Emp')).getByText('arrived while hidden')).toBeTruthy();
  });

  it('duplicate send is blocked only in the busy conversation (scenario 15)', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'first');
    await until(1);

    const box = screen.getByLabelText('Message Claude Emp');
    fireEvent.change(box, { target: { value: 'second' } });
    const dock = screen.getByRole('region', { name: 'Employee chats' });
    expect(within(dock).getByText('Send').closest('button')).toBeDisabled();
    fireEvent.submit(box.closest('form')!);
    expect(calls).toHaveLength(1);

    await openAndSend('Chat with Agy', 'Agy Emp', 'agy goes ahead');
    await until(2);
    expect(calls[1]!.agentId).toBe('agy-id');
  });

  it('shows a per-chat error for a rejected request and retries it', async () => {
    renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'overloaded');
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many chats running');
    history = {};
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2));
  });

  it('open tabs and transcripts survive a remount (page refresh)', async () => {
    const view = renderApp();
    await openAndSend('Chat with Claude', 'Claude Emp', 'remember me');
    await until(1);
    await act(async () => calls[0]!.reply('remembered', 'claude'));
    await within(transcript('Claude Emp')).findByText('remembered');
    view.unmount();

    history['claude-id'] = [
      { id: 'h1', sender: 'user', text: 'remember me', timestamp: '2026-09-27T10:00:00Z' },
      { id: 'h2', sender: 'agent', text: 'remembered', timestamp: '2026-09-27T10:00:01Z' },
    ];
    renderApp();
    fireEvent.click(await screen.findByLabelText('Open chats'));
    expect(await within(transcript('Claude Emp')).findByText('remembered')).toBeTruthy();
  });
});

describe('chatReducer', () => {
  const company = getActiveCompanyId();
  const claudeKey = conversationKey(company, CLAUDE.id, null);
  const agyKey = conversationKey(company, AGY.id, null);
  const opened = [CLAUDE, AGY].reduce(
    (s, a) => chatReducer(s, { type: 'OPEN_CONVERSATION', companyId: company, agent: a, sessionId: null, focus: true }),
    initialChatState,
  );

  it('routes a completion by its captured key, not by the selected chat', () => {
    expect(opened.activeKey).toBe(agyKey);
    let s = chatReducer(opened, { type: 'REQUEST_STARTED', key: claudeKey, requestId: 'r1', prompt: 'hi', at: 't0' });
    s = chatReducer(s, {
      type: 'REQUEST_COMPLETED',
      key: claudeKey,
      requestId: 'r1',
      at: 't1',
      reply: { message: { id: 'm1', sender: 'agent', text: 'hello', timestamp: 't1' }, adapter_used: 'cli', backend_used: 'claude' },
    });
    expect(s.conversations[claudeKey]!.messages.map((m) => m.text)).toEqual(['hi', 'hello']);
    expect(s.conversations[claudeKey]!.unreadCount).toBe(1);
    expect(s.conversations[claudeKey]!.backendUsed).toBe('claude');
    expect(s.conversations[agyKey]!.messages).toEqual([]);
  });

  it('close view keeps transcripts and pending requests', () => {
    const s = chatReducer(
      chatReducer(opened, { type: 'REQUEST_STARTED', key: agyKey, requestId: 'r2', prompt: 'x', at: 't0' }),
      { type: 'CLOSE_VIEW' },
    );
    expect(s.viewOpen).toBe(false);
    expect(s.conversations[agyKey]!.pendingRequests).toHaveLength(1);
    expect(s.conversations[agyKey]!.messages).toHaveLength(1);
  });

  it('keys conversations by company, agent and session', () => {
    expect(conversationKey('c', 'a', null)).not.toBe(conversationKey('c', 'a', 's1'));
    expect(conversationKey('c1', 'a', 's')).not.toBe(conversationKey('c2', 'a', 's'));
  });
});
