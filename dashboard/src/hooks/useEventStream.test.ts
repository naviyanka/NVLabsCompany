import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useEventStream } from './useEventStream';

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  options?: EventSourceInit;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState: number = 0;
  closed: boolean = false;

  constructor(url: string, options?: EventSourceInit) {
    this.url = url;
    this.options = options;
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emitMessage(data: any) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      }));
    }
  }

  emitError() {
    if (this.onerror) {
      this.onerror();
    }
  }
}

describe('useEventStream', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllTimers();
  });

  it('connects to the correct channel endpoint with credentials', () => {
    const onEvent = vi.fn();
    renderHook(() => useEventStream('tasks', onEvent));

    expect(MockEventSource.instances.length).toBe(1);
    const instance = MockEventSource.instances[0]!;
    expect(instance.url).toBe('/api/v1/events/stream?channel=tasks');
    expect(instance.options?.withCredentials).toBe(true);
  });

  it('delivers parsed JSON payloads to onEvent callback', () => {
    const onEvent = vi.fn();
    renderHook(() => useEventStream('tasks', onEvent));

    const instance = MockEventSource.instances[0]!;
    instance.emitMessage({ id: 'task-123', title: 'New Task' });

    expect(onEvent).toHaveBeenCalledWith({ id: 'task-123', title: 'New Task' });
  });

  it('cleans up and closes EventSource on unmount', () => {
    const onEvent = vi.fn();
    const { unmount } = renderHook(() => useEventStream('tasks', onEvent));

    expect(MockEventSource.instances.length).toBe(1);
    const instance = MockEventSource.instances[0]!;
    expect(instance.closed).toBe(false);

    unmount();
    expect(instance.closed).toBe(true);
  });
});
