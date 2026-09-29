import { afterEach, expect, it, vi } from 'vitest';

import { wsUrl } from './voiceClient';

afterEach(() => vi.unstubAllGlobals());

const from = (href: string) => vi.stubGlobal('window', { location: { href } });

it('follows the page origin, so the dev proxy and a same-origin reverse proxy both work', () => {
  from('http://localhost:3100/agents');
  expect(wsUrl('/api/v1/voice/ws')).toBe('ws://localhost:3100/api/v1/voice/ws');
});

it('uses wss under HTTPS and has no development port', () => {
  from('https://nexus.example.com/agents');
  expect(wsUrl('/api/v1/voice/ws')).toBe('wss://nexus.example.com/api/v1/voice/ws');
});

it('carries no token, ticket or query string', () => {
  from('https://nexus.example.com/agents?ticket=leak');
  expect(new URL(wsUrl('/api/v1/voice/ws')).search).toBe('');
});
