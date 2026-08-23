import { useState, useRef } from 'react';
import {
  Pencil,
  Monitor,
  Sun,
  Moon,
  Smartphone,
  ChevronDown,
  Plus,
  Check,
  X,
  Upload,
} from 'lucide-react';
import type { UserProfileData, SessionActivityItem, LinkedAccountItem } from './types';

interface ProfileSettingsTabProps {
  onSaveToast: () => void;
}

const defaultProfileData: UserProfileData = {
  fullName: 'Navi Yanka',
  username: 'navi_yanka',
  email: 'navi.yanka@nvlabs.dev',
  jobTitle: 'Operator',
  phone: '+91 98765 43210',
  phoneCountry: 'IN',
  department: 'Operations',
  bio: 'Passionate about cybersecurity, automation, and building intelligent autonomous systems.',
  avatarUrl: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80',
  language: 'en-US',
  timeZone: 'Asia/Kolkata',
  dateFormat: 'MMM DD, YYYY',
  theme: 'dark',
  weekStartsOn: 'Monday',
};

const initialSessions: SessionActivityItem[] = [
  {
    id: 's1',
    device: 'Windows',
    browser: 'Chrome',
    ip: '127.0.0.1',
    timestamp: 'Current Session',
    isActive: true,
    type: 'desktop',
  },
  {
    id: 's2',
    device: 'Windows',
    browser: 'Chrome',
    ip: '127.0.0.1',
    timestamp: 'May 16, 2024, 09:12 AM',
    isActive: false,
    type: 'desktop',
  },
  {
    id: 's3',
    device: 'Android',
    browser: 'Chrome',
    ip: '223.18.45.67',
    timestamp: 'May 15, 2024, 07:45 PM',
    isActive: false,
    type: 'mobile',
  },
  {
    id: 's4',
    device: 'Windows',
    browser: 'Edge',
    ip: '127.0.0.1',
    timestamp: 'May 15, 2024, 03:22 PM',
    isActive: false,
    type: 'desktop',
  },
  {
    id: 's5',
    device: 'iOS',
    browser: 'Safari',
    ip: '106.51.12.34',
    timestamp: 'May 14, 2024, 11:08 AM',
    isActive: false,
    type: 'mobile',
  },
];

const initialLinkedAccounts: LinkedAccountItem[] = [
  {
    id: 'acc1',
    provider: 'google',
    name: 'Google',
    identifier: 'navi.yanka@gmail.com',
    connected: true,
    connectedAt: 'March 2024',
  },
  {
    id: 'acc2',
    provider: 'github',
    name: 'GitHub',
    identifier: 'navi-yanka',
    connected: true,
    connectedAt: 'March 2024',
  },
  {
    id: 'acc3',
    provider: 'slack',
    name: 'Slack',
    identifier: 'navi_yanka',
    connected: true,
    connectedAt: 'April 2024',
  },
];

const countryCodes = [
  { code: 'IN', prefix: '+91', name: 'India', flag: '🇮🇳' },
  { code: 'US', prefix: '+1', name: 'United States', flag: '🇺🇸' },
  { code: 'GB', prefix: '+44', name: 'United Kingdom', flag: '🇬🇧' },
  { code: 'DE', prefix: '+49', name: 'Germany', flag: '🇩🇪' },
  { code: 'JP', prefix: '+81', name: 'Japan', flag: '🇯🇵' },
  { code: 'SG', prefix: '+65', name: 'Singapore', flag: '🇸🇬' },
  { code: 'AE', prefix: '+971', name: 'United Arab Emirates', flag: '🇦🇪' },
];

