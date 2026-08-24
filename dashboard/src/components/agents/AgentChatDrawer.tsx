/**
 * AgentChatDrawer — Slide-out chat panel for conversing with an agent directly from the Agents page.
 */

import { useState, useEffect, useRef } from 'react';
import { Drawer } from '@/components/common/Drawer';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { Agent } from '@/types/agent';
import { Send, Bot, User } from 'lucide-react';

interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
}

interface AgentChatDrawerProps {
  agent: Agent | null;
  isOpen: boolean;
  onClose: () => void;
}

export function AgentChatDrawer({ agent, isOpen, onClose }: AgentChatDrawerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load chat history when agent changes
  useEffect(() => {
    if (!agent || !isOpen) return;
    setMessages([]);

    apiClient
      .get<ChatMessage[]>(`/api/v1/agents/${agent.id}/chat`)
      .then((history) => {
        if (Array.isArray(history) && history.length > 0) {
          setMessages(history);
        }
      })
      .catch(() => {
        // No history yet — start fresh
      });
  }, [agent?.id, isOpen]);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !agent || sending) return;

    const userText = input.trim();
    setInput('');

    // ── Slash Command Handler ──
    if (userText.startsWith('/')) {
      const parts = userText.split(' ');
      const cmd = (parts[0] || '').toLowerCase();
      const args = parts.slice(1).join(' ');

      switch (cmd) {
        case '/clear':
          setMessages([]);
          setMessages([{
            id: `sys-${Date.now()}`,
            sender: 'agent',
            text: `Chat history cleared. Ready for new conversation.`,
            timestamp: new Date().toISOString(),
          }]);
          // Also clear on server
          apiClient.delete(`/api/v1/agents/${agent.id}/chat`).catch(() => {});
          return;

        case '/export': {
          const md = messages
            .map((m) => `**${m.sender === 'user' ? 'You' : agent.name}** (${new Date(m.timestamp).toLocaleTimeString()}):\n${m.text}`)
            .join('\n\n---\n\n');
          const header = `# Chat with ${agent.name}\n\n**Role:** ${agent.title || agent.role}\n**Provider:** ${agent.adapter_type}\n**Model:** ${agent.model || 'default'}\n\n---\n\n`;
          const blob = new Blob([header + md], { type: 'text/markdown' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `chat-${agent.name}-${Date.now()}.md`;
          a.click();
          URL.revokeObjectURL(url);
          setMessages((prev) => [...prev, {
            id: `sys-${Date.now()}`,
            sender: 'agent',
            text: `Chat exported as Markdown (${messages.length} messages).`,
            timestamp: new Date().toISOString(),
          }]);
          return;
        }

        case '/status':
          setMessages((prev) => [...prev, {
            id: `sys-${Date.now()}`,
            sender: 'agent',
            text: `**Agent Status**\n` +
              `• Name: ${agent.name}\n` +
              `• Title: ${agent.title || 'N/A'}\n` +
              `• Role: ${agent.role}\n` +
              `• Provider: ${agent.adapter_type}\n` +
              `• Model: ${agent.model || 'provider default'}\n` +
              `• Status: ${agent.status}\n` +
              `• Capabilities: ${(agent.capabilities || []).join(', ') || 'none'}\n` +
              `• Budget: $${((agent.budget_monthly_cents || 0) / 100).toFixed(2)}/mo\n` +
              `• Messages in session: ${messages.length}`,
            timestamp: new Date().toISOString(),
          }]);
          return;

        case '/model':
          if (args) {
            setMessages((prev) => [...prev, {
              id: `sys-${Date.now()}`,
              sender: 'agent',
              text: `Model switching is not yet implemented from chat. Use the Agent settings to change the model.\nCurrent model: ${agent.model || 'provider default'}`,
              timestamp: new Date().toISOString(),
            }]);
          } else {
            setMessages((prev) => [...prev, {
              id: `sys-${Date.now()}`,
              sender: 'agent',
              text: `Current model: ${agent.model || 'provider default'}\nProvider: ${agent.adapter_type}`,
              timestamp: new Date().toISOString(),
            }]);
          }
          return;

        case '/help':
          setMessages((prev) => [...prev, {
            id: `sys-${Date.now()}`,
            sender: 'agent',
            text: `**Available Commands:**\n` +
              `• \`/clear\` — Clear chat history\n` +
              `• \`/export\` — Download conversation as Markdown\n` +
              `• \`/status\` — Show agent info (role, model, capabilities)\n` +
              `• \`/model\` — Show current model\n` +
              `• \`/help\` — Show this help message\n\n` +
              `Type anything else to chat with ${agent.name}.`,
            timestamp: new Date().toISOString(),
          }]);
          return;

        default:
          setMessages((prev) => [...prev, {
            id: `sys-${Date.now()}`,
            sender: 'agent',
            text: `Unknown command: \`${cmd}\`. Type \`/help\` for available commands.`,
            timestamp: new Date().toISOString(),
          }]);
          return;
      }
    }

    // ── Normal message — send to agent with streaming ──
    setSending(true);

    const userMsg: ChatMessage = {
      id: `usr-${Date.now()}`,
      sender: 'user',
      text: userText,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // Create a placeholder message for streaming
    const streamMsgId = `stream-${Date.now()}`;
    setMessages((prev) => [...prev, { id: streamMsgId, sender: 'agent', text: '▍', timestamp: new Date().toISOString() }]);

    try {
      const response = await fetch(`/api/v1/agents/${agent.id}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ prompt: userText }),
      });

      if (!response.ok || !response.body) {
        // Fallback to non-streaming
        const res = await apiClient.post<{ message: ChatMessage; history: ChatMessage[] }>(
          `/api/v1/agents/${agent.id}/chat`,
          { prompt: userText }
        );
        setMessages((prev) => prev.filter((m) => m.id !== streamMsgId));
        if (res?.history) {
          setMessages(res.history);
        } else if (res?.message) {
          setMessages((prev) => [...prev, res.message]);
        }
      } else {
        // Stream SSE response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const text = decoder.decode(value, { stream: true });
          const lines = text.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') continue;

            try {
              const event = JSON.parse(data);
              if (event.type === 'chunk') {
                accumulated += event.text;
                setMessages((prev) =>
                  prev.map((m) => m.id === streamMsgId ? { ...m, text: accumulated + '▍' } : m)
                );
              } else if (event.type === 'done') {
                // Replace streaming placeholder with final message
                setMessages((prev) =>
                  prev.map((m) => m.id === streamMsgId ? event.message : m)
                );
              } else if (event.type === 'error') {
                setMessages((prev) =>
                  prev.map((m) => m.id === streamMsgId ? { ...m, text: `Error: ${event.text}` } : m)
                );
              }
            } catch {
              // Not valid JSON — skip
            }
          }
        }

        // If stream ended without a 'done' event, finalize
        if (accumulated && !accumulated.includes('[DONE]')) {
          setMessages((prev) =>
            prev.map((m) => m.id === streamMsgId ? { ...m, text: accumulated } : m)
          );
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) => m.id === streamMsgId
          ? { ...m, text: 'Failed to process command. The agent may be unavailable.' }
          : m)
      );
    } finally {
      setSending(false);
    }
  };

  if (!agent) return null;

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={`Chat with ${agent.name}`}
      subtitle={`${agent.title} · ${agent.model || 'default model'}`}
    >
      <div className="flex flex-col h-[500px]">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1 mb-3">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center px-4">
              <div className="w-10 h-10 rounded-full bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center mb-3">
                <Bot size={18} className="text-[#FFB020]" />
              </div>
              <p className="text-xs font-mono text-[#6B6B6E]">
                Send a message to start a conversation with {agent.name}.
              </p>
              <p className="text-[10px] text-[#6B6B6E] mt-1">
                Role: {agent.role} · Provider: {agent.adapter_type}
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-2.5 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {msg.sender === 'agent' && (
                  <div className="w-6 h-6 rounded-full bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot size={12} className="text-[#FFB020]" />
                  </div>
                )}
                <div
                  className={`max-w-[80%] px-3 py-2 rounded-[8px] text-xs leading-relaxed ${
                    msg.sender === 'user'
                      ? 'bg-[#FFB020]/10 border border-[#FFB020]/20 text-[#F2F1EE]'
                      : 'bg-[#141416] border border-white/[0.08] text-[#A8A8AB]'
                  }`}
                >
                  {msg.text}
                </div>
                {msg.sender === 'user' && (
                  <div className="w-6 h-6 rounded-full bg-white/[0.06] border border-white/[0.1] flex items-center justify-center shrink-0 mt-0.5">
                    <User size={12} className="text-[#9C9C9F]" />
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <form onSubmit={handleSend} className="flex items-center gap-2 pt-3 border-t border-white/[0.08]">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`Message ${agent.name}...`}
            className="flex-1 px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            disabled={sending}
          />
          <Button
            variant="primary"
            size="sm"
            type="submit"
            loading={sending}
            icon={<Send size={13} />}
            disabled={!input.trim()}
          >
            Send
          </Button>
        </form>
      </div>
    </Drawer>
  );
}
