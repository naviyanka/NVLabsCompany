/**
 * Runtime configuration and the active-company selection.
 *
 * A session cookie is bound to exactly one company, so the company the
 * dashboard shows is whatever the server said it was in `GET /auth/me`. This
 * module stores that answer so a page reload renders the right tenant before
 * `/me` comes back. It is convenience, not a credential: putting another
 * company's UUID in here gets a 403 from the API, because only the session
 * cookie decides what the caller may read.
 */

/** The company the demo seed creates. Also the id the mock Express API serves. */
export const SEED_COMPANY_ID = '00000000-0000-4000-8000-000000000001';

/**
 * Whether the API is enforcing authentication.
 *
 * Mirrors the backend's `AUTH_ENABLED`. When it is off, the API trusts the
 * `X-Company-Id` header, and the dashboard has to send that header instead of
 * relying on a session cookie. Default is on, so a missing env var never
 * silently produces a client that skips auth.
 */
export const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED !== 'false';

const ACTIVE_COMPANY_KEY = 'nvlabs_active_company_id';

/** Read the active company id, falling back to the seed company. */
export function getActiveCompanyId(): string {
  try {
    return window.localStorage.getItem(ACTIVE_COMPANY_KEY) || SEED_COMPANY_ID;
  } catch {
    // Private browsing modes can throw on any localStorage access.
    return SEED_COMPANY_ID;
  }
}

/** Remember which company the current session belongs to. */
export function setActiveCompanyId(companyId: string): void {
  try {
    window.localStorage.setItem(ACTIVE_COMPANY_KEY, companyId);
  } catch {
    // Losing the hint only costs one render of the wrong tenant name.
  }
}

/** Forget the active company, so the next boot starts from the seed default. */
export function clearActiveCompanyId(): void {
  try {
    window.localStorage.removeItem(ACTIVE_COMPANY_KEY);
  } catch {
    // Nothing to do; the value is a hint, not state we depend on.
  }
}
