import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const authState = vi.hoisted(() => ({ isAdmin: true }));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => authState,
}));

import { Sidebar } from '../Sidebar';

describe('Sidebar navigation', () => {
  afterEach(() => {
    authState.isAdmin = true;
    cleanup();
  });

  it('offers Tool Effect Recovery to an administrator', () => {
    authState.isAdmin = true;
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', { name: /Tool Effect Recovery/ })).toBeInTheDocument();
  });

  it('hides Tool Effect Recovery from a non-admin and keeps the rest of the group', () => {
    authState.isAdmin = false;
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    );
    expect(screen.queryByRole('link', { name: /Tool Effect Recovery/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Approval Gate/ })).toBeInTheDocument();
  });
});
