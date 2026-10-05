import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';

import { Setup } from '../Setup';
import { ApiClientError } from '@/api/client';
import type { MeResponse } from '@/api/auth';

const { mockUseAuth, mockSetup, mockAdoptIdentity } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockSetup: vi.fn(),
  mockAdoptIdentity: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  authApi: {
    setup: mockSetup,
  },
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
  display_name: 'Ada',
  user: null,
  memberships: [],
};

const VALID_PASSWORD = 'orbital-tangent-9';

function renderSetup() {
  return render(
    <MemoryRouter initialEntries={['/setup']}>
      <Routes>
        <Route path="/setup" element={<Setup />} />
        <Route path="/" element={<div>mission control</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function getForm(container: HTMLElement): HTMLFormElement {
  const form = container.querySelector('form');
  if (!form) throw new Error('setup form not rendered');
  return form;
}

function submitForm(container: HTMLElement) {
  // Dispatched directly so jsdom's native constraint validation does not mask
  // the page's own validation layer.
  fireEvent(getForm(container), new Event('submit', { bubbles: true, cancelable: true }));
}

function fillSetupForm(
  overrides: Partial<{
    email: string;
    firstName: string;
    lastName: string;
    companyName: string;
    password: string;
    confirmPassword: string;
  }> = {}
) {
  const values = {
    email: 'admin@nvlabs.dev',
    firstName: 'Ada',
    lastName: 'Lovelace',
    companyName: 'NVLabs',
    password: VALID_PASSWORD,
    confirmPassword: VALID_PASSWORD,
    ...overrides,
  };
  fireEvent.change(screen.getByLabelText('Administrator Email'), {
    target: { value: values.email },
  });
  fireEvent.change(screen.getByLabelText('First Name'), { target: { value: values.firstName } });
  fireEvent.change(screen.getByLabelText('Last Name'), { target: { value: values.lastName } });
  fireEvent.change(screen.getByLabelText('Company Workspace'), {
    target: { value: values.companyName },
  });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: values.password } });
  fireEvent.change(screen.getByLabelText('Confirm'), {
    target: { value: values.confirmPassword },
  });
}

