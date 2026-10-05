import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';

import { Login } from '../Login';
import { ApiClientError } from '@/api/client';
import type { MeResponse } from '@/api/auth';

const { mockUseAuth, mockLogin } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockLogin: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => mockUseAuth(),
}));

const ME_RESPONSE: MeResponse = {
  kind: 'user',
  role: 'admin',
  company_id: 'company-1',
  company_name: 'NVLabs',
  display_name: 'Ops',
  user: null,
  memberships: [],
};

const EMAIL = 'ops@nvlabs.dev';
const PASSWORD = 'correct horse battery staple';

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>mission control</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function getForm(container: HTMLElement): HTMLFormElement {
  const form = container.querySelector('form');
  if (!form) throw new Error('login form not rendered');
  return form;
}

function submitForm(container: HTMLElement) {
  // Dispatched directly so jsdom's native constraint validation does not mask
  // the page's own validation layer.
  fireEvent(getForm(container), new Event('submit', { bubbles: true, cancelable: true }));
}

function fillLoginForm(email = EMAIL, password = PASSWORD) {
  fireEvent.change(screen.getByLabelText('Operator Email'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
}

beforeEach(() => {
  mockUseAuth.mockReset();
  mockLogin.mockReset();
  mockUseAuth.mockReturnValue({
    status: 'anonymous',
    me: null,
    role: '',
    companyId: null,
    isAdmin: false,
    login: mockLogin,
    logout: vi.fn(),
    refresh: vi.fn(),
    adoptIdentity: vi.fn(),
    switchCompany: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Login accessibility and reliability', () => {
  it('gives both inputs accessible labels and marks them required', () => {
    renderLogin();
    expect(screen.getByLabelText('Operator Email')).toBeRequired();
    expect(screen.getByLabelText('Password')).toBeRequired();
  });

  it('uses standard autocomplete tokens', () => {
    renderLogin();
    expect(screen.getByLabelText('Operator Email')).toHaveAttribute('autocomplete', 'username');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password');
  });

  it('submits through normal form semantics when the submit button is clicked', () => {
    mockLogin.mockResolvedValue(ME_RESPONSE);
    renderLogin();
    fillLoginForm();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mockLogin).toHaveBeenCalledTimes(1);
    expect(mockLogin).toHaveBeenCalledWith(EMAIL, PASSWORD);
  });

  it('blocks submission and focuses the email field when the email is missing', () => {
    const { container } = renderLogin();
    fillLoginForm('', PASSWORD);
    submitForm(container);
    expect(mockLogin).not.toHaveBeenCalled();
    const email = screen.getByLabelText('Operator Email');
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(email).toHaveAttribute('aria-describedby', 'login-email-error');
    expect(screen.getByText('Enter your operator email.').id).toBe('login-email-error');
    expect(email).toHaveFocus();
  });

  it('associates the password validation error with the password field', () => {
    const { container } = renderLogin();
    fillLoginForm(EMAIL, '');
    submitForm(container);
    expect(mockLogin).not.toHaveBeenCalled();
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('aria-invalid', 'true');
    expect(password).toHaveAttribute('aria-describedby', 'login-password-error');
    expect(screen.getByText('Enter your password.').id).toBe('login-password-error');
    expect(password).toHaveFocus();
  });

  it('announces a server error via role="alert" and moves focus to it', async () => {
    mockLogin.mockRejectedValue(
      new ApiClientError(401, 'Unauthorized', 'Unknown email or wrong password.')
    );
    const { container } = renderLogin();
    fillLoginForm();
    submitForm(container);
    const alert = await screen.findByRole('alert');
    expect(alert.id).toBe('login-error');
    expect(alert).toHaveTextContent('Unknown email or wrong password.');
    // Focus is set in an effect after the error commits; wait for it to land.
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it('disables the submit control and ignores re-submission while pending', async () => {
    mockLogin.mockImplementation(() => new Promise(() => {}));
    const { container } = renderLogin();
    fillLoginForm();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    const pendingButton = screen.getByRole('button', { name: /opening session/i });
    expect(pendingButton).toBeDisabled();
    expect(getForm(container)).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(pendingButton);
    submitForm(container);
    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });
  });

  it('re-enables submission after a failed request', async () => {
    mockLogin.mockRejectedValue(
      new ApiClientError(401, 'Unauthorized', 'Unknown email or wrong password.')
    );
    renderLogin();
    fillLoginForm();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await screen.findByRole('alert');
    const button = screen.getByRole('button', { name: /sign in/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    const secondAlert = await screen.findByRole('alert');
    expect(secondAlert).toBeInTheDocument();
    expect(mockLogin).toHaveBeenCalledTimes(2);
  });

  it('never renders the password in error output', async () => {
    mockLogin.mockRejectedValue(new Error('network down'));
    const { container } = renderLogin();
    fillLoginForm(EMAIL, PASSWORD);
    submitForm(container);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Cannot reach the control plane.');
    expect(document.body.textContent).not.toContain(PASSWORD);
  });

  it('keeps the successful sign-in redirect intact', async () => {
    mockLogin.mockResolvedValue(ME_RESPONSE);
    renderLogin();
    fillLoginForm();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('mission control')).toBeInTheDocument();
    expect(mockLogin).toHaveBeenCalledWith(EMAIL, PASSWORD);
    expect(screen.queryByRole('button', { name: /sign in/i })).toBeNull();
  });

  it('trims the email but never alters the password', () => {
    mockLogin.mockResolvedValue(ME_RESPONSE);
    renderLogin();
    fillLoginForm(`  ${EMAIL}  `, '  spaced secret  ');
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mockLogin).toHaveBeenCalledWith(EMAIL, '  spaced secret  ');
  });
});
