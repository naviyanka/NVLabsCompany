// @vitest-environment node
import http from 'http';
import type { AddressInfo } from 'net';
import { afterEach, expect, it } from 'vitest';

import { voiceSocketUpgrade, VOICE_WS_PATH } from './voiceSocketProxy';

const servers: http.Server[] = [];
afterEach(() => {
  servers.splice(0).forEach((s) => s.close());
});

const listen = async (s: http.Server) => {
  servers.push(s);
  await new Promise<void>((r) => s.listen(0, '127.0.0.1', r));
  return (s.address() as AddressInfo).port;
};

/** A backend that upgrades /api/v1/voice/ws and echoes what it saw; anything else is a plain 404. */
async function backend() {
  const seen: http.IncomingHttpHeaders[] = [];
  const s = http.createServer((_req, res) => res.writeHead(404).end());
  s.on('upgrade', (req, socket) => {
    seen.push(req.headers);
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n');
    socket.on('data', (d) => socket.write(`echo:${d}`));
  });
  return { port: await listen(s), seen };
}

async function dashboard(backendPort: number) {
  const s = http.createServer((_q, r) => r.writeHead(404).end());
  s.on('upgrade', voiceSocketUpgrade(`http://127.0.0.1:${backendPort}`));
  return listen(s);
}

/** A browser stand-in: a WebSocket handshake with the given headers. */
function handshake(port: number, headers: Record<string, string>, path = VOICE_WS_PATH) {
  return new Promise<{ status?: number; data?: string; closed?: boolean }>((resolve) => {
    const req = http.request({ port, host: '127.0.0.1', path, headers: { Connection: 'Upgrade', Upgrade: 'websocket', ...headers } });
    req.on('upgrade', (res, socket) => {
      socket.write('ping');
      socket.once('data', (d) => {
        socket.destroy();
        resolve({ status: res.statusCode, data: d.toString() });
      });
    });
    req.on('response', (res) => resolve({ status: res.statusCode }));
    req.on('error', () => resolve({ closed: true }));
    req.end();
  });
}

it('tunnels the voice upgrade to the backend with the session cookie and no Authorization', async () => {
  const b = await backend();
  const port = await dashboard(b.port);
  const r = await handshake(port, {
    Host: `localhost:${port}`,
    Origin: `http://localhost:${port}`,
    Cookie: 'nexus_session=abc',
    Authorization: 'Bearer nope',
    'Sec-WebSocket-Key': 'k',
    'Sec-WebSocket-Version': '13',
  });
  expect(r).toEqual({ status: 101, data: 'echo:ping' });
  expect(b.seen[0].cookie).toBe('nexus_session=abc');
  expect(b.seen[0].authorization).toBeUndefined();
});

it('refuses a cross-origin handshake without contacting the backend', async () => {
  const b = await backend();
  const port = await dashboard(b.port);
  const r = await handshake(port, { Host: `localhost:${port}`, Origin: 'http://evil.example' });
  expect(r.status).toBe(403);
  expect(b.seen).toHaveLength(0);
});

it('does not proxy any other WebSocket path', async () => {
  const b = await backend();
  const port = await dashboard(b.port);
  expect((await handshake(port, { Host: `localhost:${port}` }, '/api/v1/other/ws')).closed).toBe(true);
  expect((await handshake(port, { Host: `localhost:${port}` }, `${VOICE_WS_PATH}?ticket=x`)).closed).toBe(true);
  expect(b.seen).toHaveLength(0);
});

it("passes the backend's refusal on, and reports an unreachable backend as 502", async () => {
  const refusing = http.createServer((_q, r) => r.writeHead(403).end());
  const port = await dashboard(await listen(refusing));
  expect((await handshake(port, { Host: `localhost:${port}` })).status).toBe(403);

  const down = await dashboard(1);
  expect((await handshake(down, { Host: `localhost:${down}` })).status).toBe(502);
});
