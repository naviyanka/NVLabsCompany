import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, Loader2, Lock, LogIn, Mail } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { ApiClientError } from '@/api/client';

const INPUT_CLASS =
  'w-full bg-[#141416] border border-white/[0.12] rounded-[6px] pl-9 pr-3 py-2.5 text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface LocationState {
  from?: string;
}

interface FieldErrors {
  email?: string;
  password?: string;
}

export function Login() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = 'Sign in · NEXUS Mission Control';
  }, []);

  // A server error belongs to the form, not one field (unknown email and wrong
  // password look identical), so move focus to it instead of leaving focus on
  // the submit button. tabIndex=-1 keeps it out of tab order.
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  // A fresh install has no account to sign in with; send the operator to setup.
  if (status === 'setup-required') {
    return <Navigate to="/setup" replace />;
  }

  if (status === 'authenticated') {
    const target = (location.state as LocationState | null)?.from || '/';
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setError('');

    const nextFieldErrors: FieldErrors = {};
    if (!email.trim()) {
      nextFieldErrors.email = 'Enter your operator email.';
    } else if (!EMAIL_PATTERN.test(email.trim())) {
      nextFieldErrors.email = 'Enter a valid email address.';
    }
    if (!password) {
      nextFieldErrors.password = 'Enter your password.';
    }
    if (nextFieldErrors.email || nextFieldErrors.password) {
      setFieldErrors(nextFieldErrors);
      if (nextFieldErrors.email) emailRef.current?.focus();
      else passwordRef.current?.focus();
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate((location.state as LocationState | null)?.from || '/', { replace: true });
    } catch (err) {
      // The API answers an unknown email and a wrong password identically, so
      // whatever it says is safe to show verbatim.
      setError(
        err instanceof ApiClientError
          ? err.detail
          : 'Cannot reach the control plane. Check that the API is running.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0B] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-11 h-11 rounded-[8px] bg-[#FFB020]/12 border border-[#FFB020]/25 mb-4">
            <Lock aria-hidden="true" className="w-5 h-5 text-[#FFB020]" />
          </div>
          <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
            NEXUS Mission Control
          </h1>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1.5">
            Authenticate to reach the autonomous workforce
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          aria-busy={submitting}
          className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-6 space-y-4 shadow-xl"
        >
          {error && (
            <div
              ref={errorRef}
              id="login-error"
              role="alert"
              tabIndex={-1}
              className="flex items-start gap-2 p-3 bg-[#EF4444]/10 border border-[#EF4444]/25 rounded-[6px] focus:outline-none"
            >
              <AlertTriangle
                aria-hidden="true"
                className="w-3.5 h-3.5 text-[#EF4444] mt-0.5 shrink-0"
              />
              <p className="text-xs text-[#F2F1EE] leading-relaxed">{error}</p>
            </div>
          )}

          <div>
            <label
              htmlFor="login-email"
              className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1.5"
            >
              Operator Email
            </label>
            <div className="relative">
              <Mail
                aria-hidden="true"
                className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2"
              />
              <input
                id="login-email"
                ref={emailRef}
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldErrors.email) {
                    setFieldErrors((prev) => ({ ...prev, email: undefined }));
                  }
                }}
                placeholder="you@company.com"
                autoComplete="username"
                autoFocus
                required
                aria-invalid={fieldErrors.email ? true : undefined}
                aria-describedby={fieldErrors.email ? 'login-email-error' : undefined}
                className={INPUT_CLASS}
              />
            </div>
            {fieldErrors.email && (
              <p
                id="login-email-error"
                role="alert"
                className="mt-1.5 text-[11px] leading-relaxed text-[#EF4444]"
              >
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="login-password"
              className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1.5"
            >
              Password
            </label>
            <div className="relative">
              <Lock
                aria-hidden="true"
                className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2"
              />
              <input
                id="login-password"
                ref={passwordRef}
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (fieldErrors.password) {
                    setFieldErrors((prev) => ({ ...prev, password: undefined }));
                  }
                }}
                placeholder="••••••••••••"
                autoComplete="current-password"
                required
                aria-invalid={fieldErrors.password ? true : undefined}
                aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
                className={INPUT_CLASS}
              />
            </div>
            {fieldErrors.password && (
              <p
                id="login-password-error"
                role="alert"
                className="mt-1.5 text-[11px] leading-relaxed text-[#EF4444]"
              >
                {fieldErrors.password}
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#FFB020] hover:bg-[#FFC24D] disabled:opacity-50 disabled:cursor-not-allowed text-[#0A0A0B] text-sm font-medium rounded-[6px] transition-colors cursor-pointer"
          >
            {submitting ? (
              <>
                <Loader2 aria-hidden="true" className="w-4 h-4 animate-spin" />
                Opening session...
              </>
            ) : (
              <>
                <LogIn aria-hidden="true" className="w-4 h-4" />
                Sign in
              </>
            )}
          </button>

          <p className="text-[11px] font-mono text-[#6B6B6E] text-center leading-relaxed pt-1">
            Been invited?{' '}
            <Link to="/invite" className="text-[#FFB020] hover:underline">
              Redeem an invite token
            </Link>
          </p>
        </form>

        <p className="text-[10px] font-mono text-[#6B6B6E] text-center mt-6 leading-relaxed">
          Accounts are created by invitation. Locked out? An administrator can
          issue a new invite, or the server operator can run{' '}
          <span className="text-[#A8A8AB]">python -m nexus.auth.bootstrap</span>.
        </p>
      </div>
    </div>
  );
}
