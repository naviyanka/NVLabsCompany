import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/config', () => ({
  AUTH_ENABLED: false,
  SEED_COMPANY_ID: '00000000-0000-4000-8000-000000000001',
  getActiveCompanyId: () => 'company-1',
}));

import { ApiClientError, apiClient } from '../client';

const fetchMock = vi.fn();

function sentHeaders(): Record<string, string> {
  const init = fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> };
  return init.headers;
}

const MANDATORY = {
  'Content-Type': 'application/json',
  'X-CSRF-Token': 'csrf-abc',
  'X-Company-Id': 'company-1',
};

describe('apiClient headers', () => {
  beforeEach(() => {
    document.cookie = 'nv_csrf=csrf-abc';
    fetchMock.mockReset();
    fetchMock.mockImplementation(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    document.cookie = 'nv_csrf=; max-age=0';
    vi.unstubAllGlobals();
  });

  it('sends exactly the default headers when the caller adds none', async () => {
    await apiClient.post('/api/v1/work', { title: 'x' });
    expect(sentHeaders()).toEqual(MANDATORY);
  });

  it('keeps the CSRF, content type and tenant headers next to a caller header', async () => {
    await apiClient.post('/api/v1/work', { title: 'x' }, { 'Idempotency-Key': 'k-1' });
    expect(sentHeaders()).toEqual({ ...MANDATORY, 'Idempotency-Key': 'k-1' });
  });

  it('ignores a caller header that tries to replace a mandatory one', async () => {
    await apiClient.post('/api/v1/work', {}, {
      'X-CSRF-Token': 'forged',
      'Content-Type': 'text/plain',
      'X-Company-Id': 'someone-else',
    });
    expect(sentHeaders()).toEqual(MANDATORY);
  });

  const CASINGS: Record<string, string[]> = {
    'X-CSRF-Token': ['X-CSRF-Token', 'x-csrf-token', 'X-Csrf-Token', 'X-CSRF-TOKEN'],
    'Content-Type': ['Content-Type', 'content-type', 'CONTENT-TYPE', 'Content-type'],
    'X-Company-Id': ['X-Company-Id', 'x-company-id', 'X-COMPANY-ID', 'x-Company-ID'],
  };

  /** What `fetch` would send: one entry per case-insensitive name. */
  function wire(): Map<string, string[]> {
    const out = new Map<string, string[]>();
    for (const [name, value] of Object.entries(sentHeaders())) {
      out.set(name.toLowerCase(), [...(out.get(name.toLowerCase()) ?? []), value]);
    }
    return out;
  }

  for (const [canonical, variants] of Object.entries(CASINGS)) {
    for (const variant of variants) {
      it(`cannot override ${canonical} with ${variant}`, async () => {
        await apiClient.post('/api/v1/work', {}, { [variant]: 'forged' });
        expect(wire().get(canonical.toLowerCase())).toEqual([MANDATORY[canonical as keyof typeof MANDATORY]]);
        expect(Object.values(sentHeaders())).not.toContain('forged');
      });

      it(`cannot remove ${canonical} with an empty or undefined ${variant}`, async () => {
        const expected = [MANDATORY[canonical as keyof typeof MANDATORY]];
        await apiClient.post('/api/v1/work', {}, { [variant]: '' });
        expect(wire().get(canonical.toLowerCase())).toEqual(expected);
        fetchMock.mockClear();
        await apiClient.post(
          '/api/v1/work', {}, { [variant]: undefined } as unknown as Record<string, string>,
        );
        expect(wire().get(canonical.toLowerCase())).toEqual(expected);
      });
    }

    it(`keeps one ${canonical} when the caller sends every casing at once`, async () => {
      const all = Object.fromEntries(variants.map((v) => [v, `forged-${v}`]));
      await apiClient.post('/api/v1/work', {}, all);
      expect(wire().get(canonical.toLowerCase())).toEqual([MANDATORY[canonical as keyof typeof MANDATORY]]);
    });
  }

  it('never lets a caller add a client-owned header the request does not use', async () => {
    // A GET carries no CSRF echo, so a caller header of that name must not appear either.
    await apiClient.get('/api/v1/work');
    expect(wire().has('x-csrf-token')).toBe(false);
    fetchMock.mockClear();
    document.cookie = 'nv_csrf=; max-age=0';
    await apiClient.post('/api/v1/work', {}, { 'x-csrf-token': 'forged' });
    expect(wire().has('x-csrf-token')).toBe(false);
  });

  it('keeps Idempotency-Key, deduplicated, next to attempted overrides', async () => {
    await apiClient.post('/api/v1/work', {}, {
      'Idempotency-Key': 'old',
      'idempotency-key': 'k-2',
      'x-csrf-token': 'forged',
    });
    expect(wire().get('idempotency-key')).toEqual(['k-2']);
    expect(wire().get('x-csrf-token')).toEqual(['csrf-abc']);
  });

  it('keeps two-argument and bodyless calls working', async () => {
    await apiClient.post('/api/v1/work', { title: 'x' });
    expect(sentHeaders()).toEqual(MANDATORY);
    fetchMock.mockClear();
    await apiClient.put('/api/v1/work/1', { title: 'y' });
    await apiClient.delete('/api/v1/work/1');
    await apiClient.get('/api/v1/work', { limit: 5 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('puts no header value in an error or in the console', async () => {
    const spies = (['log', 'warn', 'error', 'info', 'debug'] as const).map((level) =>
      vi.spyOn(console, level).mockImplementation(() => {}),
    );
    fetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: 'Forbidden' }), { status: 403, statusText: 'Forbidden' }),
    );
    let caught: unknown;
    try {
      await apiClient.post('/api/v1/work', {}, { 'Idempotency-Key': 'secret-key', 'x-csrf-token': 'forged' });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiClientError);
    const text = `${(caught as Error).message} ${(caught as ApiClientError).detail}`;
    for (const value of ['csrf-abc', 'secret-key', 'forged', 'company-1']) {
      expect(text).not.toContain(value);
    }
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toMatch(/csrf-abc|secret-key|forged/);
    }
    spies.forEach((spy) => spy.mockRestore());
  });
});
