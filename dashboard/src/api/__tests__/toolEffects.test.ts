import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MAX_PAGE_LIMIT, listOpenEffects, resolveEffect } from '../toolEffects';

const fetchMock = vi.fn();

function sentRequest(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, init };
}

function sentHeaders(): Record<string, string> {
  return (sentRequest().init as { headers: Record<string, string> }).headers;
}

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

describe('toolEffects api module', () => {
  beforeEach(() => {
    document.cookie = 'nv_csrf=csrf-abc';
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => okJson({ items: [], next_cursor: null }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    document.cookie = 'nv_csrf=; max-age=0';
    vi.unstubAllGlobals();
  });

  it('requests the first page at the server default limit with no cursor', async () => {
    await listOpenEffects();
    const { url } = sentRequest();
    expect(url).toContain('/api/v1/tool-effects/open');
    expect(url).toContain('limit=100');
    expect(url).not.toContain('cursor=');
  });

  it('passes a returned cursor back verbatim for the next page', async () => {
    await listOpenEffects('a-keyset-cursor', 50);
    const { url } = sentRequest();
    expect(url).toContain('cursor=a-keyset-cursor');
    expect(url).toContain('limit=50');
  });

  it('clamps the requested limit into the server 1..500 window', async () => {
    await listOpenEffects(null, MAX_PAGE_LIMIT + 1000);
    expect(sentRequest().url).toContain('limit=500');
    fetchMock.mockClear();
    await listOpenEffects(null, -20);
    expect(sentRequest().url).toContain('limit=1');
  });

  it('posts the exact resolve body to the resolve path', async () => {
    fetchMock.mockImplementation(
      async () => okJson({ id: 'e1', status: 'failed', outcome: 'not_applied' })
    );
    const response = await resolveEffect('11111111-1111-4111-8111-111111111111', {
      outcome: 'not_applied',
      reason: 'provider shows no message',
      note: null,
    });
    const { url, init } = sentRequest();
    expect(url).toContain('/api/v1/tool-effects/11111111-1111-4111-8111-111111111111/resolve');
    expect(init.method).toBe('POST');
    expect(init.body).toBe(
      JSON.stringify({ outcome: 'not_applied', reason: 'provider shows no message', note: null })
    );
    expect(response).toEqual({ id: 'e1', status: 'failed', outcome: 'not_applied' });
  });

  it('url-encodes the effect id in the resolve path', async () => {
    await resolveEffect('not a uuid', { outcome: 'applied', reason: 'r' });
    expect(sentRequest().url).toContain('/api/v1/tool-effects/not%20a%20uuid/resolve');
  });

  it('sends exactly the mandatory headers — the module exposes no way to add or replace one', async () => {
    await resolveEffect('e1', { outcome: 'applied', reason: 'r' });
    expect(sentHeaders()).toEqual({
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'csrf-abc',
    });
  });

  it('never sends a tenant header under real auth: the session decides the scope', async () => {
    await listOpenEffects();
    expect(sentHeaders()['X-Company-Id']).toBeUndefined();
  });
});
