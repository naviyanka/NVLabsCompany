// @vitest-environment node
import http from 'http';
import net from 'net';
import type { AddressInfo } from 'net';
import { expect, it, vi } from 'vitest';

import { pipeBody } from './proxyBody';

it('passes an event on while the upstream stream is still open, and cancels it when the browser leaves', async () => {
  let push!: ReadableStreamDefaultController<Uint8Array>;
  let cancelled = false;
  const upstream = new Response(
    new ReadableStream<Uint8Array>({
      start: (controller) => void (push = controller),
      cancel: () => void (cancelled = true),
    })
  );
  const proxy = http.createServer((_req, res) => {
    res.setHeader('content-type', 'text/event-stream');
    pipeBody(upstream, res);
  });
  await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve));

  try {
    // A raw socket plays the browser: the test setup's request interception
    // (msw) never sees it, so nothing between it and the proxy buffers.
    const { port } = proxy.address() as AddressInfo;
    const browser = net.connect(port, '127.0.0.1');
    let received = '';
    browser.on('data', (chunk) => void (received += chunk.toString()));
    browser.write('GET /api/v1/events/stream HTTP/1.1\r\nHost: localhost\r\n\r\n');

    await vi.waitFor(() => expect(received).toContain('content-type: text/event-stream'));
    push.enqueue(new TextEncoder().encode('event: session.updated\ndata: {}\n\n'));
    // The upstream never closes: the event arrives only if the proxy streams.
    await vi.waitFor(() => expect(received).toContain('event: session.updated\ndata: {}\n\n'));

    browser.destroy();
    await vi.waitFor(() => expect(cancelled).toBe(true));
  } finally {
    proxy.closeAllConnections();
    proxy.close();
  }
});
