import { COMPANY_ID } from '@/config';

export interface RealtimeEvent {
  event_id: string;
  event_type: string;
  channel?: string;
  timestamp: string;
  company_id?: string;
  data: Record<string, unknown>;
}

export interface StreamOptions {
  eventTypes?: string[];
  channel?: string;
  onEvent: (event: RealtimeEvent) => void;
  onError?: (error: Error) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export class SSEStreamClient {
  private controller: AbortController | null = null;
  private isActive = false;
  private reconnectTimeout: number | null = null;

  constructor(private options: StreamOptions) {}

  public start() {
    if (this.isActive) return;
    this.isActive = true;
    this.connect();
  }

  public stop() {
    this.isActive = false;
    if (this.reconnectTimeout) {
      window.clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
    this.options.onDisconnect?.();
  }

  private async connect() {
    if (!this.isActive) return;

    this.controller = new AbortController();
    const url = new URL('/events/stream', BASE_URL);

    if (this.options.eventTypes && this.options.eventTypes.length > 0) {
      url.searchParams.set('event_types', this.options.eventTypes.join(','));
    }
    if (this.options.channel) {
      url.searchParams.set('channel', this.options.channel);
    }

    try {
      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Accept': 'text/event-stream',
          'X-Company-Id': COMPANY_ID,
        },
        signal: this.controller.signal,
      });

      if (!response.ok) {
        throw new Error(`SSE Connection failed with status ${response.status}`);
      }

      this.options.onConnect?.();

      if (!response.body) {
        throw new Error('Response body is null');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (this.isActive) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const block of lines) {
          if (!block.trim() || block.startsWith(':')) continue; // Skip empty lines and keepalives

          const eventLines = block.split('\n');
          let dataStr = '';

          for (const line of eventLines) {
            if (line.startsWith('data:')) {
              dataStr += line.slice(5).trim();
            }
          }

          if (dataStr) {
            try {
              const parsed: RealtimeEvent = JSON.parse(dataStr);
              this.options.onEvent(parsed);
            } catch (err) {
              console.warn('Failed to parse SSE event payload:', dataStr, err);
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') return; // Intentional stop
      this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
    } finally {
      if (this.isActive) {
        this.options.onDisconnect?.();
        // Auto-reconnect after 3 seconds
        this.reconnectTimeout = window.setTimeout(() => this.connect(), 3000);
      }
    }
  }
}
