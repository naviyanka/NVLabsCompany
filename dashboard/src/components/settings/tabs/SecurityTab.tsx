import { useState } from 'react';
import { Shield, Save, KeyRound } from 'lucide-react';
import { Button } from '@/components/common/Button';

interface SecurityTabProps {
  onSaveToast: (msg?: string) => void;
}

export function SecurityTab({ onSaveToast }: SecurityTabProps) {
  const [twoFactorAuth, setTwoFactorAuth] = useState(true);
  const [sessionTimeout, setSessionTimeout] = useState('24');
  const [requireSaml, setRequireSaml] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveToast('Security settings & authentication rules updated');
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Shield size={18} className="text-[#FFB020]" />
            Security & Authentication Control
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Manage two-factor authentication, SSO policies, and operator session timeouts.
          </p>
        </div>
        <Button variant="primary" size="sm" type="submit" icon={<Save size={14} />}>
          Save Security
        </Button>
      </div>

      <div className="space-y-5">
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium text-white">Two-Factor Authentication (2FA)</div>
              <div className="text-[11px] text-gray-400">Require TOTP authenticator app code on login</div>
            </div>
            <input
              type="checkbox"
              checked={twoFactorAuth}
              onChange={(e) => setTwoFactorAuth(e.target.checked)}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
            <div>
              <div className="font-medium text-white">Enforce SAML 2.0 Single Sign-On (SSO)</div>
              <div className="text-[11px] text-gray-400">Restrict team sign-ins to Okta or Azure AD</div>
            </div>
            <input
              type="checkbox"
              checked={requireSaml}
              onChange={(e) => setRequireSaml(e.target.checked)}
              className="w-4 h-4 accent-[#FFB020] cursor-pointer"
            />
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Operator Session Timeout (Hours)
          </label>
          <select
            value={sessionTimeout}
            onChange={(e) => setSessionTimeout(e.target.value)}
            className="w-full max-w-sm px-3 py-2 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
          >
            <option value="4">4 Hours (Strict Security)</option>
            <option value="12">12 Hours</option>
            <option value="24">24 Hours (Standard)</option>
            <option value="168">7 Days</option>
          </select>
        </div>

        <div className="pt-4 border-t border-white/[0.08] space-y-3">
          <h3 className="font-medium text-white flex items-center gap-1.5">
            <KeyRound size={15} className="text-[#FFB020]" /> Change Password
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg">
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Current Password"
              className="px-3 py-2 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New Password (min 12 chars)"
              className="px-3 py-2 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>
      </div>
    </form>
  );
}
