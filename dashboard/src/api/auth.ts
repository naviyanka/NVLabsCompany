import { apiClient } from './client';

const BASE = '/api/v1/auth';

export interface UserSummary {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string;
  avatar_url: string | null;
  timezone: string;
  status: string;
  two_factor_enabled: boolean;
  is_superuser: boolean;
}

export interface MembershipSummary {
  company_id: string;
  company_name: string;
  role: string;
  is_current: boolean;
}

/** Identity as the server sees it. `kind` is `user` for a human, `api_key` for a service token. */
export interface MeResponse {
  kind: string;
  role: string;
  company_id: string;
  company_name: string;
  display_name: string;
  user: UserSummary | null;
  memberships: MembershipSummary[];
}

export interface SessionSummary {
  id: string;
  company_id: string;
  browser: string;
  ip_address: string;
  location: string | null;
  is_current: boolean;
  last_active_at: string;
  expires_at: string | null;
  created_at: string;
}

export interface InviteSummary {
  id: string;
  company_id: string;
  email: string;
  role: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

/** The invite token is returned exactly once — only its hash is stored. */
export interface InviteCreateResponse {
  invite: InviteSummary;
  token: string;
}

export interface InviteAcceptResponse {
  company_id: string;
  role: string;
  account_created: boolean;
  message: string;
}

export interface InviteAcceptRequest {
  token: string;
  password?: string;
  first_name?: string;
  last_name?: string;
}

export interface SetupRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  company_name?: string;
}

export const authApi = {
  /** Who am I? Answers 401 when there is no live session, which is not an error. */
  me(): Promise<MeResponse> {
    return apiClient.get<MeResponse>(`${BASE}/me`);
  },

  login(email: string, password: string): Promise<MeResponse> {
    return apiClient.post<MeResponse>(`${BASE}/login`, { email, password });
  },

  logout(): Promise<{ success: boolean }> {
    return apiClient.post<{ success: boolean }>(`${BASE}/logout`);
  },

  /** Re-issue the readable CSRF cookie when the page has lost it but the session survives. */
  csrf(): Promise<{ csrf_token: string }> {
    return apiClient.get<{ csrf_token: string }>(`${BASE}/csrf`);
  },

  listSessions(): Promise<SessionSummary[]> {
    return apiClient.get<SessionSummary[]>(`${BASE}/sessions`);
  },

  revokeSession(sessionId: string): Promise<{ revoked: boolean }> {
    return apiClient.delete<{ revoked: boolean }>(`${BASE}/sessions/${sessionId}`);
  },

  revokeOtherSessions(): Promise<{ revoked_count: number }> {
    return apiClient.post<{ revoked_count: number }>(`${BASE}/sessions/revoke-others`);
  },

  listCompanies(): Promise<MembershipSummary[]> {
    return apiClient.get<MembershipSummary[]>(`${BASE}/companies`);
  },

  /** Open a session in another company. The previous session is revoked server-side. */
  switchCompany(companyId: string): Promise<MeResponse> {
    return apiClient.post<MeResponse>(`${BASE}/switch-company`, { company_id: companyId });
  },

  changePassword(
    currentPassword: string,
    newPassword: string
  ): Promise<{ success: boolean; other_sessions_revoked: number }> {
    return apiClient.post(`${BASE}/change-password`, {
      current_password: currentPassword,
      new_password: newPassword,
    });
  },

  listInvites(): Promise<InviteSummary[]> {
    return apiClient.get<InviteSummary[]>(`${BASE}/invites`);
  },

  createInvite(email: string, role: string, expiresInHours?: number): Promise<InviteCreateResponse> {
    return apiClient.post<InviteCreateResponse>(`${BASE}/invites`, {
      email,
      role,
      ...(expiresInHours ? { expires_in_hours: expiresInHours } : {}),
    });
  },

  revokeInvite(inviteId: string): Promise<{ revoked: boolean }> {
    return apiClient.delete<{ revoked: boolean }>(`${BASE}/invites/${inviteId}`);
  },

  acceptInvite(body: InviteAcceptRequest): Promise<InviteAcceptResponse> {
    return apiClient.post<InviteAcceptResponse>(`${BASE}/invites/accept`, body);
  },

  /** True only while the deployment has no users at all. */
  setupRequired(): Promise<{ setup_required: boolean }> {
    return apiClient.get<{ setup_required: boolean }>(`${BASE}/setup-required`);
  },

  /** Create the first administrator and sign them in. Works exactly once. */
  setup(body: SetupRequest): Promise<MeResponse> {
    return apiClient.post<MeResponse>(`${BASE}/setup`, body);
  },
};
