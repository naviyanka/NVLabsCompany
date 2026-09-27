/**
 * ChatDock — non-modal employee chat panel with one tab per open conversation.
 *
 * It never blocks the page: there is no backdrop, and a pending request only
 * disables sending in its own conversation. Hiding the dock or a tab keeps the
 * transcript and lets running requests finish.
 */

import { useEffect, useRef, useState } from 'react';
import { Bot as BotIcon, Loader2, MessageSquare, Minus, RotateCcw, Send, User as UserIcon, X } from 'lucide-react';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import { useChatManager, type ChatManager, type Conversation } from '@/contexts/ChatManagerContext';

const SLASH_COMMANDS = [
  { cmd: '/help', desc: 'Show all available commands' },
  { cmd: '/status', desc: 'Show agent status, role & capabilities' },
  { cmd: '/clear', desc: 'Clear chat history' },
  { cmd: '/export', desc: 'Download chat transcript as Markdown' },
  { cmd: '/model', desc: 'Show current model & provider' },
  { cmd: '/budget', desc: 'Show remaining budget & spend' },
  { cmd: '/cancel', desc: 'Cancel the running request in this chat' },
  { cmd: '/hire', desc: 'Quick-hire a new agent' },
  { cmd: '/broadcast', desc: 'Send message to all agents' },
];

