import { describe, it, expect, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import appSource from '../../App.tsx?raw';
import App from '../../App';

vi.mock('@/hooks/useEventStream', () => ({ useEventStream: vi.fn() }));
vi.mock('@/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({ status: 'authenticated', user: null, logout: vi.fn() }),
}));

// Every route the dashboard had before the workspace was added.
const EXISTING_PATHS = [
  '/login', '/setup', '/invite', '/', '/overview', '/office', '/hr-room', '/plaza', '/agents',
  '/agents/:id', '/tasks', '/pipelines', '/organization', '/goals', '/skills', '/tools', '/memory',
  '/memory-graph', '/git-repos', '/knowledge', '/knowledge-base', '/approvals', '/budgets',
  '/evolution', '/workflows', '/nodes', '/meetings', '/activity', '/notifications', '/terminal',
  '/settings', '*',
];

describe('App routes', () => {
  it('keeps every existing route and adds /workspace', () => {
    const declared = [...appSource.matchAll(/path="([^"]*)"/g)].map((m) => m[1]);
    expect(declared).toEqual(expect.arrayContaining([...EXISTING_PATHS, '/workspace']));
  });

  it.each(['/workspace', '/agents', '/tasks', '/approvals', '/activity'])(
    'renders %s inside the shell without redirecting',
    async (path) => {
      window.history.pushState({}, '', path);
      render(<App />);
      expect(await screen.findByRole('link', { name: /Agent Workspace/ })).toBeTruthy();
      expect(window.location.pathname).toBe(path);
      cleanup();
    }
  );
});
