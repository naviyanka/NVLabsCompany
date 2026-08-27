import { useState, useEffect } from 'react';
import { Pencil, ChevronDown, Check, X } from 'lucide-react';
import { apiClient, ApiClientError } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import { useAuth } from '@/contexts/AuthContext';

interface ProfileSettingsTabProps {
  onSaveToast: (msg?: string) => void;
}

/** Mirror of the backend `ProfileResponse`. */
interface ProfileResponse {
  id: string;
  company_id: string;
  email: string;
  first_name: string;
  last_name: string;
  title: string;
  avatar_url: string | null;
  phone: string | null;
  timezone: string;
  status: string;
  two_factor_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Exactly the backend's `EDITABLE_FIELDS`. Anything else is dropped by the PUT. */
interface ProfileForm {
  first_name: string;
  last_name: string;
  title: string;
  avatar_url: string;
  phone: string;
  timezone: string;
}

const KNOWN_TIMEZONES = [
  { value: 'Asia/Kolkata', label: '(GMT+05:30) Asia/Kolkata' },
  { value: 'America/New_York', label: '(GMT-05:00) Eastern Time (US & Canada)' },
  { value: 'America/Los_Angeles', label: '(GMT-08:00) Pacific Time (US & Canada)' },
  { value: 'Europe/London', label: '(GMT+00:00) London, Edinburgh, Dublin' },
  { value: 'Europe/Berlin', label: '(GMT+01:00) Berlin, Frankfurt, Paris' },
  { value: 'Asia/Tokyo', label: '(GMT+09:00) Tokyo, Osaka, Sapporo' },
  { value: 'Asia/Singapore', label: '(GMT+08:00) Singapore, Kuala Lumpur' },
  { value: 'UTC', label: '(GMT+00:00) UTC' },
];

const PRESET_AVATARS = [
  'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop&q=80',
];

const FALLBACK_AVATAR = PRESET_AVATARS[0];

function formatMoment(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
}

function formToPayload(form: ProfileForm) {
  return {
    first_name: form.first_name,
    last_name: form.last_name,
    title: form.title,
    avatar_url: form.avatar_url || null,
    phone: form.phone || null,
    timezone: form.timezone,
  };
}

function formFromProfile(profile: ProfileResponse): ProfileForm {
  return {
    first_name: profile.first_name ?? '',
    last_name: profile.last_name ?? '',
    title: profile.title ?? '',
    avatar_url: profile.avatar_url ?? '',
    phone: profile.phone ?? '',
    timezone: profile.timezone ?? 'UTC',
  };
}

export function ProfileSettingsTab({ onSaveToast }: ProfileSettingsTabProps) {
  const { me, role, refresh } = useAuth();

  // Seeded from the signed-in identity so the header shows the right person
  // before the GET lands, then replaced by the real profile row.
  const [form, setForm] = useState<ProfileForm>(() => ({
    first_name: me?.user?.first_name ?? '',
    last_name: me?.user?.last_name ?? '',
    title: me?.user?.title ?? '',
    avatar_url: me?.user?.avatar_url ?? '',
    phone: '',
    timezone: me?.user?.timezone ?? 'UTC',
  }));
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get<ProfileResponse>(
          `/api/v1/companies/${getActiveCompanyId()}/profile`
        );
        if (cancelled) return;
        setProfile(res);
        setForm(formFromProfile(res));
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiClientError ? err.detail : 'Could not load your profile.'
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      const res = await apiClient.put<ProfileResponse>(
        `/api/v1/companies/${getActiveCompanyId()}/profile`,
        formToPayload(form)
      );
      setProfile(res);
      setForm(formFromProfile(res));
      await refresh();
      onSaveToast('Profile saved');
    } catch (err) {
      setSaveError(
        err instanceof ApiClientError ? err.detail : 'Could not save your profile.'
      );
    } finally {
      setIsSaving(false);
    }
  };

  const displayName =
    [form.first_name, form.last_name].filter(Boolean).join(' ') ||
    me?.display_name ||
    'Operator';
  const avatarSrc = form.avatar_url || FALLBACK_AVATAR;
  const email = profile?.email ?? me?.user?.email ?? '';
  const presence = profile?.status ?? me?.user?.status ?? 'offline';
  const twoFactor = profile?.two_factor_enabled ?? me?.user?.two_factor_enabled ?? false;
  const timezoneOptions = KNOWN_TIMEZONES.some((tz) => tz.value === form.timezone)
    ? KNOWN_TIMEZONES
    : [{ value: form.timezone, label: form.timezone }, ...KNOWN_TIMEZONES];

  return (
    <div className="flex flex-col xl:flex-row gap-6 w-full items-start">
      {/* Main Profile Form Center Column */}
      <div className="flex-1 w-full space-y-6">
        {/* Profile Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
          <div>
            <h2 className="text-lg font-semibold text-[#F2F1EE] tracking-tight">Operator Profile</h2>
            <p className="text-xs text-[#A8A8AB] mt-0.5">
              View and update your personal credentials, organizational roles, and platform display preferences.
            </p>
          </div>
          <button
            id="save-profile-button"
            type="button"
            onClick={handleSave}
            disabled={isSaving || loading}
            aria-describedby={saveError ? 'profile-save-error' : undefined}
            className="px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] disabled:opacity-60 text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold flex items-center justify-center gap-2 cursor-pointer transition-colors shrink-0"
          >
            {isSaving ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-black border-t-transparent rounded-full animate-spin" />
                <span>Saving...</span>
              </>
            ) : (
              <>
                <Check size={14} />
                <span>Save Changes</span>
              </>
            )}
          </button>
        </div>

        {loading && (
          <p className="text-xs font-mono text-[#6B6B6E]">Loading your profile…</p>
        )}

        {loadError && (
          <p role="alert" className="text-xs font-mono text-red-400">
            {loadError}
          </p>
        )}

        {saveError && (
          <p id="profile-save-error" role="alert" className="text-xs font-mono text-red-400">
            {saveError}
          </p>
        )}

        {/* Section 1: Profile Information */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#F2F1EE] tracking-tight">Profile Information</h3>
          </div>

          <div className="flex flex-col sm:flex-row gap-6 items-start">
            {/* Avatar Photo Section */}
            <div className="flex flex-col items-center gap-3 shrink-0 self-center sm:self-start">
              <div className="relative group">
                <img
                  src={avatarSrc}
                  alt={displayName}
                  className="w-24 h-24 rounded-full object-cover ring-2 ring-white/10 shadow-lg group-hover:ring-[#FFB020]/60 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setIsPhotoModalOpen(true)}
                  className="absolute bottom-0 right-0 w-7 h-7 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-full flex items-center justify-center shadow-md border-2 border-[#0A0A0B] cursor-pointer transition-transform hover:scale-105"
                  title="Change avatar"
                >
                  <Pencil size={12} />
                  <span className="sr-only">Change avatar</span>
                </button>
              </div>

              <button
                type="button"
                onClick={() => setIsPhotoModalOpen(true)}
                className="px-3 py-1.5 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-[#F2F1EE] text-xs font-mono font-medium rounded-lg border border-white/[0.08] transition-colors cursor-pointer"
              >
                Change Photo
              </button>

              <span className="text-[11px] text-[#6B6B6E] text-center font-mono">
                Image URL or preset. No file upload yet.
              </span>
            </div>

            {/* Form Fields Grid */}
            <div className="flex-1 w-full grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* First Name */}
              <div>
                <label
                  htmlFor="profile-first-name"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  First Name
                </label>
                <input
                  id="profile-first-name"
                  type="text"
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="First name"
                />
              </div>

              {/* Last Name */}
              <div>
                <label
                  htmlFor="profile-last-name"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  Last Name
                </label>
                <input
                  id="profile-last-name"
                  type="text"
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="Last name"
                />
              </div>

              {/* Email Address (read-only: login identifier) */}
              <div>
                <label
                  htmlFor="profile-email"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  Email Address
                </label>
                <input
                  id="profile-email"
                  type="email"
                  value={email}
                  readOnly
                  disabled
                  aria-describedby="profile-email-note"
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.08] rounded-lg text-xs text-[#A8A8AB] outline-none cursor-not-allowed"
                />
                <p id="profile-email-note" className="text-[11px] text-[#6B6B6E] font-mono mt-1">
                  Login identifier — not editable yet.
                </p>
              </div>

              {/* Job Title */}
              <div>
                <label
                  htmlFor="profile-title"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  Job Title / Designation
                </label>
                <input
                  id="profile-title"
                  type="text"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="Job Title"
                />
              </div>

              {/* Phone Number */}
              <div>
                <label
                  htmlFor="profile-phone"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  Phone Number
                </label>
                <input
                  id="profile-phone"
                  type="tel"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="+91 98765 43210"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Preferences */}
        <div className="space-y-4 pt-2 border-t border-white/[0.08]">
          <div>
            <h3 className="text-sm font-semibold text-[#F2F1EE] tracking-tight">Localization</h3>
            <p className="text-xs text-[#A8A8AB] mt-0.5">
              The time zone timestamps across the platform are rendered in.
            </p>
          </div>

          {/* Time Zone */}
          <div className="space-y-1">
            <label
              htmlFor="profile-timezone"
              className="block text-xs font-medium text-[#F2F1EE] font-mono"
            >
              Time Zone
            </label>
            <p className="text-[11px] text-[#6B6B6E]">Select your local time zone</p>
            <div className="relative">
              <select
                id="profile-timezone"
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                className="w-full appearance-none px-3.5 py-2.5 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none cursor-pointer pr-10"
              >
                {timezoneOptions.map((tz) => (
                  <option key={tz.value} value={tz.value}>
                    {tz.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                size={14}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#6B6B6E] pointer-events-none"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Right Column / Context Panels */}
      <div className="w-full xl:w-80 shrink-0 space-y-4">
        {/* Card 1: Account Status */}
        <div className="bg-[#141416] border border-white/[0.08] rounded-xl p-4 space-y-3.5">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-[#F2F1EE] font-mono uppercase">Account Status</h4>
            <span className="px-2 py-0.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[11px] font-mono font-medium rounded">
              {presence}
            </span>
          </div>

          <div className="space-y-2.5 text-xs font-mono">
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Member since</span>
              <span className="text-[#F2F1EE] font-medium">{formatMoment(profile?.created_at)}</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Last login</span>
              <span className="text-[#F2F1EE] font-medium">{formatMoment(profile?.last_login_at)}</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Account type</span>
              <span className="text-[#FFB020] font-medium">{role || '—'}</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>2FA Status</span>
              <span className={twoFactor ? 'text-emerald-400 font-medium' : 'text-[#6B6B6E] font-medium'}>
                {twoFactor ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Sessions pointer — the real session list lives on the Security tab */}
        <div className="bg-[#141416] border border-white/[0.08] rounded-xl p-4 space-y-2">
          <h4 className="text-xs font-semibold text-[#F2F1EE] font-mono uppercase">Session Activity</h4>
          <p className="text-[11px] text-[#6B6B6E] font-mono">
            Signed-in devices and sign-out controls live on the Security tab.
          </p>
        </div>
      </div>

      {/* Modal: Change Photo */}
      {isPhotoModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#141416] border border-white/[0.12] rounded-xl p-5 max-w-sm w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
              <h3 className="text-sm font-semibold text-[#F2F1EE]">Update Profile Photo</h3>
              <button
                type="button"
                onClick={() => setIsPhotoModalOpen(false)}
                className="text-[#6B6B6E] hover:text-[#F2F1EE] cursor-pointer"
              >
                <X size={16} />
                <span className="sr-only">Close</span>
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex justify-center">
                <img
                  src={avatarSrc}
                  alt="Preview"
                  className="w-24 h-24 rounded-full object-cover ring-4 ring-[#FFB020]/40"
                />
              </div>

              <div>
                <label
                  htmlFor="profile-avatar-url"
                  className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono"
                >
                  Avatar Image URL
                </label>
                <input
                  id="profile-avatar-url"
                  type="url"
                  value={form.avatar_url}
                  onChange={(e) => setForm({ ...form, avatar_url: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="https://example.com/avatar.png"
                />
              </div>

              <div className="space-y-2">
                <span className="text-[11px] text-[#A8A8AB] font-mono font-medium block">
                  Or pick a preset avatar:
                </span>
                <div className="grid grid-cols-4 gap-2">
                  {PRESET_AVATARS.map((url, i) => (
                    <button
                      key={url}
                      type="button"
                      onClick={() => {
                        setForm((p) => ({ ...p, avatar_url: url }));
                        setIsPhotoModalOpen(false);
                      }}
                      className="rounded-full cursor-pointer"
                    >
                      <img
                        src={url}
                        alt={`Preset avatar ${i + 1}`}
                        className="w-12 h-12 rounded-full object-cover ring-1 ring-white/20 hover:ring-[#FFB020] transition-transform hover:scale-105"
                      />
                    </button>
                  ))}
                </div>
              </div>

              <button
                type="button"
                onClick={() => setIsPhotoModalOpen(false)}
                className="w-full py-2.5 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold cursor-pointer transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
