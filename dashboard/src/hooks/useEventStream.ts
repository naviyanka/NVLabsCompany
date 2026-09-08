import { useEffect, useRef } from 'react';

/**
 * Minimal custom hook using EventSource to stream real-time events.
 *
 * Connects to `/api/v1/events?channel=${channel}` with credentials: 'include'.
 * Features exponential backoff reconnection on error and cleanup on unmount.
 */
export function useEventStream<T = any>(
  channel: string,
  onEvent?: (data: T) => void
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!channel) return;

    let eventSource: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;
    let isMounted = true;

    const connect = () => {
      if (!isMounted) return;

      const url = `/api/v1/events/stream?channel=${encodeURIComponent(channel)}`;
      // with credentials: 'include' via EventSource's withCredentials option
      const es = new EventSource(url, { withCredentials: true });
      eventSource = es;

      es.onopen = () => {
        retryCount = 0;
      };

      es.onmessage = (event: MessageEvent) => {
        if (!onEventRef.current) return;
        try {
          const parsed = JSON.parse(event.data) as T;
          onEventRef.current(parsed);
        } catch {
          onEventRef.current(event.data as unknown as T);
        }
      };

      es.onerror = () => {
        if (es) {
          es.close();
        }
        if (eventSource === es) {
          eventSource = null;
        }

        if (!isMounted) return;

        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, up to 30s max
        const delay = Math.min(1000 * Math.pow(2, retryCount), 30000);
        retryCount++;

        if (retryTimer) {
          clearTimeout(retryTimer);
        }
        retryTimer = setTimeout(() => {
          connect();
        }, delay);
      };
    };

    connect();

    return () => {
      isMounted = false;
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };
  }, [channel]);
}
