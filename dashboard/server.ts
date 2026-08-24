/**
 * NEXUS Dashboard Server — API Proxy + Vite Dev Server
 *
 * All API requests are forwarded to the real FastAPI backend.
 * No mock data, no in-memory databases.
 *
 * Environment variables:
 * - NEXUS_API_URL: Backend URL (default: http://localhost:8000)
 * - PORT: Server port (default: 3000)
 * - NODE_ENV: 'production' for static serving, else Vite dev mode
 */

import express from 'express';
import type { Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import { createServer as createViteServer } from 'vite';

const app = express();
const PORT = parseInt(process.env.PORT || '3000', 10);
const NEXUS_API_URL = process.env.NEXUS_API_URL || 'http://localhost:8000';

// ──────────────── Process Crash Protection ────────────────

process.on('uncaughtException', (err) => {
  console.error('[Process Supervisor] Caught uncaughtException:', err);
});

process.on('unhandledRejection', (reason) => {
  console.error('[Process Supervisor] Caught unhandledRejection:', reason);
});

// ──────────────── API Proxy to FastAPI Backend ────────────────

/** Headers worth forwarding to the upstream backend. */
const FORWARDED_REQUEST_HEADERS = [
  'accept',
  'authorization',
  'content-type',
  'cookie',
  'user-agent',
  'x-api-key',
  'x-company-id',
  'x-csrf-token',
];

function readRawBody(req: Request): Promise<Buffer> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', () => resolve(Buffer.from('')));
  });
}

function readSetCookie(headers: Headers): string[] {
  const undiciHeaders = headers as Headers & { getSetCookie?: () => string[] };
  if (typeof undiciHeaders.getSetCookie === 'function') {
    return undiciHeaders.getSetCookie();
  }
  const single = headers.get('set-cookie');
  return single ? [single] : [];
}

/**
 * Proxy ALL /api/* requests to the real FastAPI backend.
 * This middleware must run BEFORE express.json() to preserve raw body streaming.
 */
app.use(async (req: Request, res: Response, next: NextFunction) => {
  if (!req.url.startsWith('/api/')) {
    next();
    return;
  }

  const headers: Record<string, string> = {};
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers[name];
    if (typeof value === 'string') headers[name] = value;
  }

  const hasBody = req.method !== 'GET' && req.method !== 'HEAD';

  try {
    const raw = hasBody ? await readRawBody(req) : undefined;
    const upstream = await fetch(new URL(req.url, NEXUS_API_URL), {
      method: req.method,
      headers,
      body: raw && raw.length > 0 ? new Uint8Array(raw) : undefined,
      redirect: 'manual',
    });

    // Forward cookies (session + CSRF)
    const cookies = readSetCookie(upstream.headers);
    if (cookies.length > 0) res.setHeader('set-cookie', cookies);

    const contentType = upstream.headers.get('content-type');
    if (contentType) res.setHeader('content-type', contentType);

    // Forward rate limit headers
    const rl = upstream.headers.get('x-ratelimit-remaining');
    if (rl) res.setHeader('x-ratelimit-remaining', rl);

    res.status(upstream.status);
    res.end(Buffer.from(await upstream.arrayBuffer()));
  } catch (err) {
    console.error(`[Proxy] Cannot reach ${NEXUS_API_URL} for ${req.method} ${req.url}`);
    res.status(502).json({
      detail: `Cannot reach the NEXUS API at ${NEXUS_API_URL}. Start it with: uvicorn nexus.main:app --port 8000`,
    });
  }
});

// ──────────────── Vite Dev Server / Production Static ────────────────

async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
    app.use('*', async (req, res, next) => {
      if (req.originalUrl.startsWith('/api/')) return next();
      try {
        const url = req.originalUrl;
        let template = fs.readFileSync(path.resolve(process.cwd(), 'index.html'), 'utf-8');
        template = await vite.transformIndexHtml(url, template);
        res.status(200).set({ 'Content-Type': 'text/html' }).end(template);
      } catch (e) {
        vite.ssrFixStacktrace(e as Error);
        next(e);
      }
    });
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      if (req.url.startsWith('/api/')) return;
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`\n  NEXUS Dashboard → http://localhost:${PORT}`);
    console.log(`  API Proxy     → ${NEXUS_API_URL}`);
    console.log(`  Mode          → ${process.env.NODE_ENV === 'production' ? 'Production (static)' : 'Development (Vite HMR)'}\n`);
  });
}

startServer().catch((err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
