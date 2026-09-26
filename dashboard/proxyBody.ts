import type { ServerResponse } from 'http';
import { Readable } from 'stream';
import type { ReadableStream as WebReadableStream } from 'stream/web';

/**
 * Send an upstream `fetch` response body on to the browser as it arrives.
 *
 * Reading the whole body first (`arrayBuffer()`) never finishes for an event
 * stream, so realtime events would never reach the browser. When the browser
 * goes away, the upstream request is cancelled with it.
 */
export function pipeBody(upstream: Response, res: ServerResponse): void {
  if (!upstream.body) {
    res.end();
    return;
  }
  const body = Readable.fromWeb(upstream.body as WebReadableStream<Uint8Array>);
  body.on('error', () => res.destroy());
  res.on('close', () => body.destroy());
  res.flushHeaders();
  body.pipe(res);
}
