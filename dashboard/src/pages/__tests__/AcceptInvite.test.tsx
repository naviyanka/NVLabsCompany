import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';

import { AcceptInvite } from '../AcceptInvite';
import { ApiClientError } from '@/api/client';
import type { InviteAcceptResponse } from '@/api/auth';

const { mockUseAuth, mockAcceptInvite } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockAcceptInvite: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  authApi: {
    acceptInvite: mockAcceptInvite,
  },
}));

vi.mock('@/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => mockUseAuth(),
}));

const ACCEPT_RESPONSE: InviteAcceptResponse = {
  company_id: 'company-1',
  role: 'member',
  account_created: true,
  message: 'Welcome to NVLabs.',
};

const TOKEN = 'invite-token-9f2c';
const VALID_PASSWORD = 'orbital-tangent-9';

function renderAcceptInvite(initialEntries: string[] = ['/invite']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/invite" element={<AcceptInvite />} />
        <Route path="/login" element={<div>sign in</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function getForm(container: HTMLElement): HTMLFormElement {
  const form = container.querySelector('form');
  if (!form) throw new Error('invite form not rendered');
  return form;
}

function submitForm(container: HTMLElement) {
  // Dispatched directly so jsdom's native constraint validation does not mask
  // the page's own validation layer.
  fireEvent(getForm(container), new Event('submit', { bubbles: true, cancelable: true }));
}

function fillToken(token = TOKEN) {
  fireEvent.change(screen.getByLabelText('Invite Token'), { target: { value: token } });
}

beforeEach(() => {
  mockUseAuth.mockReset();
  mockAcceptInvite.mockReset();
  mockUseAuth.mockReturnValue({
    status: 'anonymous',
    me: null,
    role: '',
    companyId: null,
    isAdmin: false,
    login: vi.fn(),
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

describe('AcceptInvite accessibility and reliability', () => {
  it('keeps the invite token out of the rendered UI and the console on failure', async () => {
    const logSpy = vi.spyOn(console, 'log');
    const warnSpy = vi.spyOn(console, 'warn');
    const errorSpy = vi.spyOn(console, 'error');
    const { container } = renderAcceptInvite();
    fillToken();
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: VALID_PASSWORD } });
    fireEvent.change(screen.getByLabelText('Confirm'), { target: { value: 'different-value' } });
    submitForm(container);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The two passwords do not match.');
    // The textarea legitimately holds the token as its value; nothing else in
    // the DOM (visible or announced) may carry it, and no console call may
    // echo it.
    const rest = document.body.cloneNode(true) as HTMLElement;
    rest.querySelector('#invite-token')?.remove();
    expect(rest.textContent).not.toContain(TOKEN);
    for (const spy of [logSpy, warnSpy, errorSpy]) {
      for (const call of spy.mock.calls) {
        expect(call.map(String).join(' ')).not.toContain(TOKEN);
      }
    }
  });

  it('gives every field an accessible label and requires the token', () => {
    renderAcceptInvite();
    expect(screen.getByLabelText('Invite Token')).toBeInTheDocument();
    expect(screen.getByLabelText('Invite Token')).toBeRequired();
    expect(screen.getByLabelText('First Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Last Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm')).toBeInTheDocument();
  });

  it('uses standard autocomplete values', () => {
    renderAcceptInvite();
    expect(screen.getByLabelText('First Name')).toHaveAttribute('autocomplete', 'given-name');
    expect(screen.getByLabelText('Last Name')).toHaveAttribute('autocomplete', 'family-name');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
    expect(screen.getByLabelText('Confirm')).toHaveAttribute('autocomplete', 'new-password');
    // The token is not a personal-data field; it must not claim an autocomplete token.
    expect(screen.getByLabelText('Invite Token')).not.toHaveAttribute('autocomplete');
  });

  it('announces an invalid or expired invitation error and moves focus to it', async () => {
    mockAcceptInvite.mockRejectedValue(
      new ApiClientError(400, 'Bad Request', 'This invite is invalid, expired, or already used.')
    );
    const { container } = renderAcceptInvite();
    fillToken();
    submitForm(container);
    const alert = await screen.findByRole('alert');
    expect(alert.id).toBe('invite-error');
    expect(alert).toHaveTextContent('This invite is invalid, expired, or already used.');
    // Focus is set in an effect after the error commits; wait for it to land.
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it('reports a missing token on the field without a request', () => {
    const { container } = renderAcceptInvite();
    submitForm(container);
    expect(mockAcceptInvite).not.toHaveBeenCalled();
    const tokenField = screen.getByLabelText('Invite Token');
    expect(tokenField).toHaveAttribute('aria-invalid', 'true');
    expect(tokenField).toHaveAttribute('aria-describedby', 'invite-token-error');
    expect(screen.getByText('Paste the invite token you were sent.').id).toBe('invite-token-error');
    expect(tokenField).toHaveFocus();
  });

  it('blocks short passwords without a request', () => {
    const { container } = renderAcceptInvite();
    fillToken();
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'short' } });
    fireEvent.change(screen.getByLabelText('Confirm'), { target: { value: 'short' } });
    submitForm(container);
    expect(mockAcceptInvite).not.toHaveBeenCalled();
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Password must be at least 12 characters.').id).toBe(
      'invite-password-error'
    );
    expect(password).toHaveFocus();
  });

  it('disables submission and ignores re-submission while pending', async () => {
    mockAcceptInvite.mockImplementation(() => new Promise(() => {}));
    const { container } = renderAcceptInvite();
    fillToken();
    fireEvent.click(screen.getByRole('button', { name: /accept invite/i }));
    const pendingButton = screen.getByRole('button', { name: /redeeming token/i });
    expect(pendingButton).toBeDisabled();
    expect(getForm(container)).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(pendingButton);
    submitForm(container);
    await waitFor(() => {
      expect(mockAcceptInvite).toHaveBeenCalledTimes(1);
    });
  });

  it('re-enables submission after a failed request', async () => {
    mockAcceptInvite.mockRejectedValue(
      new ApiClientError(400, 'Bad Request', 'This invite is invalid, expired, or already used.')
    );
    renderAcceptInvite();
    fillToken();
    fireEvent.click(screen.getByRole('button', { name: /accept invite/i }));
    await screen.findByRole('alert');
    const button = screen.getByRole('button', { name: /accept invite/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    const secondAlert = await screen.findByRole('alert');
    expect(secondAlert).toBeInTheDocument();
    expect(mockAcceptInvite).toHaveBeenCalledTimes(2);
  });

  it('announces the success state and moves focus to its heading', async () => {
    mockAcceptInvite.mockResolvedValue(ACCEPT_RESPONSE);
    renderAcceptInvite();
    fillToken();
    fireEvent.click(screen.getByRole('button', { name: /accept invite/i }));
    const heading = await screen.findByRole('heading', { name: 'Invite accepted' });
    // Focus is set in an effect after the success card commits; wait for it.
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByRole('status')).toHaveTextContent('Welcome to NVLabs.');
    expect(mockAcceptInvite).toHaveBeenCalledTimes(1);
  });

  it('sends the same request payload as before, with the same normalization', async () => {
    mockAcceptInvite.mockResolvedValue(ACCEPT_RESPONSE);
    renderAcceptInvite();
    fillToken(` ${TOKEN} `);
    fireEvent.change(screen.getByLabelText('First Name'), { target: { value: ' Ada ' } });
    fireEvent.change(screen.getByLabelText('Last Name'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: VALID_PASSWORD } });
    fireEvent.change(screen.getByLabelText('Confirm'), { target: { value: VALID_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: /accept invite/i }));
    await screen.findByRole('heading', { name: 'Invite accepted' });
    expect(mockAcceptInvite).toHaveBeenCalledTimes(1);
    expect(mockAcceptInvite).toHaveBeenCalledWith({
      token: TOKEN,
      password: VALID_PASSWORD,
      first_name: 'Ada',
    });
  });

  it('submits a valid form through normal form semantics', async () => {
    mockAcceptInvite.mockResolvedValue(ACCEPT_RESPONSE);
    const { container } = renderAcceptInvite();
    fillToken();
    submitForm(container);
    const heading = await screen.findByRole('heading', { name: 'Invite accepted' });
    expect(heading).toBeInTheDocument();
    expect(mockAcceptInvite).toHaveBeenCalledTimes(1);
    expect(mockAcceptInvite).toHaveBeenCalledWith({ token: TOKEN });
  });
});
