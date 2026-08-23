import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AlertTriangle, Loader2, Lock, LogIn, Mail } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { ApiClientError } from '@/api/client';

const INPUT_CLASS =
  'w-full bg-[#141416] border border-white/[0.12] rounded-[6px] pl-9 pr-3 py-2.5 text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors';

interface LocationState {
  from?: string;
}

export function Login() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('admin@nvlabs.dev');
  const [password, setPassword] = useState('bypass');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.title = 'Sign in · NEXUS Mission Control';
  }, []);

  // A fresh install has no account to sign in with; send the operator to setup.
  if (status === 'setup-required') {
    return <Navigate to="/setup" replace />;
  }

  if (status === 'authenticated') {
    const target = (location.state as LocationState | null)?.from || '/';
    return <Navigate to={target} replace />;
  }

  const handleBypassSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await login(email.trim() || 'admin@nvlabs.dev', password || 'bypass');
      navigate((location.state as LocationState | null)?.from || '/', { replace: true });
    } catch (err) {
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
            <Lock className="w-5 h-5 text-[#FFB020]" />
          </div>
          <h1 className="text-lg font-display font-medium text-[#F2F1EE] tracking-tight">
            NEXUS Mission Control
          </h1>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1.5">
            Authenticate to reach the autonomous workforce
          </p>

          <div className="mt-3 px-3 py-1.5 bg-[#FFB020]/10 border border-[#FFB020]/30 rounded-md text-[11px] font-mono text-[#FFB020] inline-block">
            ⚡ Dev Mode: Auth Bypass Active
          </div>
        </div>

        <form
          onSubmit={handleBypassSubmit}
          className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-6 space-y-4 shadow-xl"
        >
          {error && (
            <div className="flex items-start gap-2 p-3 bg-[#EF4444]/10 border border-[#EF4444]/25 rounded-[6px]">
              <AlertTriangle className="w-3.5 h-3.5 text-[#EF4444] mt-0.5 shrink-0" />
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
              <Mail className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@nvlabs.dev"
                autoComplete="username"
                autoFocus
                required
                className={INPUT_CLASS}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="login-password"
              className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1.5"
            >
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                autoComplete="current-password"
                required
                className={INPUT_CLASS}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#FFB020] hover:bg-[#FFC24D] disabled:opacity-50 disabled:cursor-not-allowed text-[#0A0A0B] text-sm font-medium rounded-[6px] transition-colors cursor-pointer"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Opening session...
              </>
            ) : (
              <>
                <LogIn className="w-4 h-4" />
                Sign in as Operator (Dev Bypass)
              </>
            )}
          </button>

          <div className="pt-2 border-t border-white/[0.06] text-center">
            <button
              type="button"
              onClick={() => handleBypassSubmit()}
              disabled={submitting}
              className="w-full py-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded text-xs font-mono font-medium transition-colors cursor-pointer"
            >
              ⚡ 1-Click Fast Bypass Sign-In
            </button>
          </div>

          <p className="text-[11px] font-mono text-[#6B6B6E] text-center leading-relaxed pt-1">
            Been invited?{' '}
            <Link to="/invite" className="text-[#FFB020] hover:underline">
              Redeem an invite token
            </Link>
          </p>
        </form>

        <p className="text-[10px] font-mono text-[#6B6B6E] text-center mt-6 leading-relaxed">
          Development bypass mode allows instant access while backend authentication API is under construction.
        </p>
      </div>
    </div>
  );
}
