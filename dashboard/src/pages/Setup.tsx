import { useEffect, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { AlertTriangle, Building2, Loader2, Mail, ShieldCheck, User } from 'lucide-react';
import { authApi } from '@/api/auth';
import { ApiClientError } from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';

const INPUT_CLASS =
  'w-full bg-[#141416] border border-white/[0.12] rounded-[6px] px-3 py-2.5 text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors';

const LABEL_CLASS = 'block text-xs font-mono text-[#A8A8AB] uppercase mb-1.5';

/**
 * Mirrors the backend's `PASSWORD_MIN_LENGTH` default. Checking here only saves
 * a round trip — the server validates the password again and is the authority.
 */
const MIN_PASSWORD_LENGTH = 12;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface FieldErrors {
  email?: string;
  password?: string;
  confirm?: string;
}

export function Setup() {
  const { status, adoptIdentity } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [companyName, setCompanyName] = useState('NVLabs');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [serverError, setServerError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = 'First-run setup · NEXUS Mission Control';
  }, []);

  // Server errors belong to the form as a whole; move focus so keyboard and
  // screen reader users land on the explanation. tabIndex=-1 keeps it out of
  // tab order.
  useEffect(() => {
    if (serverError) errorRef.current?.focus();
  }, [serverError]);

  if (status === 'authenticated') {
    return <Navigate to="/" replace />;
  }

  // Setup closes the moment the first account exists. Anyone arriving late gets
  // the login form rather than a form the server would refuse.
  if (status === 'anonymous') {
    return <Navigate to="/login" replace />;
  }

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0A0A0B]">
        <div className="w-8 h-8 border-2 border-[#FFB020] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setServerError('');

    const nextFieldErrors: FieldErrors = {};
    if (!email.trim()) {
      nextFieldErrors.email = 'Enter your administrator email.';
    } else if (!EMAIL_PATTERN.test(email.trim())) {
      nextFieldErrors.email = 'Enter a valid email address.';
    }
    if (password !== confirmPassword) {
      nextFieldErrors.confirm = 'The two passwords do not match.';
    } else if (password.length < MIN_PASSWORD_LENGTH) {
      nextFieldErrors.password = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    if (nextFieldErrors.email || nextFieldErrors.password || nextFieldErrors.confirm) {
      setFieldErrors(nextFieldErrors);
      if (nextFieldErrors.email) emailRef.current?.focus();
      else if (nextFieldErrors.password) passwordRef.current?.focus();
      else confirmRef.current?.focus();
      return;
    }

    setFieldErrors({});
    setSubmitting(true);
    try {
      // Setup signs the new administrator in as it creates them, so the response
      // is a full identity and there is no second login step.
      const me = await authApi.setup({
        email: email.trim(),
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        company_name: companyName.trim() || 'NVLabs',
      });
      adoptIdentity(me);
      navigate('/', { replace: true });
    } catch (err) {
      setServerError(
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
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="mb-7 text-center">
          <div className="inline-flex items-center justify-center w-11 h-11 rounded-[8px] bg-[#22C55E]/12 border border-[#22C55E]/25 mb-4">
            <ShieldCheck aria-hidden="true" className="w-5 h-5 text-[#22C55E]" />
          </div>
          <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
            Claim this deployment
          </h1>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1.5 leading-relaxed">
            No accounts exist yet. Create the first administrator — this form
            works exactly once.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          aria-busy={submitting}
          className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-6 space-y-4"
        >
          {serverError && (
            <div
              ref={errorRef}
              id="setup-error"
              role="alert"
              tabIndex={-1}
              className="flex items-start gap-2 p-3 bg-[#EF4444]/10 border border-[#EF4444]/25 rounded-[6px] focus:outline-none"
            >
              <AlertTriangle
                aria-hidden="true"
                className="w-3.5 h-3.5 text-[#EF4444] mt-0.5 shrink-0"
              />
              <p className="text-xs text-[#F2F1EE] leading-relaxed">{serverError}</p>
            </div>
          )}

          <div>
            <label htmlFor="setup-email" className={LABEL_CLASS}>
              Administrator Email
            </label>
            <div className="relative">
              <Mail
                aria-hidden="true"
                className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2"
              />
              <input
                id="setup-email"
                ref={emailRef}
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldErrors.email) {
                    setFieldErrors((prev) => ({ ...prev, email: undefined }));
                  }
                }}
                placeholder="admin@nvlabs.dev"
                autoComplete="email"
                autoFocus
                required
                aria-invalid={fieldErrors.email ? true : undefined}
                aria-describedby={fieldErrors.email ? 'setup-email-error' : undefined}
                className={`${INPUT_CLASS} pl-9`}
              />
            </div>
            {fieldErrors.email && (
              <p
                id="setup-email-error"
                role="alert"
                className="mt-1.5 text-[11px] leading-relaxed text-[#EF4444]"
              >
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="setup-first" className={LABEL_CLASS}>
                First Name
              </label>
              <div className="relative">
                <User
                  aria-hidden="true"
                  className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2"
                />
                <input
                  id="setup-first"
                  type="text"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  placeholder="Ada"
                  autoComplete="given-name"
                  className={`${INPUT_CLASS} pl-9`}
                />
              </div>
            </div>
            <div>
              <label htmlFor="setup-last" className={LABEL_CLASS}>
                Last Name
              </label>
              <input
                id="setup-last"
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Lovelace"
                autoComplete="family-name"
                className={INPUT_CLASS}
              />
            </div>
          </div>

          <div>
            <label htmlFor="setup-company" className={LABEL_CLASS}>
              Company Workspace
            </label>
            <div className="relative">
              <Building2
                aria-hidden="true"
                className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2"
              />
              <input
                id="setup-company"
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="NVLabs"
                autoComplete="organization"
                className={`${INPUT_CLASS} pl-9`}
              />
            </div>
            <p className="text-[10px] font-mono text-[#6B6B6E] mt-1.5 leading-relaxed">
              Used only if this install has no company yet; otherwise you join
              the existing one.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="setup-password" className={LABEL_CLASS}>
                Password
              </label>
              <input
                id="setup-password"
                ref={passwordRef}
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (fieldErrors.password) {
                    setFieldErrors((prev) => ({ ...prev, password: undefined }));
                  }
                }}
                placeholder={`${MIN_PASSWORD_LENGTH}+ characters`}
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                required
                aria-invalid={fieldErrors.password ? true : undefined}
                aria-describedby={fieldErrors.password ? 'setup-password-error' : undefined}
                className={INPUT_CLASS}
              />
              {fieldErrors.password && (
                <p
                  id="setup-password-error"
                  role="alert"
                  className="mt-1.5 text-[11px] leading-relaxed text-[#EF4444]"
                >
                  {fieldErrors.password}
                </p>
              )}
            </div>
            <div>
              <label htmlFor="setup-confirm" className={LABEL_CLASS}>
                Confirm
              </label>
              <input
                id="setup-confirm"
                ref={confirmRef}
                type="password"
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(e.target.value);
                  if (fieldErrors.confirm) {
                    setFieldErrors((prev) => ({ ...prev, confirm: undefined }));
                  }
                }}
                placeholder="Repeat password"
                autoComplete="new-password"
                required
                aria-invalid={fieldErrors.confirm ? true : undefined}
                aria-describedby={fieldErrors.confirm ? 'setup-confirm-error' : undefined}
                className={INPUT_CLASS}
              />
              {fieldErrors.confirm && (
                <p
                  id="setup-confirm-error"
                  role="alert"
                  className="mt-1.5 text-[11px] leading-relaxed text-[#EF4444]"
                >
                  {fieldErrors.confirm}
                </p>
              )}
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#FFB020] hover:bg-[#FFC24D] disabled:opacity-50 disabled:cursor-not-allowed text-[#0A0A0B] text-sm font-medium rounded-[6px] transition-colors cursor-pointer"
          >
            {submitting ? (
              <>
                <Loader2 aria-hidden="true" className="w-4 h-4 animate-spin" />
                Creating administrator...
              </>
            ) : (
              <>
                <ShieldCheck aria-hidden="true" className="w-4 h-4" />
                Create administrator &amp; sign in
              </>
            )}
          </button>
        </form>

        <p className="text-[10px] font-mono text-[#6B6B6E] text-center mt-6 leading-relaxed">
          Locked out later? Recover from the server with{' '}
          <span className="text-[#A8A8AB]">python -m nexus.auth.bootstrap</span>.
        </p>
      </div>
    </div>
  );
}
