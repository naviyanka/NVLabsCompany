import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { authApi, type MeResponse } from '@/api/auth';
import { ApiClientError, setUnauthorizedHandler } from '@/api/client';
import { clearActiveCompanyId, setActiveCompanyId } from '@/config';

/**
 * `setup-required` is its own state rather than a flavour of `anonymous`: a
 * fresh install has no account that could possibly sign in, so sending the
 * operator to the login form would be a dead end.
 */
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'setup-required';

interface AuthContextValue {
  status: AuthStatus;
  me: MeResponse | null;
  role: string;
  companyId: string | null;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<MeResponse>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  adoptIdentity: (me: MeResponse) => void;
  switchCompany: (companyId: string) => Promise<MeResponse>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [me, setMe] = useState<MeResponse | null>(null);

  const adopt = useCallback((next: MeResponse) => {
    setMe(next);
    setActiveCompanyId(next.company_id);
    setStatus('authenticated');
  }, []);

  const forget = useCallback(() => {
    setMe(null);
    clearActiveCompanyId();
    setStatus('anonymous');
  }, []);

  /**
   * Decide the initial state: signed in, signed out, or never set up.
   *
   * `/me` answering 401 is the only case worth a second question — anything
   * else (network failure, server down) is reported as anonymous rather than
   * guessed at, because a fresh install is not the likely explanation.
   */
  const resolve = useCallback(async () => {
    try {
      adopt(await authApi.me());
      return;
    } catch (error) {
      if (!(error instanceof ApiClientError) || error.status !== 401) {
        setMe(null);
        setStatus('anonymous');
        return;
      }
    }

    try {
      const { setup_required } = await authApi.setupRequired();
      setStatus(setup_required ? 'setup-required' : 'anonymous');
    } catch {
      setStatus('anonymous');
    }
  }, [adopt]);

  // Boot once. A remount must not re-run identity resolution and flash the app
  // back to its loading state.
  const resolveRef = useRef(false);
  useEffect(() => {
    if (resolveRef.current) return;
    resolveRef.current = true;
    void resolve();
  }, [resolve]);

  // Any request that comes back unauthenticated means the session died
  // mid-visit; drop identity so the guard redirects instead of leaving the app
  // rendering against an API that now refuses everything.
  useEffect(() => {
    setUnauthorizedHandler(forget);
    return () => setUnauthorizedHandler(null);
  }, [forget]);

  const login = useCallback(
    async (email: string, password: string) => {
      const next = await authApi.login(email, password);
      adopt(next);
      return next;
    },
    [adopt]
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // The server has either revoked the session or never had one. Either way
      // this browser is done with it.
      forget();
    }
  }, [forget]);

  const refresh = useCallback(async () => {
    try {
      adopt(await authApi.me());
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 401) {
        forget();
        return;
      }
      throw error;
    }
  }, [adopt, forget]);

  const switchCompany = useCallback(
    async (companyId: string) => {
      const next = await authApi.switchCompany(companyId);
      adopt(next);
      return next;
    },
    [adopt]
  );

  return (
    <AuthContext.Provider
      value={{
        status,
        me,
        role: me?.role ?? '',
        companyId: me?.company_id ?? null,
        isAdmin: me?.role === 'admin',
        login,
        logout,
        refresh,
        adoptIdentity: adopt,
        switchCompany,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return value;
}
