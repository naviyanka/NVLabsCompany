import { useState, useEffect } from 'react';
import { Shield, Save, KeyRound, Monitor, LogOut } from 'lucide-react';
import { Button } from '@/components/common/Button';
import { ApiClientError } from '@/api/client';
import { authApi, type SessionSummary } from '@/api/auth';

interface SecurityTabProps {
  onSaveToast: (msg?: string) => void;
}

function errorDetail(err: unknown, fallback: string): string {
  return err instanceof ApiClientError ? err.detail : fallback;
}

export function SecurityTab({ onSaveToast }: SecurityTabProps) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [passwordError, setPasswordError] = useState('');

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsError, setSessionsError] = useState('');
  const [revoking, setRevoking] = useState('');

  async function loadSessions() {
    try {
      setSessions(await authApi.listSessions());
      setSessionsError('');
    } catch (err) {
      setSessionsError(errorDetail(err, 'Could not load active sessions'));
    }
  }

  useEffect(() => {
    loadSessions();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setPasswordError('');
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      onSaveToast('Password changed. Your other sessions were signed out.');
      loadSessions();
    } catch (err) {
      setPasswordError(errorDetail(err, 'Could not change password'));
    } finally {
      setSaving(false);
    }
  };

  const handleRevoke = async (sessionId: string) => {
    setRevoking(sessionId);
    try {
      await authApi.revokeSession(sessionId);
      await loadSessions();
    } catch (err) {
      setSessionsError(errorDetail(err, 'Could not revoke that session'));
    } finally {
      setRevoking('');
    }
  };

  const handleRevokeOthers = async () => {
    setRevoking('others');
    try {
      const { revoked_count } = await authApi.revokeOtherSessions();
      onSaveToast(`Signed out ${revoked_count} other session${revoked_count === 1 ? '' : 's'}`);
      await loadSessions();
    } catch (err) {
      setSessionsError(errorDetail(err, 'Could not sign out other sessions'));
    } finally {
      setRevoking('');
    }
  };

  const otherSessionCount = sessions.filter((s) => !s.is_current).length;

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Shield size={18} className="text-[#FFB020]" />
            Security & Authentication Control
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Change your password and review the sessions signed in to your account.
          </p>
        </div>
        <Button variant="primary" size="sm" type="submit" loading={saving} icon={<Save size={14} />}>
          Change Password
        </Button>
      </div>

      <div className="space-y-5">
        <div className="space-y-3">
          <h3 className="font-medium text-white flex items-center gap-1.5">
            <KeyRound size={15} className="text-[#FFB020]" /> Change Password
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg">
            <div>
              <label
                htmlFor="security-current-password"
                className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1"
              >
                Current Password
              </label>
              <input
                id="security-current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                aria-invalid={passwordError ? true : undefined}
                aria-describedby={passwordError ? 'security-password-error' : undefined}
                className="w-full px-3 py-2 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
            </div>
            <div>
              <label
                htmlFor="security-new-password"
                className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1"
              >
                New Password (min 12 chars)
              </label>
              <input
                id="security-new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                aria-invalid={passwordError ? true : undefined}
                aria-describedby={passwordError ? 'security-password-error' : undefined}
                className="w-full px-3 py-2 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>

          {passwordError && (
            <p id="security-password-error" role="alert" className="text-[11px] text-red-400">
              {passwordError}
            </p>
          )}
          <p className="text-[11px] text-gray-400">
            Changing your password signs out every other session on your account.
          </p>
        </div>

        <div className="pt-4 border-t border-white/[0.08] space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-white flex items-center gap-1.5">
              <Monitor size={15} className="text-[#FFB020]" /> Active Sessions
            </h3>
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={handleRevokeOthers}
              loading={revoking === 'others'}
              disabled={otherSessionCount === 0}
              icon={<LogOut size={14} />}
            >
              Sign out all other sessions
            </Button>
          </div>

          {sessionsError && (
            <p role="alert" className="text-[11px] text-red-400">
              {sessionsError}
            </p>
          )}

          <div className="space-y-2">
            {sessions.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-3 p-3 bg-[#101012] border border-white/[0.08] rounded-lg"
              >
                <div className="min-w-0">
                  <div className="font-medium text-white truncate">
                    {s.browser || 'Unknown browser'}
                    {s.is_current && (
                      <span className="ml-2 px-1.5 py-0.5 rounded font-mono text-[10px] uppercase text-[#FFB020] bg-[#FFB020]/10">
                        Current
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-gray-400 truncate">
                    {[s.ip_address, s.location].filter(Boolean).join(' · ')} · last active{' '}
                    {new Date(s.last_active_at).toLocaleString()}
                  </div>
                </div>
                {!s.is_current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    type="button"
                    onClick={() => handleRevoke(s.id)}
                    loading={revoking === s.id}
                  >
                    Revoke
                  </Button>
                )}
              </div>
            ))}
            {!sessionsError && sessions.length === 0 && (
              <p className="text-[11px] text-gray-400">No active sessions found.</p>
            )}
          </div>
        </div>
      </div>
    </form>
  );
}