export function ProfileSettingsTab({ onSaveToast }: ProfileSettingsTabProps) {
  const [profile, setProfile] = useState<UserProfileData>(() => {
    try {
      const saved = localStorage.getItem('nvlabs_user_profile');
      return saved ? { ...defaultProfileData, ...JSON.parse(saved) } : defaultProfileData;
    } catch {
      return defaultProfileData;
    }
  });

  const [sessions, setSessions] = useState<SessionActivityItem[]>(initialSessions);
  const [linkedAccounts, setLinkedAccounts] = useState<LinkedAccountItem[]>(initialLinkedAccounts);
  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState(false);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);
  const [isManageModalOpen, setIsManageModalOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPhoneDropdownOpen, setIsPhoneDropdownOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedCountry =
    countryCodes.find((c) => c.code === profile.phoneCountry) || countryCodes[0];

  const handleSave = () => {
    setIsSaving(true);
    try {
      localStorage.setItem('nvlabs_user_profile', JSON.stringify(profile));
    } catch {
      // ignore
    }
    setTimeout(() => {
      setIsSaving(false);
      onSaveToast();
    }, 400);
  };

  const handleAvatarFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.size > 2 * 1024 * 1024) {
        alert('File size exceeds 2MB limit.');
        return;
      }
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          setProfile((p) => ({ ...p, avatarUrl: event.target!.result as string }));
          setIsPhotoModalOpen(false);
        }
      };
      reader.readAsDataURL(file);
    }
  };

  const terminateSession = (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
  };

  const toggleAccountConnection = (id: string) => {
    setLinkedAccounts((prev) =>
      prev.map((acc) => (acc.id === id ? { ...acc, connected: !acc.connected } : acc))
    );
  };

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
            disabled={isSaving}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold tracking-wide transition-colors shadow-sm cursor-pointer disabled:opacity-50"
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

        {/* Section 1: Profile Information */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#F2F1EE] tracking-tight">Profile Information</h3>
            <span className="text-[11px] font-mono text-[#6B6B6E]">Operator ID: OP-9042</span>
          </div>

          <div className="flex flex-col sm:flex-row gap-6 items-start">
            {/* Avatar Photo Section */}
            <div className="flex flex-col items-center gap-3 shrink-0 self-center sm:self-start">
              <div className="relative group">
                <img
                  src={profile.avatarUrl}
                  alt={profile.fullName}
                  className="w-24 h-24 rounded-full object-cover ring-2 ring-white/10 shadow-lg group-hover:ring-[#FFB020]/60 transition-all"
                />
                <button
                  type="button"
                  onClick={() => setIsPhotoModalOpen(true)}
                  className="absolute bottom-0 right-0 w-7 h-7 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-full flex items-center justify-center shadow-md border-2 border-[#0A0A0B] cursor-pointer transition-transform hover:scale-105"
                  title="Change avatar"
                >
                  <Pencil size={12} />
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
                JPG, PNG or WebP. Max 2MB.
              </span>
            </div>

            {/* Form Fields Grid */}
            <div className="flex-1 w-full grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Full Name */}
              <div>
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Full Name
                </label>
                <input
                  type="text"
                  value={profile.fullName}
                  onChange={(e) => setProfile({ ...profile, fullName: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="Your full name"
                />
              </div>

              {/* Username */}
              <div>
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Username
                </label>
                <input
                  type="text"
                  value={profile.username}
                  onChange={(e) => setProfile({ ...profile, username: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="username"
                />
              </div>

              {/* Email Address */}
              <div>
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Email Address
                </label>
                <input
                  type="email"
                  value={profile.email}
                  onChange={(e) => setProfile({ ...profile, email: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="email@example.com"
                />
              </div>

              {/* Job Title */}
              <div>
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Job Title / Designation
                </label>
                <input
                  type="text"
                  value={profile.jobTitle}
                  onChange={(e) => setProfile({ ...profile, jobTitle: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="Job Title"
                />
              </div>

              {/* Phone Number with Country Select */}
              <div className="relative">
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Phone Number
                </label>
                <div className="flex items-center">
                  <input
                    type="text"
                    value={profile.phone}
                    onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
                    className="w-full pl-3 pr-16 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                    placeholder="+91 98765 43210"
                  />
                  <div className="absolute right-2 flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => setIsPhoneDropdownOpen(!isPhoneDropdownOpen)}
                      className="flex items-center gap-1 px-1.5 py-1 text-xs hover:bg-white/[0.06] rounded cursor-pointer transition-colors"
                    >
                      <span>{selectedCountry?.flag || '🇮🇳'}</span>
                      <ChevronDown size={12} className="text-[#6B6B6E]" />
                    </button>
                  </div>
                </div>

                {/* Country Dropdown Popover */}
                {isPhoneDropdownOpen && (
                  <div className="absolute z-30 right-0 mt-1 w-56 bg-[#141416] border border-white/[0.12] rounded-lg shadow-xl py-1 text-xs max-h-48 overflow-y-auto">
                    {countryCodes.map((country) => (
                      <button
                        key={country.code}
                        type="button"
                        onClick={() => {
                          setProfile({ ...profile, phoneCountry: country.code });
                          setIsPhoneDropdownOpen(false);
                        }}
                        className="w-full px-3 py-1.5 flex items-center justify-between text-left hover:bg-white/[0.06] text-[#F2F1EE] cursor-pointer"
                      >
                        <span className="flex items-center gap-2">
                          <span>{country.flag}</span>
                          <span>{country.name}</span>
                        </span>
                        <span className="text-[#6B6B6E] font-mono">{country.prefix}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Department */}
              <div>
                <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">
                  Department / Squad
                </label>
                <input
                  type="text"
                  value={profile.department}
                  onChange={(e) => setProfile({ ...profile, department: e.target.value })}
                  className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors"
                  placeholder="Department"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: About You */}
        <div className="space-y-3 pt-2">
          <h3 className="text-sm font-semibold text-[#F2F1EE] tracking-tight">Operator Bio</h3>
          <div>
            <label className="block text-xs font-medium text-[#A8A8AB] mb-1.5 font-mono">Summary & Mission Focus</label>
            <div className="relative">
              <textarea
                rows={3}
                maxLength={200}
                value={profile.bio}
                onChange={(e) => setProfile({ ...profile, bio: e.target.value })}
                className="w-full px-3 py-2 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] focus:ring-1 focus:ring-[#FFB020]/20 rounded-lg text-xs text-[#F2F1EE] placeholder-[#6B6B6E] outline-none transition-colors resize-none"
                placeholder="Tell us a little bit about yourself and your role..."
              />
              <div className="absolute bottom-2 right-3 text-[11px] font-mono text-[#6B6B6E]">
                {profile.bio.length}/200
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: Preferences */}
        <div className="space-y-4 pt-2 border-t border-white/[0.08]">
          <div>
            <h3 className="text-sm font-semibold text-[#F2F1EE] tracking-tight">Localization & Display</h3>
            <p className="text-xs text-[#A8A8AB] mt-0.5">
              Customize your platform regional format, interface theme, and timestamp schemas.
            </p>
          </div>

          <div className="space-y-4">
            {/* Language */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#F2F1EE] font-mono">Language</label>
              <p className="text-[11px] text-[#6B6B6E]">Select your preferred language</p>
              <div className="relative">
                <select
                  value={profile.language}
                  onChange={(e) => setProfile({ ...profile, language: e.target.value })}
                  className="w-full appearance-none px-3.5 py-2.5 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none cursor-pointer pr-10"
                >
                  <option value="en-US">English (US)</option>
                  <option value="en-GB">English (UK)</option>
                  <option value="de-DE">Deutsch (German)</option>
                  <option value="ja-JP">日本語 (Japanese)</option>
                  <option value="fr-FR">Français (French)</option>
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#6B6B6E] pointer-events-none"
                />
              </div>
            </div>

            {/* Time Zone */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#F2F1EE] font-mono">Time Zone</label>
              <p className="text-[11px] text-[#6B6B6E]">Select your local time zone</p>
              <div className="relative">
                <select
                  value={profile.timeZone}
                  onChange={(e) => setProfile({ ...profile, timeZone: e.target.value })}
                  className="w-full appearance-none px-3.5 py-2.5 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none cursor-pointer pr-10"
                >
                  <option value="Asia/Kolkata">(GMT+05:30) Asia/Kolkata</option>
                  <option value="America/New_York">(GMT-05:00) Eastern Time (US & Canada)</option>
                  <option value="America/Los_Angeles">(GMT-08:00) Pacific Time (US & Canada)</option>
                  <option value="Europe/London">(GMT+00:00) London, Edinburgh, Dublin</option>
                  <option value="Europe/Berlin">(GMT+01:00) Berlin, Frankfurt, Paris</option>
                  <option value="Asia/Tokyo">(GMT+09:00) Tokyo, Osaka, Sapporo</option>
                  <option value="Asia/Singapore">(GMT+08:00) Singapore, Kuala Lumpur</option>
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#6B6B6E] pointer-events-none"
                />
              </div>
            </div>

            {/* Date Format */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#F2F1EE] font-mono">Date Format</label>
              <p className="text-[11px] text-[#6B6B6E]">Choose your preferred date format</p>
              <div className="relative">
                <select
                  value={profile.dateFormat}
                  onChange={(e) => setProfile({ ...profile, dateFormat: e.target.value })}
                  className="w-full appearance-none px-3.5 py-2.5 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none cursor-pointer pr-10"
                >
                  <option value="MMM DD, YYYY">May 16, 2024 (MMM DD, YYYY)</option>
                  <option value="YYYY-MM-DD">2024-05-16 (YYYY-MM-DD)</option>
                  <option value="DD/MM/YYYY">16/05/2024 (DD/MM/YYYY)</option>
                  <option value="MM/DD/YYYY">05/16/2024 (MM/DD/YYYY)</option>
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#6B6B6E] pointer-events-none"
                />
              </div>
            </div>

            {/* Theme Toggle Selection */}
            <div className="space-y-2">
              <div>
                <label className="block text-xs font-medium text-[#F2F1EE] font-mono">Theme Mode</label>
                <p className="text-[11px] text-[#6B6B6E]">Choose your interface presentation mode</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* System */}
                <button
                  type="button"
                  onClick={() => setProfile({ ...profile, theme: 'system' })}
                  className={`flex items-center gap-3 p-3 rounded-lg border text-left transition-all cursor-pointer ${
                    profile.theme === 'system'
                      ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                      : 'bg-[#0A0A0B] border-white/[0.08] text-[#A8A8AB] hover:border-white/[0.2] hover:text-[#F2F1EE]'
                  }`}
                >
                  <Monitor
                    size={18}
                    className={profile.theme === 'system' ? 'text-[#FFB020]' : 'text-[#6B6B6E]'}
                  />
                  <div>
                    <div className="text-xs font-medium text-[#F2F1EE]">System</div>
                    <div className="text-[10px] text-[#6B6B6E] font-mono">Auto detect OS</div>
                  </div>
                </button>

                {/* Light */}
                <button
                  type="button"
                  onClick={() => setProfile({ ...profile, theme: 'light' })}
                  className={`flex items-center gap-3 p-3 rounded-lg border text-left transition-all cursor-pointer ${
                    profile.theme === 'light'
                      ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                      : 'bg-[#0A0A0B] border-white/[0.08] text-[#A8A8AB] hover:border-white/[0.2] hover:text-[#F2F1EE]'
                  }`}
                >
                  <Sun
                    size={18}
                    className={profile.theme === 'light' ? 'text-[#FFB020]' : 'text-[#6B6B6E]'}
                  />
                  <div>
                    <div className="text-xs font-medium text-[#F2F1EE]">Light</div>
                    <div className="text-[10px] text-[#6B6B6E] font-mono">Clean daylight</div>
                  </div>
                </button>

                {/* Dark */}
                <button
                  type="button"
                  onClick={() => setProfile({ ...profile, theme: 'dark' })}
                  className={`flex items-center gap-3 p-3 rounded-lg border text-left transition-all cursor-pointer ${
                    profile.theme === 'dark'
                      ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                      : 'bg-[#0A0A0B] border-white/[0.08] text-[#A8A8AB] hover:border-white/[0.2] hover:text-[#F2F1EE]'
                  }`}
                >
                  <Moon
                    size={18}
                    className={profile.theme === 'dark' ? 'text-[#FFB020]' : 'text-[#6B6B6E]'}
                  />
                  <div>
                    <div className="text-xs font-medium text-[#F2F1EE]">Dark (Default)</div>
                    <div className="text-[10px] text-[#6B6B6E] font-mono">Nexus Obsidian</div>
                  </div>
                </button>
              </div>
            </div>

            {/* Week Starts On */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-[#F2F1EE] font-mono">Week Starts On</label>
              <p className="text-[11px] text-[#6B6B6E]">Select the first day of the weekly sprint cycle</p>
              <div className="relative">
                <select
                  value={profile.weekStartsOn}
                  onChange={(e) =>
                    setProfile({ ...profile, weekStartsOn: e.target.value as 'Monday' | 'Sunday' })
                  }
                  className="w-full appearance-none px-3.5 py-2.5 bg-[#0A0A0B] border border-white/[0.08] focus:border-[#FFB020] rounded-lg text-xs text-[#F2F1EE] outline-none cursor-pointer pr-10"
                >
                  <option value="Monday">Monday</option>
                  <option value="Sunday">Sunday</option>
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#6B6B6E] pointer-events-none"
                />
              </div>
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
              Active
            </span>
          </div>

          <div className="space-y-2.5 text-xs font-mono">
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Member since</span>
              <span className="text-[#F2F1EE] font-medium">March 12, 2024</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Last login</span>
              <span className="text-[#F2F1EE] font-medium">May 16, 2024, 10:25 AM</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>Account type</span>
              <span className="text-[#FFB020] font-medium">Operator</span>
            </div>
            <div className="flex items-center justify-between text-[#A8A8AB]">
              <span>2FA Status</span>
              <span className="text-emerald-400 font-medium">Enforced</span>
            </div>
          </div>
        </div>

        {/* Card 2: Session Activity */}
        <div className="bg-[#141416] border border-white/[0.08] rounded-xl p-4 space-y-3.5">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-[#F2F1EE] font-mono uppercase">Session Activity</h4>
            <button
              type="button"
              onClick={() => setIsSessionsModalOpen(true)}
              className="text-xs font-mono font-medium text-[#FFB020] hover:text-[#FFC453] cursor-pointer transition-colors"
            >
              View All
            </button>
          </div>

          {/* Timeline List */}
          <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-px before:bg-white/[0.1]">
            {sessions.map((sess) => (
              <div key={sess.id} className="relative group">
                {/* Node icon */}
                <div
                  className={`absolute -left-6 top-0.5 w-4 h-4 rounded flex items-center justify-center ${
                    sess.isActive ? 'bg-[#FFB020] text-[#0A0A0B] ring-2 ring-[#FFB020]/30' : 'text-[#6B6B6E]'
                  }`}
                >
                  {sess.type === 'mobile' ? <Smartphone size={10} /> : <Monitor size={10} />}
                </div>

                <div>
                  <div className="flex items-center gap-1.5 text-xs font-mono">
                    <span className="text-[#F2F1EE] font-medium">{sess.timestamp}</span>
                    {sess.isActive && (
                      <span className="text-emerald-400 text-[10px] font-mono font-medium flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        Active
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-[#6B6B6E] font-mono mt-0.5">
                    {sess.device} • {sess.browser} • {sess.ip}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Card 3: Linked Accounts */}
        <div className="bg-[#141416] border border-white/[0.08] rounded-xl p-4 space-y-3.5">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-[#F2F1EE] font-mono uppercase">Linked Accounts</h4>
            <button
              type="button"
              onClick={() => setIsManageModalOpen(true)}
              className="text-xs font-mono font-medium text-[#FFB020] hover:text-[#FFC453] cursor-pointer transition-colors"
            >
              Manage
            </button>
          </div>

          <div className="space-y-2.5">
            {linkedAccounts.map((acc) => (
              <div
                key={acc.id}
                className="flex items-center justify-between p-2 rounded-lg bg-[#0A0A0B] border border-white/[0.04]"
              >
                <div className="flex items-center gap-2.5">
                  {acc.provider === 'google' && (
                    <div className="w-6 h-6 rounded bg-white/[0.06] flex items-center justify-center font-bold text-xs text-red-400">
                      G
                    </div>
                  )}
                  {acc.provider === 'github' && (
                    <div className="w-6 h-6 rounded bg-white/[0.06] flex items-center justify-center font-bold text-xs text-white">
                      🐙
                    </div>
                  )}
                  {acc.provider === 'slack' && (
                    <div className="w-6 h-6 rounded bg-white/[0.06] flex items-center justify-center font-bold text-xs text-amber-400">
                      #
                    </div>
                  )}
                  <div>
                    <div className="text-xs font-medium text-[#F2F1EE]">{acc.name}</div>
                    <div className="text-[11px] text-[#6B6B6E] font-mono truncate max-w-[120px]">
                      {acc.identifier}
                    </div>
                  </div>
                </div>

                <span
                  className={`text-[11px] font-mono font-medium ${
                    acc.connected ? 'text-emerald-400' : 'text-[#6B6B6E]'
                  }`}
                >
                  {acc.connected ? 'Connected' : 'Disconnected'}
                </span>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={() => setIsConnectModalOpen(true)}
            className="w-full py-2 bg-[#1C1C1F] hover:bg-[#2A2A2E] text-[#F2F1EE] border border-[#FFB020]/30 hover:border-[#FFB020] rounded-lg text-xs font-mono font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
          >
            <Plus size={13} className="text-[#FFB020]" />
            <span>Connect Account</span>
          </button>
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
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex justify-center">
                <img
                  src={profile.avatarUrl}
                  alt="Preview"
                  className="w-24 h-24 rounded-full object-cover ring-4 ring-[#FFB020]/40"
                />
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/png, image/jpeg, image/webp"
                className="hidden"
                onChange={handleAvatarFile}
              />

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="w-full py-2.5 bg-[#FFB020] hover:bg-[#E59E1C] text-[#0A0A0B] rounded-lg text-xs font-mono font-semibold flex items-center justify-center gap-2 cursor-pointer transition-colors"
              >
                <Upload size={14} />
                <span>Upload From Device</span>
              </button>

              <div className="space-y-2">
                <span className="text-[11px] text-[#A8A8AB] font-mono font-medium block">
                  Or pick a preset avatar:
                </span>
                <div className="grid grid-cols-4 gap-2">
                  {[
                    'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80',
                    'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80',
                    'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80',
                    'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop&q=80',
                  ].map((url, i) => (
                    <img
                      key={i}
                      src={url}
                      alt={`Preset ${i}`}
                      onClick={() => {
                        setProfile((p) => ({ ...p, avatarUrl: url }));
                        setIsPhotoModalOpen(false);
                      }}
                      className="w-12 h-12 rounded-full object-cover ring-1 ring-white/20 hover:ring-[#FFB020] cursor-pointer transition-transform hover:scale-105"
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal: View All Sessions */}
      {isSessionsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#141416] border border-white/[0.12] rounded-xl p-5 max-w-lg w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
              <div>
                <h3 className="text-sm font-semibold text-[#F2F1EE]">Active & Past Sessions</h3>
                <p className="text-[11px] text-[#6B6B6E] font-mono">
                  Review logged-in operator credentials and active tokens
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsSessionsModalOpen(false)}
                className="text-[#6B6B6E] hover:text-[#F2F1EE] cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-2 max-h-72 overflow-y-auto font-mono">
              {sessions.map((sess) => (
                <div
                  key={sess.id}
                  className="flex items-center justify-between p-3 rounded-lg bg-[#0A0A0B] border border-white/[0.06]"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-white/[0.04] flex items-center justify-center text-[#FFB020]">
                      {sess.type === 'mobile' ? <Smartphone size={14} /> : <Monitor size={14} />}
                    </div>
                    <div>
                      <div className="flex items-center gap-2 text-xs font-medium text-[#F2F1EE]">
                        <span>
                          {sess.device} • {sess.browser}
                        </span>
                        {sess.isActive && (
                          <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono">
                            Current
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-[#6B6B6E] font-mono">
                        {sess.ip} • {sess.timestamp}
                      </div>
                    </div>
                  </div>

                  {!sess.isActive && (
                    <button
                      type="button"
                      onClick={() => terminateSession(sess.id)}
                      className="px-2.5 py-1 text-[11px] font-mono text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded cursor-pointer transition-colors"
                    >
                      Revoke
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="pt-2 border-t border-white/[0.08] flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setSessions((prev) => prev.filter((s) => s.isActive));
                  setIsSessionsModalOpen(false);
                }}
                className="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg text-xs font-mono font-medium transition-colors cursor-pointer"
              >
                Log Out All Other Devices
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Connect Account */}
      {isConnectModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#141416] border border-white/[0.12] rounded-xl p-5 max-w-sm w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
              <h3 className="text-sm font-semibold text-[#F2F1EE]">Connect Third-Party Account</h3>
              <button
                type="button"
                onClick={() => setIsConnectModalOpen(false)}
                className="text-[#6B6B6E] hover:text-[#F2F1EE] cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-2.5">
              {[
                { name: 'Discord', id: 'discord', icon: '🎮' },
                { name: 'Microsoft 365', id: 'microsoft', icon: '💼' },
                { name: 'Linear', id: 'linear', icon: '📐' },
                { name: 'GitLab', id: 'gitlab', icon: '🦊' },
              ].map((prov) => (
                <button
                  key={prov.id}
                  type="button"
                  onClick={() => {
                    setLinkedAccounts((prev) => [
                      ...prev,
                      {
                        id: `acc-${Date.now()}`,
                        provider: prov.id as any,
                        name: prov.name,
                        identifier: `navi.yanka@${prov.id}.com`,
                        connected: true,
                        connectedAt: 'Just now',
                      },
                    ]);
                    setIsConnectModalOpen(false);
                  }}
                  className="w-full flex items-center justify-between p-3 rounded-lg bg-[#0A0A0B] hover:bg-white/[0.04] border border-white/[0.06] text-left transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-base">{prov.icon}</span>
                    <span className="text-xs font-medium text-[#F2F1EE]">{prov.name}</span>
                  </div>
                  <span className="text-xs text-[#FFB020] font-mono font-medium">+ Connect</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal: Manage Linked Accounts */}
      {isManageModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#141416] border border-white/[0.12] rounded-xl p-5 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
              <h3 className="text-sm font-semibold text-[#F2F1EE]">Manage SSO & OAuth Links</h3>
              <button
                type="button"
                onClick={() => setIsManageModalOpen(false)}
                className="text-[#6B6B6E] hover:text-[#F2F1EE] cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              {linkedAccounts.map((acc) => (
                <div
                  key={acc.id}
                  className="flex items-center justify-between p-3 rounded-lg bg-[#0A0A0B] border border-white/[0.06]"
                >
                  <div>
                    <div className="text-xs font-semibold text-[#F2F1EE]">{acc.name}</div>
                    <div className="text-[11px] text-[#6B6B6E] font-mono">{acc.identifier}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleAccountConnection(acc.id)}
                    className={`px-3 py-1.5 text-xs font-mono font-medium rounded-lg transition-colors cursor-pointer ${
                      acc.connected
                        ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                        : 'bg-[#FFB020] text-[#0A0A0B] hover:bg-[#E59E1C]'
                    }`}
                  >
                    {acc.connected ? 'Disconnect' : 'Reconnect'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
