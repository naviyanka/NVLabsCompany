import http from 'http';
import type { IncomingMessage } from 'http';
import type { Duplex } from 'stream';

/** The only WebSocket path the dev server forwards. Express cannot proxy an upgrade itself. */
export const VOICE_WS_PATH = '/api/v1/voice/ws';

// Handshake headers only. Authorization is never forwarded: the browser authenticates the
// upgrade with its session cookie, and the signed hello ticket then binds it to that user.
const FORWARDED = ['cookie', 'origin', 'user-agent', 'sec-websocket-key', 'sec-websocket-version', 'sec-websocket-protocol'];

function refuse(socket: Duplex, status: string): void {
  socket.end(`HTTP/1.1 ${status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

/**
 * `upgrade` handler that tunnels the voice WebSocket to the backend, and nothing else.
 * Any other upgrade is dropped (Vite HMR has its own port). A cross-origin handshake is
 * refused here as well as by the backend, so it never reaches it.
 */
export function voiceSocketUpgrade(backendUrl: string) {
  const backend = new URL(backendUrl);
  return (req: IncomingMessage, socket: Duplex, head: Buffer): void => {
    if (req.url !== VOICE_WS_PATH) return void socket.destroy();
    const origin = req.headers.origin;
    let sameOrigin = true;
    try {
      sameOrigin = !origin || new URL(origin).host === req.headers.host;
    } catch {
      sameOrigin = false;
    }
    if (!sameOrigin) return refuse(socket, '403 Forbidden');

    const headers: Record<string, string> = { connection: 'Upgrade', upgrade: 'websocket' };
    for (const name of FORWARDED) {
      const value = req.headers[name];
      if (typeof value === 'string') headers[name] = value;
    }
    const upstream = http.request({
      hostname: backend.hostname,
      port: backend.port || 80,
      path: VOICE_WS_PATH,
      headers,
    });
    upstream.on('upgrade', (res, upstreamSocket, upstreamHead) => {
      let raw = `HTTP/1.1 101 Switching Protocols\r\n`;
      for (let i = 0; i < res.rawHeaders.length; i += 2) raw += `${res.rawHeaders[i]}: ${res.rawHeaders[i + 1]}\r\n`;
      socket.write(`${raw}\r\n`);
      if (upstreamHead.length) socket.write(upstreamHead);
      if (head.length) upstreamSocket.write(head);
      upstreamSocket.pipe(socket);
      socket.pipe(upstreamSocket);
      socket.on('error', () => upstreamSocket.destroy());
      upstreamSocket.on('error', () => socket.destroy());
      socket.on('close', () => upstreamSocket.destroy());
      upstreamSocket.on('close', () => socket.destroy());
    });
    // The backend answered with a plain HTTP response: it refused the handshake.
    upstream.on('response', (res) => {
      res.resume();
      refuse(socket, `${res.statusCode} ${res.statusMessage ?? 'Error'}`);
    });
    upstream.on('error', () => refuse(socket, '502 Bad Gateway'));
    upstream.end();
  };
}
