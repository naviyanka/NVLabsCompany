import { useEffect, useState, useCallback, useRef } from 'react';
import { SSEStreamClient, type RealtimeEvent } from '@/api/events';

export interface UseEventStreamOptions {
  eventTypes?: string[];
  channel?: string;
  maxEvents?: number;
  enabled?: boolean;
}

export interface UseEventStreamReturn {
  events: RealtimeEvent[];
  isConnected: boolean;
  error: Error | null;
  clearEvents: () => void;
}

export function useEventStream({
  eventTypes,
  channel,
  maxEvents = 100,
  enabled = true,
}: UseEventStreamOptions = {}): UseEventStreamReturn {
  const [events, setEvents] = useState<RealtimeEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const clientRef = useRef<SSEStreamClient | null>(null);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  useEffect(() => {
    if (!enabled) {
      if (clientRef.current) {
        clientRef.current.stop();
        clientRef.current = null;
      }
      setIsConnected(false);
      return;
    }

    const client = new SSEStreamClient({
      eventTypes,
      channel,
      onConnect: () => {
        setIsConnected(true);
        setError(null);
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onError: (err) => {
        setIsConnected(false);
        setError(err);
      },
      onEvent: (newEvent) => {
        setEvents((prev) => [newEvent, ...prev].slice(0, maxEvents));
      },
    });

    clientRef.current = client;
    client.start();

    return () => {
      client.stop();
      clientRef.current = null;
    };
  }, [enabled, channel, maxEvents, JSON.stringify(eventTypes)]);

  return {
    events,
    isConnected,
    error,
    clearEvents,
  };
}
