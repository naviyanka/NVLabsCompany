import { apiUrl, postHeaders } from '@/api/client';

export interface ChatReply {
  message: { id: string; sender: 'user' | 'agent'; text: string; timestamp: string };
  model_used?: string | null;
  tokens_used?: number;
  adapter_used?: string | null;
  backend_used?: string | null;
  execution_id?: string | null;
}

export class ChatStreamError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'ChatStreamError';
  }
}

/** The endpoint a conversation posts to: an explicit session, or the agent's default one. */
export function chatStreamPath(agentId: string, sessionId: string | null): string {
  return sessionId
    ? `/api/v1/sessions/${sessionId}/messages/stream`
    : `/api/v1/agents/${agentId}/chat/stream`;
}

function detailMessage(body: unknown, fallback: string): { text: string; code?: string } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return { text: detail };
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; code?: string };
    return { text: d.message ?? fallback, code: d.code };
  }
  return { text: fallback };
}

export interface StreamHandlers {
  signal: AbortSignal;
  /** The server accepted the turn and is now running it. */
  onOpen?: () => void;
  onChunk?: (text: string) => void;
}

/**
 * POST one prompt to an SSE chat endpoint and resolve with the final reply.
 * Aborting `signal` disconnects, which cancels the turn (and its CLI process)
 * on the server. There is deliberately no non-streaming fallback: retrying a
 * failed stream as a plain POST could run the same prompt twice.
 */
export async function streamChat(
  path: string,
  prompt: string,
  { signal, onOpen, onChunk }: StreamHandlers,
): Promise<ChatReply> {
  const response = await fetch(apiUrl(path), {
    method: 'POST',
    headers: postHeaders(),
    credentials: 'include',
    body: JSON.stringify({ prompt }),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    const { text, code } = detailMessage(body, `Request failed (${response.status})`);
    throw new ChatStreamError(text, response.status, code);
  }
  onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data: ')) continue;
      const data = trimmed.slice(6);
      if (data === '[DONE]') continue;
      let event: { type?: string; text?: string; code?: string; status?: number } & Partial<ChatReply>;
      try {
        event = JSON.parse(data);
      } catch {
        continue;
      }
      if (event.type === 'chunk' && event.text) onChunk?.(event.text);
      else if (event.type === 'error') throw new ChatStreamError(event.text ?? 'Chat error', event.status, event.code);
      else if (event.type === 'done' && event.message) return event as ChatReply;
    }
  }
  throw new ChatStreamError('The stream ended without a reply');
}
