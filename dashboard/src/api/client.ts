import { AUTH_ENABLED, SEED_COMPANY_ID, getActiveCompanyId } from '@/config';

export class ApiClientError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly detail: string
  ) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiClientError';
  }
}

/** @deprecated Build paths from `getActiveCompanyId()` instead. Kept for legacy call sites. */
export const DEFAULT_COMPANY_ID = SEED_COMPANY_ID;

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const CSRF_COOKIE_NAME = 'nv_csrf';
const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const entry of document.cookie.split('; ')) {
    if (entry.startsWith(prefix)) return decodeURIComponent(entry.slice(prefix.length));
  }
  return null;
}

/**
 * The session cookie is httpOnly, so JavaScript cannot read it and cannot be
 * tricked into leaking it. The readable CSRF cookie is echoed back in a header
 * — a cross-site form can send the cookie but cannot read it to set the header.
 */
function defaultHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };

  if (MUTATING_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE_NAME);
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }

  // With AUTH_ENABLED=false the API trusts this header to pick a tenant. It is a
  // development convenience and must never be sent to an authenticated backend,
  // where the session alone decides scope.
  if (!AUTH_ENABLED) headers['X-Company-Id'] = getActiveCompanyId();

  return headers;
}

/** For SSE and hand-rolled `fetch` calls that bypass `apiClient`. */
export function legacyCompanyHeaders(): Record<string, string> {
  return AUTH_ENABLED ? {} : { 'X-Company-Id': getActiveCompanyId() };
}

/**
 * Compatibility shim for paths that still carry the demo-seed company UUID.
 *
 * Under real auth the server rejects a company you are not a member of, so a
 * hardcoded tenant id is a 403 waiting to happen. Rewriting it here fixes every
 * such call site at once. New code should build paths from
 * `getActiveCompanyId()` and never rely on this.
 */
function resolveCompanyPath(path: string): string {
  const activeCompanyId = getActiveCompanyId();
  if (activeCompanyId === SEED_COMPANY_ID || !path.includes(SEED_COMPANY_ID)) return path;
  return path.split(SEED_COMPANY_ID).join(activeCompanyId);
}

/**
 * Asking "am I signed in?" must be allowed to answer no. Treating the auth
 * endpoints' own 401 as a session loss would drop identity during boot and
 * bounce the operator between login and guard forever.
 */
function isAuthProbe(path: string): boolean {
  return path.includes('/api/v1/auth/');
}

async function handleResponse<T>(response: Response, path: string): Promise<T> {
  if (response.status === 401 && !isAuthProbe(path)) {
    unauthorizedHandler?.();
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json() as { detail?: string; message?: string };
      if (body.detail) {
        detail = body.detail;
      } else if (body.message) {
        detail = body.message;
      }
    } catch {
      // Use statusText as fallback
    }
    throw new ApiClientError(response.status, response.statusText, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function buildUrl(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
  let urlStr = path;
  if (params && Object.keys(params).length > 0) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        searchParams.set(key, String(value));
      }
    });
    const qs = searchParams.toString();
    if (qs) {
      urlStr = `${path}${path.includes('?') ? '&' : '?'}${qs}`;
    }
  }
  return BASE_URL ? new URL(urlStr, BASE_URL).toString() : urlStr;
}

interface RequestOptions {
  params?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const resolvedPath = resolveCompanyPath(path);
  const response = await fetch(buildUrl(resolvedPath, options.params), {
    method,
    headers: defaultHeaders(method),
    // Sessions live in cookies, so they must ride along even cross-origin.
    credentials: 'include',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  return handleResponse<T>(response, resolvedPath);
}

export const apiClient = {
  get<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
    return request<T>('GET', path, { params });
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('POST', path, { body });
  },

  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('PUT', path, { body });
  },

  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>('PATCH', path, { body });
  },

  delete<T>(path: string): Promise<T> {
    return request<T>('DELETE', path);
  },
};

/**
 * Normalize a list response from the API.
 *
 * The mock Express server wraps arrays in `{ items: T[] }` while the real
 * FastAPI backend returns plain arrays. This helper accepts either shape and
 * always returns the items array, making frontend code backend-agnostic.
 */
export function unwrapItems<T>(data: T[] | { items: T[] } | null | undefined): T[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray((data as { items: T[] }).items)) return (data as { items: T[] }).items;
  return [];
}
