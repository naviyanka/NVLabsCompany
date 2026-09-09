import '@testing-library/jest-dom';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll } from 'vitest';

export const handlers = [
  http.get('*/api/v1/companies/:companyId/tasks', () => {
    return HttpResponse.json([]);
  }),
  http.get('*/api/v1/companies/:companyId/agents', () => {
    return HttpResponse.json([]);
  }),
  http.get('*/api/v1/companies/:companyId/approvals/pending', () => {
    return HttpResponse.json([]);
  }),
  http.get('*/api/v1/companies/:companyId/activity', () => {
    return HttpResponse.json([]);
  }),
  http.get('*/api/v1/companies/:companyId/runs/liveness', () => {
    return HttpResponse.json({
      items: [],
      summary: { total: 0, healthy: 0, stalled: 0, confirmed_dead: 0 },
    });
  }),
];

export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
