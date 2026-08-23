import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Loader2, Ticket, User } from 'lucide-react';
import { authApi } from '@/api/auth';
import { ApiClientError } from '@/api/client';
import { useAuth } from '@/contexts/AuthContext';

const INPUT_CLASS =
  'w-full bg-[#141416] border border-white/[0.12] rounded-[6px] px-3 py-2.5 text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors';

const LABEL_CLASS = 'block text-xs font-mono text-[#A8A8AB] uppercase mb-1.5';

/** Matches the backend's `PASSWORD_MIN_LENGTH` default; the server re-checks it. */
const MIN_PASSWORD_LENGTH = 12;

export function AcceptInvite() {
  const { status } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [token, setToken] = useState(searchParams.get('token') ?? '');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [accepted, setAccepted] = useState<{ message: string; accountCreated: boolean } | null>(
    null
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.title = 'Redeem invite · NEXUS Mission Control';
  }, []);

  // A fresh install has no administrator to have sent an invite.
  if (status === 'setup-required') {
    return <Navigate to="/setup" replace />;
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');

    if (!token.trim()) {
      setError('Paste the invite token you were sent.');
      return;
    }
    if (password && password !== confirmPassword) {
      setError('The two passwords do not match.');
      return;
    }
    if (password && password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      // Password and names are only used when the invite creates a new account.
      // An existing user joining a second company keeps the credentials they have.
      const result = await authApi.acceptInvite({
        token: token.trim(),
        ...(password ? { password } : {}),
        ...(firstName.trim() ? { first_name: firstName.trim() } : {}),
        ...(lastName.trim() ? { last_name: lastName.trim() } : {}),
      });
      setAccepted({ message: result.message, accountCreated: result.account_created });
      setPassword('');
      setConfirmPassword('');
    } catch (err) {
      // Invalid, expired, and already-used tokens share one message on purpose,
      // so this form cannot be used to probe which tokens exist.
      setError(
        err instanceof ApiClientError
          ? err.detail
          : 'Cannot reach the control plane. Check that the API is running.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (accepted) {
    return (
      <div className="min-h-screen bg-[#0A0A0B] flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm text-center">
          <div className="inline-flex items-center justify-center w-11 h-11 rounded-[8px] bg-[#22C55E]/12 border border-[#22C55E]/25 mb-4">
            <CheckCircle2 className="w-5 h-5 text-[#22C55E]" />
          </div>
          <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
            Invite accepted
          </h1>
          <p className="text-xs font-mono text-[#A8A8AB] mt-2 leading-relaxed">
            {accepted.message}
          </p>
          <button
            type="button"
            onClick={() => navigate('/login', { replace: true })}
            className="mt-6 w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#FFB020] hover:bg-[#FFC24D] text-[#0A0A0B] text-sm font-medium rounded-[6px] transition-colors cursor-pointer"
          >
            Continue to sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0B] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="mb-7 text-center">
          <div className="inline-flex items-center justify-center w-11 h-11 rounded-[8px] bg-[#FFB020]/12 border border-[#FFB020]/25 mb-4">
            <Ticket className="w-5 h-5 text-[#FFB020]" />
          </div>
          <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
            Redeem your invite
          </h1>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1.5 leading-relaxed">
            Tokens are single-use and expire. Set a password if this is your
            first company here.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-6 space-y-4"
        >
          {error && (
            <div className="flex items-start gap-2 p-3 bg-[#EF4444]/10 border border-[#EF4444]/25 rounded-[6px]">
              <AlertTriangle className="w-3.5 h-3.5 text-[#EF4444] mt-0.5 shrink-0" />
              <p className="text-xs text-[#F2F1EE] leading-relaxed">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="invite-token" className={LABEL_CLASS}>
              Invite Token
            </label>
            <textarea
              id="invite-token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste the token from your invite"
              rows={2}
              required
              className={`${INPUT_CLASS} font-mono text-xs resize-none`}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="invite-first" className={LABEL_CLASS}>
                First Name
              </label>
              <div className="relative">
                <User className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  id="invite-first"
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
              <label htmlFor="invite-last" className={LABEL_CLASS}>
                Last Name
              </label>
              <input
                id="invite-last"
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Lovelace"
                autoComplete="family-name"
                className={INPUT_CLASS}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="invite-password" className={LABEL_CLASS}>
                Password
              </label>
              <input
                id="invite-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={`${MIN_PASSWORD_LENGTH}+ characters`}
                autoComplete="new-password"
                className={INPUT_CLASS}
              />
            </div>
            <div>
              <label htmlFor="invite-confirm" className={LABEL_CLASS}>
                Confirm
              </label>
              <input
                id="invite-confirm"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                autoComplete="new-password"
                className={INPUT_CLASS}
              />
            </div>
          </div>

          <p className="text-[10px] font-mono text-[#6B6B6E] leading-relaxed">
            Already have an account? Leave the password blank — accepting only
            adds the new company to it.
          </p>

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#FFB020] hover:bg-[#FFC24D] disabled:opacity-50 disabled:cursor-not-allowed text-[#0A0A0B] text-sm font-medium rounded-[6px] transition-colors cursor-pointer"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Redeeming token...
              </>
            ) : (
              <>
                <Ticket className="w-4 h-4" />
                Accept invite
              </>
            )}
          </button>
        </form>

        <p className="text-[11px] font-mono text-[#6B6B6E] text-center mt-6">
          <Link to="/login" className="text-[#FFB020] hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