function uid(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function statusOf(c: Conversation): string {
  const pending = c.pendingRequests[0];
  if (pending) return pending.phase === 'sending' ? 'sending' : 'waiting for CLI';
  return c.lastOutcome ?? 'idle';
}

function backendBadge(c: Conversation): string {
  return c.backendUsed ?? c.agent.cli_backend ?? c.agent.adapter_type;
}

/** Local slash commands. Returns false when the text is not a command. */
function runCommand(text: string, conv: Conversation, manager: ChatManager): boolean {
  if (!text.startsWith('/')) return false;
  const { key, agent } = conv;
  const cmd = (text.split(' ')[0] ?? '').toLowerCase();
  const now = () => new Date().toISOString();
  const say = (reply: string) =>
    manager.dispatch({ type: 'APPEND_LOCAL', key, message: { id: `sys-${uid()}`, sender: 'agent', text: reply, timestamp: now() } });
  manager.dispatch({ type: 'APPEND_LOCAL', key, message: { id: `cmd-${uid()}`, sender: 'user', text, timestamp: now() } });
  manager.dispatch({ type: 'SET_DRAFT', key, draft: '' });
  const money = (cents: number) => `$${(cents / 100).toFixed(2)}`;

  switch (cmd) {
    case '/clear':
      manager.dispatch({ type: 'CLEAR', key, message: { id: `sys-${uid()}`, sender: 'agent', text: 'Chat history cleared. Ready for new conversation.', timestamp: now() } });
      apiClient.delete(`/api/v1/agents/${agent.id}/chat`).catch(() => {});
      break;
    case '/export': {
      const md = conv.messages
        .map((m) => `**${m.sender === 'user' ? 'You' : agent.name}** (${new Date(m.timestamp).toLocaleTimeString()}):\n${m.text}`)
        .join('\n\n---\n\n');
      const header = `# Chat with ${agent.name}\n\n**Role:** ${agent.title || agent.role}\n**Provider:** ${agent.adapter_type}\n**Model:** ${agent.model || 'default'}\n\n---\n\n`;
      const url = URL.createObjectURL(new Blob([header + md], { type: 'text/markdown' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `chat-${agent.name}-${Date.now()}.md`;
      a.click();
      URL.revokeObjectURL(url);
      say(`Chat exported as Markdown (${conv.messages.length} messages).`);
      break;
    }
    case '/status': {
      const caps = Array.isArray(agent.capabilities) ? agent.capabilities.join(', ') : String(agent.capabilities ?? '');
      say(
        `**Agent Status & Configuration**\n• Name: ${agent.name}\n• Title: ${agent.title || 'N/A'}\n• Role: ${agent.role}\n` +
          `• Provider: ${agent.adapter_type}${agent.cli_backend ? ` (${agent.cli_backend})` : ''}\n• Model: ${agent.model || 'provider default'}\n` +
          `• Status: ${agent.status}\n• Capabilities: ${caps || 'none'}\n• Monthly Budget: ${money(agent.budget_monthly_cents || 0)}/mo`,
      );
      break;
    }
    case '/model':
      say(`Current Model: **${agent.model || 'provider default'}**\nProvider Adapter: **${agent.adapter_type}**${agent.cli_backend ? `\nCLI Backend: **${agent.cli_backend}**` : ''}`);
      break;
    case '/help':
      say(`**Available Commands:**\n${SLASH_COMMANDS.map((c) => `• \`${c.cmd}\` — ${c.desc}`).join('\n')}\n\nType anything else to converse directly with ${agent.name}.`);
      break;
    case '/budget': {
      const budget = agent.budget_monthly_cents || 0;
      const spent = agent.spent_monthly_cents || 0;
      say(`**Budget & Spend**\n• Monthly Budget: ${money(budget)}\n• Monthly Spent: ${money(spent)}\n• Remaining: ${money(budget - spent)}`);
      break;
    }
    case '/cancel':
      if (conv.pendingRequests.length) conv.pendingRequests.forEach((r) => manager.cancel(r.requestId));
      else say(`No active request to cancel. ${agent.name} is idle.`);
      break;
    case '/hire':
      say('Opening the Hire Agent modal... Use the UI to configure and deploy a new agent.');
      window.dispatchEvent(new CustomEvent('nexus:open-hire-modal'));
      break;
    case '/broadcast': {
      const message = text.slice('/broadcast'.length).trim();
      if (!message) {
        say('Usage: `/broadcast <message>`\nSends a message to all active agents.');
        break;
      }
      apiClient
        .post('/api/v1/communication/broadcast', { message, sender_agent_id: agent.id })
        .then(() => say(`Broadcast sent to all active agents: "${message}"`))
        .catch(() => say('Failed to broadcast. Communication service may be unavailable.'));
      break;
    }
    default:
      say(`Unknown command: \`${cmd}\`. Type \`/help\` for available commands.`);
  }
  return true;
}

/** One conversation: transcript, pending rows with Cancel, error with Retry, composer. */
export function ConversationView({ conv, className = '' }: { conv: Conversation; className?: string }) {
  const manager = useChatManager();
  const { loadHistory } = manager;
  const bottomRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(() => Date.now());
  const pending = conv.pendingRequests;

  useEffect(() => loadHistory(conv.key), [loadHistory, conv.key]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [conv.messages.length, pending.length]);

  // Elapsed-time ticker, only while this chat is waiting.
  useEffect(() => {
    if (!pending.length) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [pending.length]);

  const draft = conv.draft;
  const suggestions = draft.startsWith('/') ? SLASH_COMMANDS.filter((c) => c.cmd.startsWith(draft.toLowerCase())) : [];
  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    if (!runCommand(text, conv, manager)) manager.send(conv.key, text);
  };

  return (
    <div className={`flex flex-col flex-1 min-h-0 ${className}`} data-testid={`conversation-${conv.agent.name}`}>
      <div className="px-3 py-1.5 border-b border-white/[0.06] text-[10px] font-mono text-[#6B6B6E] flex items-center gap-2">
        <span className="truncate">{conv.agent.title || conv.agent.role}</span>
        <span className="px-1.5 py-0.5 rounded bg-white/[0.06] text-[#A8A8AB]">{backendBadge(conv)}</span>
        <span className="ml-auto" aria-label="Chat status">{statusOf(conv)}</span>
      </div>
      <ol aria-label={`Transcript with ${conv.agent.name}`} className="flex-1 overflow-y-auto space-y-3 p-3">
        {conv.messages.length === 0 && !pending.length && (
          <li className="text-[11px] font-mono text-[#6B6B6E] text-center pt-8">
            Send a message to start a conversation with {conv.agent.name}. Type <span className="text-[#FFB020]">/help</span> for commands.
          </li>
        )}
        {conv.messages.map((msg) => (
          <li key={msg.id} className={`flex gap-2 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.sender === 'agent' && <BotIcon size={12} className="text-[#FFB020] mt-1 shrink-0" />}
            <div
              className={`max-w-[80%] px-3 py-2 rounded-[8px] text-xs leading-relaxed whitespace-pre-wrap break-words ${
                msg.sender === 'user' ? 'bg-[#FFB020]/10 border border-[#FFB020]/20 text-[#F2F1EE]' : 'bg-[#141416] border border-white/[0.08] text-[#A8A8AB]'
              }`}
            >
              {msg.text}
              {msg.via && <div className="mt-1 text-[9px] font-mono text-[#6B6B6E]" title="Execution that produced this reply">via {msg.via}</div>}
            </div>
            {msg.sender === 'user' && <UserIcon size={12} className="text-[#9C9C9F] mt-1 shrink-0" />}
          </li>
        ))}
        {pending.map((r) => (
          <li key={r.requestId} className="flex gap-2 items-start" aria-label="Pending request">
            <Loader2 size={12} className="text-[#FFB020] mt-1 shrink-0 animate-spin" />
            <div className="flex-1 px-3 py-2 rounded-[8px] text-xs bg-[#141416] border border-white/[0.08] text-[#A8A8AB] whitespace-pre-wrap">
              {r.partial || `${r.phase === 'sending' ? 'Sending' : 'Waiting for'} ${conv.agent.name}… ${Math.max(0, Math.round((now - Date.parse(r.startedAt)) / 1000))}s`}
            </div>
            <button type="button" onClick={() => manager.cancel(r.requestId)} className="text-[11px] font-mono text-red-400 hover:text-red-300 px-1.5 py-1">
              Cancel
            </button>
          </li>
        ))}
        {conv.error && (
          <li role="alert" className="flex items-center gap-2 text-[11px] text-red-400">
            <span className="flex-1">{conv.error.message}</span>
            <button type="button" onClick={() => manager.retry(conv.key)} className="flex items-center gap-1 text-[#FFB020] hover:text-white">
              <RotateCcw size={11} /> Retry
            </button>
          </li>
        )}
        <div ref={bottomRef} />
      </ol>
      {suggestions.length > 0 && (
        <div className="mx-3 mb-2 bg-[#141416] border border-[#FFB020]/30 rounded-[8px] p-1 space-y-0.5">
          {suggestions.map((c) => (
            <button
              key={c.cmd}
              type="button"
              onClick={() => manager.dispatch({ type: 'SET_DRAFT', key: conv.key, draft: c.cmd })}
              className="w-full text-left px-2 py-1 rounded-[6px] hover:bg-[#FFB020]/10 flex justify-between text-[11px] font-mono"
            >
              <span className="text-[#FFB020]">{c.cmd}</span>
              <span className="text-[#A8A8AB]">{c.desc}</span>
            </button>
          ))}
        </div>
      )}
      <form
        className="flex items-center gap-2 p-3 border-t border-white/[0.08]"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <input
          aria-label={`Message ${conv.agent.name}`}
          value={draft}
          onChange={(e) => manager.dispatch({ type: 'SET_DRAFT', key: conv.key, draft: e.target.value })}
          placeholder={`Message ${conv.agent.name} (type / for commands)...`}
          className="flex-1 px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
        />
        {/* One turn at a time per conversation (sequential per session); other chats stay free. */}
        <button
          type="submit"
          disabled={!draft.trim() || (pending.length > 0 && !draft.trim().startsWith('/'))}
          className="flex items-center gap-1 px-3 py-2 text-xs rounded-[6px] bg-[#FFB020] text-black disabled:opacity-40"
        >
          <Send size={12} /> Send
        </button>
      </form>
    </div>
  );
}

export function ChatDock() {
  const manager = useChatManager();
  const { state, dispatch } = manager;
  const companyId = getActiveCompanyId();
  const tabs = state.tabs.map((k) => state.conversations[k]!).filter((c) => c.companyId === companyId);
  const active = tabs.find((c) => c.key === state.activeKey) ?? null;
  const unread = tabs.reduce((n, c) => n + c.unreadCount, 0);
  const running = tabs.some((c) => c.pendingRequests.length > 0);

  if (!tabs.length) return null;

  if (!state.viewOpen || !active) {
    return (
      <button
        type="button"
        onClick={() => (active ? dispatch({ type: 'OPEN_VIEW' }) : dispatch({ type: 'SELECT_CONVERSATION', key: tabs[tabs.length - 1]!.key }))}
        className="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-full bg-[#141416] border border-white/[0.12] text-xs text-[#F2F1EE] shadow-xl hover:border-[#FFB020]"
        aria-label="Open chats"
      >
        {running ? <Loader2 size={14} className="animate-spin text-[#FFB020]" /> : <MessageSquare size={14} className="text-[#FFB020]" />}
        Chats
        {unread > 0 && (
          <span aria-label={`${unread} unread`} className="min-w-[18px] h-[18px] px-1 rounded-full bg-[#FFB020] text-black text-[10px] font-bold flex items-center justify-center">
            {unread}
          </span>
        )}
      </button>
    );
  }

  return (
    <section
      aria-label="Employee chats"
      className="fixed bottom-4 right-4 z-40 w-[440px] max-w-[calc(100vw-2rem)] h-[560px] max-h-[calc(100vh-2rem)] flex flex-col bg-[#0C0C0E] border border-white/[0.12] rounded-[10px] shadow-2xl"
    >
      <div role="tablist" className="flex items-center gap-1 px-2 pt-2 border-b border-white/[0.08] overflow-x-auto">
        {tabs.map((c) => (
          <div
            key={c.key}
            className={`flex items-center gap-1 pl-2.5 pr-1 py-1.5 rounded-t-[6px] text-[11px] whitespace-nowrap ${
              c.key === active.key ? 'bg-white/[0.06] text-[#F2F1EE]' : 'text-[#9C9C9F] hover:text-[#F2F1EE]'
            }`}
          >
            <button type="button" role="tab" aria-selected={c.key === active.key} onClick={() => dispatch({ type: 'SELECT_CONVERSATION', key: c.key })} className="flex items-center gap-1.5">
              {c.pendingRequests.length > 0 && <Loader2 size={11} aria-label="Pending" className="animate-spin text-[#FFB020]" />}
              {c.agent.name}
              {c.unreadCount > 0 && (
                <span aria-label={`${c.unreadCount} unread`} className="min-w-[16px] h-4 px-1 rounded-full bg-[#FFB020] text-black text-[9px] font-bold flex items-center justify-center">
                  {c.unreadCount}
                </span>
              )}
            </button>
            {c.pendingRequests.length === 0 && (
              <button type="button" aria-label={`Close ${c.agent.name} tab`} onClick={() => dispatch({ type: 'HIDE_TAB', key: c.key })} className="p-0.5 text-[#6B6B6E] hover:text-white">
                <X size={11} />
              </button>
            )}
          </div>
        ))}
        <button type="button" aria-label="Hide chats" onClick={() => dispatch({ type: 'CLOSE_VIEW' })} className="ml-auto p-1 text-[#6B6B6E] hover:text-white">
          <Minus size={14} />
        </button>
      </div>
      <ConversationView key={active.key} conv={active} />
    </section>
  );
}
