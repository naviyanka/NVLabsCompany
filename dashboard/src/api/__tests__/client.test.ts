import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/config', () => ({
  AUTH_ENABLED: false,
  SEED_COMPANY_ID: '00000000-0000-4000-8000-000000000001',
  getActiveCompanyId: () => 'company-1',
}));

import { apiClient } from '../client';

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
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
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
});