beforeEach(() => {
  mockUseAuth.mockReset();
  mockSetup.mockReset();
  mockAdoptIdentity.mockReset();
  mockUseAuth.mockReturnValue({
    status: 'setup-required',
    me: null,
    role: '',
    companyId: null,
    isAdmin: false,
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    adoptIdentity: mockAdoptIdentity,
    switchCompany: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Setup accessibility and reliability', () => {
  it('gives every field an accessible label', () => {
    renderSetup();
    expect(screen.getByLabelText('Administrator Email')).toBeInTheDocument();
    expect(screen.getByLabelText('First Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Last Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Company Workspace')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm')).toBeInTheDocument();
  });

  it('uses standard autocomplete values', () => {
    renderSetup();
    expect(screen.getByLabelText('Administrator Email')).toHaveAttribute('autocomplete', 'email');
    expect(screen.getByLabelText('First Name')).toHaveAttribute('autocomplete', 'given-name');
    expect(screen.getByLabelText('Last Name')).toHaveAttribute('autocomplete', 'family-name');
    expect(screen.getByLabelText('Company Workspace')).toHaveAttribute(
      'autocomplete',
      'organization'
    );
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
    expect(screen.getByLabelText('Confirm')).toHaveAttribute('autocomplete', 'new-password');
  });

  it('marks required fields and rejects an invalid email without a request', () => {
    const { container } = renderSetup();
    expect(screen.getByLabelText('Administrator Email')).toBeRequired();
    expect(screen.getByLabelText('Password')).toBeRequired();
    expect(screen.getByLabelText('Confirm')).toBeRequired();
    fillSetupForm({ email: 'not-an-email' });
    submitForm(container);
    expect(mockSetup).not.toHaveBeenCalled();
    const email = screen.getByLabelText('Administrator Email');
    expect(email).toHaveAttribute('aria-invalid', 'true');
    expect(email).toHaveAttribute('aria-describedby', 'setup-email-error');
    expect(screen.getByText('Enter a valid email address.').id).toBe('setup-email-error');
    expect(email).toHaveFocus();
  });

  it('reports a password/confirmation mismatch on the confirm field', () => {
    const { container } = renderSetup();
    fillSetupForm({ confirmPassword: 'a-different-password' });
    submitForm(container);
    expect(mockSetup).not.toHaveBeenCalled();
    const confirm = screen.getByLabelText('Confirm');
    expect(confirm).toHaveAttribute('aria-invalid', 'true');
    expect(confirm).toHaveAttribute('aria-describedby', 'setup-confirm-error');
    expect(screen.getByText('The two passwords do not match.').id).toBe('setup-confirm-error');
    expect(confirm).toHaveFocus();
  });

  it('blocks short passwords without a request', () => {
    const { container } = renderSetup();
    fillSetupForm({ password: 'short', confirmPassword: 'short' });
    submitForm(container);
    expect(mockSetup).not.toHaveBeenCalled();
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Password must be at least 12 characters.').id).toBe(
      'setup-password-error'
    );
    expect(password).toHaveFocus();
  });

  it('disables submission and ignores re-submission while pending', async () => {
    mockSetup.mockImplementation(() => new Promise(() => {}));
    const { container } = renderSetup();
    fillSetupForm();
    fireEvent.click(screen.getByRole('button', { name: /create administrator/i }));
    const pendingButton = screen.getByRole('button', { name: /creating administrator/i });
    expect(pendingButton).toBeDisabled();
    expect(getForm(container)).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(pendingButton);
    submitForm(container);
    await waitFor(() => {
      expect(mockSetup).toHaveBeenCalledTimes(1);
    });
  });

  it('announces a server error via role="alert" and moves focus to it', async () => {
    mockSetup.mockRejectedValue(new ApiClientError(409, 'Conflict', 'Setup already completed.'));
    renderSetup();
    fillSetupForm();
    fireEvent.click(screen.getByRole('button', { name: /create administrator/i }));
    const alert = await screen.findByRole('alert');
    expect(alert.id).toBe('setup-error');
    expect(alert).toHaveTextContent('Setup already completed.');
    // Focus is set in an effect after the error commits; wait for it to land.
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it('adopts the new identity and leaves the page on success', async () => {
    mockSetup.mockResolvedValue(ME_RESPONSE);
    renderSetup();
    fillSetupForm();
    fireEvent.click(screen.getByRole('button', { name: /create administrator/i }));
    expect(await screen.findByText('mission control')).toBeInTheDocument();
    expect(mockAdoptIdentity).toHaveBeenCalledWith(ME_RESPONSE);
    expect(mockSetup).toHaveBeenCalledTimes(1);
  });

  it('sends the same setup payload as before, with the same normalization', async () => {
    mockSetup.mockResolvedValue(ME_RESPONSE);
    renderSetup();
    fillSetupForm({ email: ' admin@nvlabs.dev ', firstName: ' Ada ', lastName: '', companyName: '' });
    fireEvent.click(screen.getByRole('button', { name: /create administrator/i }));
    expect(await screen.findByText('mission control')).toBeInTheDocument();
    expect(mockSetup).toHaveBeenCalledWith({
      email: 'admin@nvlabs.dev',
      password: VALID_PASSWORD,
      first_name: 'Ada',
      last_name: '',
      company_name: 'NVLabs',
    });
  });

  it('submits a valid form through normal form semantics', async () => {
    mockSetup.mockResolvedValue(ME_RESPONSE);
    const { container } = renderSetup();
    fillSetupForm();
    submitForm(container);
    expect(await screen.findByText('mission control')).toBeInTheDocument();
    expect(mockSetup).toHaveBeenCalledTimes(1);
    expect(mockSetup).toHaveBeenCalledWith({
      email: 'admin@nvlabs.dev',
      password: VALID_PASSWORD,
      first_name: 'Ada',
      last_name: 'Lovelace',
      company_name: 'NVLabs',
    });
  });
});
