import { expect, request, test } from '@playwright/test';

/**
 * Mock/real response-shape parity.
 *
 * Every list endpoint below must answer with a bare JSON array. The mock
 * Express server used to wrap these in `{ items, total }` while FastAPI
 * returned `list[...]`, which is why the frontend needed an `unwrapItems()`
 * shim. This spec is the guard that keeps the two agreeing: CI runs it against
 * the mock (default) and against the real backend (`PROXY_API=true`), so a
 * divergence on either side fails the build.
 *
 *   E2E_BASE_URL=http://localhost:3000 npx playwright test e2e/api-parity.spec.ts
 */
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const COMPANY_ID = process.env.E2E_COMPANY_ID || '00000000-0000-4000-8000-000000000001';

/** Company-scoped GET endpoints served by both the mock and the real API. */
const LIST_ENDPOINTS = [
  'agents',
  'tasks',
  'skills',
  'tools',
  'goals',
  'meetings',
  'pipelines',
  'knowledge',
  'notifications',
  'activity',
  'memory',
  'workflows',
  'departments',
  'audit-logs',
  'repos',
  'evolution/proposals',
];

test.describe('mock/real list-shape parity', () => {
  for (const endpoint of LIST_ENDPOINTS) {
    test(`GET /${endpoint} returns a bare array`, async () => {
      const api = await request.newContext({
        baseURL: BASE_URL,
        // With AUTH_ENABLED=false the API takes the tenant from this header.
        extraHTTPHeaders: { 'X-Company-Id': COMPANY_ID },
      });
      const res = await api.get(`/api/v1/companies/${COMPANY_ID}/${endpoint}`);
      expect(res.status(), `${endpoint} should answer 200`).toBe(200);

      const body = await res.json();
      // `{ items: [...] }` is the exact divergence this spec exists to catch.
      expect(
        Array.isArray(body),
        `${endpoint} returned ${JSON.stringify(body).slice(0, 120)} — list endpoints must be bare arrays, not wrapped`
      ).toBe(true);

      await api.dispose();
    });
  }
});
